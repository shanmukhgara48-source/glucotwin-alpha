"""Persistent clinician workflow around causal replay and synthetic intake."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.auth import admin_user, current_user
from backend.storage import audit, connection, utc_now

router = APIRouter()
DEFAULT_MONITORING = {"timezone": "Asia/Kolkata", "start_hour": 9, "end_hour": 17,
                      "reviewer_id": "reviewer", "days": [0, 1, 2, 3, 4]}
PUBLIC_DATASET_URL = "https://figshare.com/articles/dataset/diabetes_datasets_zip/21600933"


def result(data):
    from backend.main import success
    return success(data)


def iso_time(value: str, required_zone: bool = True) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(422, "Use an ISO 8601 timestamp with a timezone offset.")
    if parsed.tzinfo is None:
        if required_zone:
            raise HTTPException(422, "Imported timestamps must include Z or a timezone offset.")
        return parsed.isoformat()
    return parsed.astimezone(timezone.utc).isoformat()


def time_key(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def seed_profiles():
    from backend.main import data_store
    with connection() as db:
        for profile in data_store()["patients"]:
            db.execute("INSERT OR IGNORE INTO profiles VALUES(?,?,?)", ("demo-clinic", str(profile["id"]), json.dumps(profile)))
        demo = {"id": "SIM-001", "name": "Synthetic stream patient", "age": 55, "sex": "Female", "bmi": 27,
                "diabetes_duration_years": 8, "recording_id": "SIM-001-stream", "source": "synthetic",
                "provenance": "Fully synthetic demonstration; excluded from measured-data evaluation."}
        db.execute("INSERT OR IGNORE INTO profiles VALUES(?,?,?)", ("demo-clinic", demo["id"], json.dumps(demo)))


def get_profile(patient_id: str, user: dict) -> dict:
    seed_profiles()
    with connection() as db:
        row = db.execute("SELECT profile_json FROM profiles WHERE clinic_id=? AND patient_id=?", (user["clinic_id"], patient_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Patient is unavailable in this clinic.")
    return json.loads(row[0])


def clinic_patients(user: dict) -> list[dict]:
    seed_profiles()
    with connection() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT profile_json FROM profiles WHERE clinic_id=? ORDER BY patient_id", (user["clinic_id"],))]


def context_at(patient_id: str, user: dict, at: str) -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT * FROM context WHERE clinic_id=? AND patient_id=? ORDER BY observed_at,id", (user["clinic_id"], patient_id)).fetchall()
    return [{**dict(row), "value": json.loads(row["value_json"])} for row in rows
            if time_key(row["observed_at"]) <= time_key(at) and time_key(row["available_at"]) <= time_key(at)]


def profile_at(patient_id: str, user: dict, at: str) -> dict:
    profile = get_profile(patient_id, user).copy()
    profile["baseline_context"] = {key: profile.get(key) for key in ["age", "sex", "bmi", "diabetes_duration_years"]}
    entries = context_at(patient_id, user, at)
    # Only dated structured historical context enters the model; free text is timeline-only.
    for entry in entries:
        if entry["kind"] == "historical" and isinstance(entry["value"], dict):
            for key in ["age", "sex", "bmi", "diabetes_duration_years"]:
                if key in entry["value"]:
                    profile[key] = entry["value"][key]
    profile["context_entries"] = [{key: row[key] for key in ["id", "kind", "value", "observed_at", "available_at", "provenance"]} for row in entries]
    return profile


def monitoring(user: dict, at: str | None = None) -> dict:
    with connection() as db:
        row = db.execute("SELECT config_json FROM monitoring WHERE clinic_id=?", (user["clinic_id"],)).fetchone()
    config = json.loads(row[0]) if row else DEFAULT_MONITORING.copy()
    value = iso_time(at, required_zone=False) if at else utc_now()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # Historical naive timestamps run a labeled virtual local clock, never imply actual staffing in 2021.
    local = parsed if parsed.tzinfo is None else parsed.astimezone(ZoneInfo(config["timezone"]))
    active = local.weekday() in config["days"] and config["start_hour"] <= local.hour < config["end_hour"]
    return {**config, "active": active, "current_time": value, "clock_kind": "recorded" if at else "wall_clock",
            "message": "Staffed monitoring active." if active else "Monitoring inactive; items retained for the next staffed window."}


def imported_records(patient_id: str, user: dict, at: str | None = None) -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT timestamp,available_at,glucose_mg_dl,source FROM observations WHERE clinic_id=? AND patient_id=? ORDER BY timestamp", (user["clinic_id"], patient_id)).fetchall()
    return [dict(row) for row in rows if at is None or (time_key(row["timestamp"]) <= time_key(at) and time_key(row["available_at"]) <= time_key(at))]


def snapshot_for(patient_id: str, user: dict, cursor: int = 0, scenario: str = "recorded", at: str | None = None) -> dict:
    from backend.main import build_snapshot, data_store
    profile = get_profile(patient_id, user)
    if at:
        at = iso_time(at, required_zone=False)
    if profile.get("source") in {"synthetic", "anonymized_public"}:
        full = imported_records(patient_id, user)
        if not full:
            raise HTTPException(409, "Synthetic patient has no readings. Import a CSV/FHIR bundle or send simulated readings first.")
        virtual_now = at or full[min(max(cursor, 0), len(full) - 1)]["timestamp"]
        records = imported_records(patient_id, user, virtual_now)
        if not records:
            raise HTTPException(409, "No readings were available at this time.")
        snapshot = build_snapshot(profile_at(patient_id, user, virtual_now), records, len(records) - 1, scenario, data_store()["bundle"], current_time=virtual_now)
        snapshot["total_observations"] = len(full)
        snapshot["cursor"] = min(max(cursor, 0), len(full) - 1)
        snapshot["playback"]["kind"] = "public_csv_replay" if profile.get("source") == "anonymized_public" else "synthetic_stream"
    else:
        records = data_store()["observations"].get(patient_id, [])
        if not records:
            raise HTTPException(503, "Patient observations are unavailable.")
        virtual_now = records[min(max(cursor, 0), len(records) - 1)]["timestamp"]
        snapshot = build_snapshot(profile_at(patient_id, user, virtual_now), records, cursor, scenario, data_store()["bundle"])
    snapshot["monitoring"] = monitoring(user, snapshot["current_time"])
    snapshot["clinical_status"] = "Doctor workflow review pending; research prototype."
    return snapshot


def mature_outcomes(patient_id: str, user: dict, records: list[dict], cutoff: str, db=None):
    """Append observed outcomes on explicit mutations; never rewrite an issuance."""
    known = {time_key(row["timestamp"]): row for row in records
             if time_key(row["timestamp"]) <= time_key(cutoff) and time_key(row.get("available_at", row["timestamp"])) <= time_key(cutoff)}
    with (nullcontext(db) if db is not None else connection()) as db:
        rows = db.execute("SELECT id,issued_at,snapshot_json FROM forecasts WHERE clinic_id=? AND patient_id=?", (user["clinic_id"], patient_id)).fetchall()
        for row in rows:
            snapshot = json.loads(row["snapshot_json"])
            clinic = snapshot.get("clinic_model") or {}
            curves = clinic.get("forecasts", {}).get(clinic.get("model", {}).get("primary", "population"), []) or snapshot.get("forecasts", {}).get("population", []) or snapshot.get("forecasts", {}).get("twin", [])
            origin = time_key(row["issued_at"])
            for point in curves:
                target = time_key(point["timestamp"])
                observed = known.get(target)
                if observed is None:
                    continue
                horizon = point["horizon_minutes"]
                expected = [origin + timedelta(minutes=offset) for offset in range(15, horizon + 1, 15)]
                event = int(any(known[stamp]["glucose_mg_dl"] > 180 for stamp in expected)) if all(stamp in known for stamp in expected) else None
                current = db.execute("INSERT OR IGNORE INTO forecast_outcomes(clinic_id,forecast_id,horizon_minutes,target_time,available_at,actual_glucose_mg_dl,event_occurred,provenance,recorded_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                     (user["clinic_id"], row["id"], horizon, point["timestamp"], observed.get("available_at", observed["timestamp"]), observed["glucose_mg_dl"], event, observed.get("source", "measured"), utc_now()))
                if current.rowcount:
                    audit(db, user, "forecast.outcome_observed", str(row["id"]), {"horizon_minutes": horizon, "target_time": point["timestamp"]})


class Capture(BaseModel):
    cursor: int = Field(default=0, ge=0)
    scenario: str = "recorded"
    current_time: str | None = None


@router.post("/api/clinic/capture/{patient_id}")
def capture(patient_id: str, payload: Capture, user: dict = Depends(current_user)):
    if payload.scenario not in {"recorded", "sensor_gap"}:
        raise HTTPException(422, "Unknown replay scenario.")
    snapshot = snapshot_for(patient_id, user, payload.cursor, payload.scenario, payload.current_time)
    model = snapshot.get("clinic_model", {}).get("model", {})
    version = model.get("version", "legacy-local-filter-v1")
    issued = snapshot["current_time"]
    # Persist a compact issuance record; observed targets are derived from prefix-safe evidence later.
    stored = {key: snapshot.get(key) for key in ["patient", "current_time", "cursor", "quality", "forecasts", "alerts", "state", "clinic_model", "monitoring", "scenario"]}
    if stored.get("clinic_model"):
        stored["clinic_model"] = {key: value for key, value in stored["clinic_model"].items() if key != "forecast_history"}
    with connection() as db:
        mature_outcomes(patient_id, user, snapshot["observations"], issued, db)
        db.execute("INSERT OR IGNORE INTO forecasts(clinic_id,patient_id,issued_at,input_cutoff,model_version,scenario,snapshot_json,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                   (user["clinic_id"], patient_id, issued, issued, version, payload.scenario, json.dumps(stored), utc_now()))
        forecast = db.execute("SELECT id FROM forecasts WHERE clinic_id=? AND patient_id=? AND issued_at=? AND scenario=? AND model_version=?",
                              (user["clinic_id"], patient_id, issued, payload.scenario, version)).fetchone()
        forecast_id = forecast["id"]
        quality = snapshot["quality"]["status"]
        current = snapshot["observations"][-1]["glucose_mg_dl"] if snapshot["observations"] else None
        risks = snapshot.get("clinic_model", {}).get("event_risks", [])
        risk = next((row for row in risks if row["horizon_minutes"] == 30), {})
        if quality != "ok":
            kind, message = "missing_data", snapshot["quality"]["message"]
        elif current is not None and current > 180:
            kind, message = "ongoing_high", "Glucose is currently above 180 mg/dL; this is an observed state."
        elif (risk.get("event_eligible") and risk.get("exceeds_threshold")) or (not risks and snapshot["alerts"]):
            kind, message = "predicted_excursion", "Model predicts a new high-glucose excursion; review forecast evidence."
        else:
            kind, message = "forecast_review", "Forecast recorded for clinician review; no excursion warning at this issue time."
        # An open episode deduplicates warnings of the same kind until the reviewer closes it.
        existing = db.execute("SELECT id FROM reviews WHERE clinic_id=? AND forecast_id=? ORDER BY id DESC LIMIT 1",
                              (user["clinic_id"], forecast_id)).fetchone()
        if existing is None:
            existing = db.execute("SELECT id FROM reviews WHERE clinic_id=? AND patient_id=? AND type=? AND status!='closed' ORDER BY id DESC LIMIT 1",
                                  (user["clinic_id"], patient_id, kind)).fetchone()
        if existing:
            review_id = existing["id"]
        else:
            cur = db.execute("INSERT INTO reviews(clinic_id,patient_id,forecast_id,type,status,issued_at,assigned_reviewer,message,probability) VALUES(?,?,?,?,?,?,?,?,?)",
                             (user["clinic_id"], patient_id, forecast_id, kind, "new", issued, snapshot["monitoring"]["reviewer_id"], message, risk.get("probability")))
            review_id = cur.lastrowid
        audit(db, user, "forecast.captured", str(forecast_id), {"review_id": review_id, "patient_id": patient_id})
    return result({"forecast_id": forecast_id, "review_id": review_id, "snapshot": snapshot, "monitoring": snapshot["monitoring"]})


@router.get("/api/clinic/queue")
def queue(at: str | None = None, user: dict = Depends(current_user)):
    if at:
        at = iso_time(at, required_zone=False)
    seed_profiles()
    with connection() as db:
        rows = db.execute("SELECT r.*,f.snapshot_json,p.profile_json FROM reviews r JOIN forecasts f ON r.forecast_id=f.id JOIN profiles p ON p.clinic_id=r.clinic_id AND p.patient_id=r.patient_id WHERE r.clinic_id=? ORDER BY CASE r.type WHEN 'predicted_excursion' THEN 0 WHEN 'ongoing_high' THEN 1 WHEN 'missing_data' THEN 2 ELSE 3 END,r.issued_at DESC", (user["clinic_id"],)).fetchall()
    now = at or utc_now()
    items = []
    for row in rows:
        item = {key: row[key] for key in row.keys() if key not in {"snapshot_json", "profile_json", "clinic_id"}}
        profile, snapshot = json.loads(row["profile_json"]), json.loads(row["snapshot_json"])
        item.update(patient_name=profile.get("name") or f"Patient {profile['id']}", reading_freshness=snapshot["quality"],
                    cursor=snapshot.get("cursor", 0), scenario=snapshot.get("scenario", "recorded"),
                    overdue=bool(row["status"] != "closed" and row["next_review_at"] and time_key(row["next_review_at"]) < time_key(now)),
                    monitoring_at_issue=snapshot.get("monitoring"))
        item["reading_age_at_issue_minutes"] = snapshot["quality"].get("minutes_since_reading")
        item["reading_freshness"] = {**snapshot["quality"], "clock_kind": "recorded_issue",
                                     "age_at_issue_minutes": snapshot["quality"].get("minutes_since_reading"),
                                     "issue_time": row["issued_at"], "live_freshness": False}
        if at and snapshot["quality"].get("last_reading_at"):
            item["reading_freshness"]["age_at_selected_virtual_clock_minutes"] = max(0, (time_key(at) - time_key(snapshot["quality"]["last_reading_at"])).total_seconds() / 60)
        items.append(item)
    return result({"items": items, "pending_count": sum(row["status"] != "closed" for row in items),
                   "overdue_count": sum(row["overdue"] for row in items), "monitoring": monitoring(user, at)})


@router.get("/api/clinic/monitoring")
def get_monitoring(at: str | None = None, user: dict = Depends(current_user)):
    return result(monitoring(user, at))


class Monitoring(BaseModel):
    timezone: str = "Asia/Kolkata"
    start_hour: int = Field(default=9, ge=0, le=23)
    end_hour: int = Field(default=17, ge=1, le=24)
    reviewer_id: str = "reviewer"
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])


@router.put("/api/clinic/monitoring")
def put_monitoring(payload: Monitoring, user: dict = Depends(admin_user)):
    try:
        ZoneInfo(payload.timezone)
    except Exception:
        raise HTTPException(422, "Unknown timezone.")
    if payload.end_hour <= payload.start_hour or not payload.days or any(day not in range(7) for day in payload.days):
        raise HTTPException(422, "Choose a same-day window and valid weekdays (0=Monday).")
    with connection() as db:
        reviewer = db.execute("SELECT id FROM users WHERE id=? AND clinic_id=?", (payload.reviewer_id, user["clinic_id"])).fetchone()
        if not reviewer:
            raise HTTPException(422, "Reviewer must belong to this clinic.")
        db.execute("INSERT INTO monitoring VALUES(?,?) ON CONFLICT(clinic_id) DO UPDATE SET config_json=excluded.config_json", (user["clinic_id"], json.dumps(payload.model_dump())))
        audit(db, user, "monitoring.updated", user["clinic_id"], payload.model_dump())
    return result(monitoring(user))


class ReviewAction(BaseModel):
    status: str
    reason: str = Field(min_length=1, max_length=500)
    note: str = Field(default="", max_length=4000)
    next_review_at: str | None = None
    assigned_reviewer: str | None = None


@router.get("/api/clinic/reviews/{review_id}")
def review_detail(review_id: int, user: dict = Depends(current_user)):
    with connection() as db:
        review = db.execute("SELECT * FROM reviews WHERE id=? AND clinic_id=?", (review_id, user["clinic_id"])).fetchone()
        if not review:
            raise HTTPException(404, "Review is unavailable in this clinic.")
        actions = [dict(row) for row in db.execute("SELECT * FROM actions WHERE review_id=? AND clinic_id=? ORDER BY id", (review_id, user["clinic_id"]))]
    return result({**dict(review), "actions": actions})


@router.patch("/api/clinic/reviews/{review_id}")
@router.post("/api/clinic/reviews/{review_id}/actions")
def review_action(review_id: int, payload: ReviewAction, user: dict = Depends(current_user)):
    transitions = {"new": {"reviewed"}, "reviewed": {"follow_up_planned", "closed"}, "follow_up_planned": {"follow_up_planned", "closed"}, "closed": set()}
    next_time = iso_time(payload.next_review_at) if payload.next_review_at else None
    if payload.status == "follow_up_planned" and not next_time:
        raise HTTPException(422, "A follow-up review time is required.")
    with connection() as db:
        review = db.execute("SELECT * FROM reviews WHERE id=? AND clinic_id=?", (review_id, user["clinic_id"])).fetchone()
        if not review:
            raise HTTPException(404, "Review is unavailable in this clinic.")
        if payload.status not in transitions.get(review["status"], set()):
            raise HTTPException(409, "Review must progress new → reviewed → follow-up planned or closed.")
        assigned = payload.assigned_reviewer or review["assigned_reviewer"]
        if not db.execute("SELECT id FROM users WHERE id=? AND clinic_id=?", (assigned, user["clinic_id"])).fetchone():
            raise HTTPException(422, "Reviewer must belong to this clinic.")
        now = utc_now()
        db.execute("INSERT INTO actions(clinic_id,review_id,actor_id,status,reason,note,next_review_at,recorded_at) VALUES(?,?,?,?,?,?,?,?)", (user["clinic_id"], review_id, user["id"], payload.status, payload.reason, payload.note, next_time, now))
        db.execute("UPDATE reviews SET status=?,assigned_reviewer=?,last_review=?,next_review_at=?,closed_at=? WHERE id=? AND clinic_id=?", (payload.status, assigned, now, next_time, now if payload.status == "closed" else None, review_id, user["clinic_id"]))
        audit(db, user, "review.action", str(review_id), {"status": payload.status})
    return review_detail(review_id, user)


class ContextEntry(BaseModel):
    kind: str
    value: Any
    observed_at: str
    available_at: str | None = None
    provenance: str = "self_reported"


def add_context_entry(patient_id: str, payload: ContextEntry, user: dict, db=None):
    if db is None:
        get_profile(patient_id, user)
    elif not db.execute("SELECT patient_id FROM profiles WHERE clinic_id=? AND patient_id=?", (user["clinic_id"], patient_id)).fetchone():
        raise HTTPException(404, "Patient is unavailable in this clinic.")
    if payload.kind not in {"meal", "activity", "symptom", "note", "historical", "condition", "care_plan"}:
        raise HTTPException(422, "Unknown context kind.")
    if payload.provenance not in {"self_reported", "simulated", "measured"}:
        raise HTTPException(422, "Unknown provenance.")
    if len(json.dumps(payload.value)) > 5000:
        raise HTTPException(422, "Context entry is too long.")
    observed = iso_time(payload.observed_at)
    available = iso_time(payload.available_at or utc_now())
    if time_key(available) < time_key(observed):
        raise HTTPException(422, "Arrival time cannot precede observation time.")
    if payload.kind == "historical":
        if not isinstance(payload.value, dict) or set(payload.value) - {"age", "sex", "bmi", "diabetes_duration_years"}:
            raise HTTPException(422, "Historical context accepts age, sex, bmi and diabetes_duration_years only.")
        for key in ["age", "bmi", "diabetes_duration_years"]:
            if key in payload.value and (not isinstance(payload.value[key], (int, float)) or not math.isfinite(payload.value[key]) or payload.value[key] < 0):
                raise HTTPException(422, "Historical numeric context must be finite and non-negative.")
    with (nullcontext(db) if db is not None else connection()) as db:
        value_json = json.dumps(payload.value, sort_keys=True)
        dedupe_key = hashlib.sha256(json.dumps([payload.kind, value_json, observed, available, payload.provenance]).encode()).hexdigest()
        existing = db.execute("SELECT id FROM context WHERE clinic_id=? AND patient_id=? AND dedupe_key=?", (user["clinic_id"], patient_id, dedupe_key)).fetchone()
        if existing:
            return {"id": existing["id"], **payload.model_dump(), "observed_at": observed, "available_at": available, "duplicate": True}
        cur = db.execute("INSERT INTO context(clinic_id,patient_id,kind,value_json,observed_at,available_at,provenance,created_by,dedupe_key) VALUES(?,?,?,?,?,?,?,?,?)", (user["clinic_id"], patient_id, payload.kind, value_json, observed, available, payload.provenance, user["id"], dedupe_key))
        audit(db, user, "context.added", str(cur.lastrowid), {"patient_id": patient_id, "kind": payload.kind})
    return {"id": cur.lastrowid, **payload.model_dump(), "observed_at": observed, "available_at": available}


@router.post("/api/clinic/context/{patient_id}")
@router.post("/api/clinic/patients/{patient_id}/context")
def add_context(patient_id: str, payload: ContextEntry, user: dict = Depends(current_user)):
    return result(add_context_entry(patient_id, payload, user))


class Observation(BaseModel):
    timestamp: str
    glucose_mg_dl: float = Field(ge=20, le=600)
    available_at: str | None = None
    source: str = "simulated"


def validate_synthetic_id(patient_id: str):
    if not patient_id.startswith("SIM-") or len(patient_id) > 64 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in patient_id):
        raise HTTPException(422, "Intake is restricted to anonymized synthetic IDs beginning SIM-; source records remain immutable.")


def create_synthetic(patient_id: str, user: dict, db=None):
    validate_synthetic_id(patient_id)
    with (nullcontext(db) if db is not None else connection()) as db:
        profile = {"id": patient_id, "name": f"Synthetic patient {patient_id}", "source": "synthetic", "recording_id": f"{patient_id}-stream",
                   "provenance": "Fully synthetic demonstration; excluded from measured-data evaluation."}
        db.execute("INSERT OR IGNORE INTO profiles VALUES(?,?,?)", (user["clinic_id"], patient_id, json.dumps(profile)))


def validate_observation(patient_id: str, payload: Observation, public_provenance: dict | None = None) -> tuple[str, str]:
    if public_provenance:
        if not patient_id.startswith("PUB-"):
            raise HTTPException(422, "Public research imports need pseudonymous PUB- patient IDs.")
        validate_synthetic_id("SIM-" + patient_id[4:])
    else:
        validate_synthetic_id(patient_id)
    observed, available = iso_time(payload.timestamp), iso_time(payload.available_at or utc_now())
    if time_key(available) < time_key(observed):
        raise HTTPException(422, "Arrival time cannot precede observation time.")
    expected_source = "anonymized_public" if public_provenance else "simulated"
    if payload.source != expected_source or not math.isfinite(payload.glucose_mg_dl):
        raise HTTPException(422, "Public demo intake accepts simulated readings only.")
    return observed, available


def ingest_observation(patient_id: str, payload: Observation, user: dict, db=None, public_provenance: dict | None = None) -> bool:
    observed, available = validate_observation(patient_id, payload, public_provenance)
    with (nullcontext(db) if db is not None else connection()) as db:
        if public_provenance:
            profile = {"id": patient_id, "name": f"Public research patient {patient_id}", "source": "anonymized_public", "recording_id": f"{patient_id}-import",
                       "provenance": "Administrator-attested public anonymized ShanghaiT2DM import; excluded from benchmark training.", **public_provenance}
            db.execute("INSERT OR IGNORE INTO profiles VALUES(?,?,?)", (user["clinic_id"], patient_id, json.dumps(profile)))
        else:
            create_synthetic(patient_id, user, db)
        duplicate = db.execute("SELECT glucose_mg_dl,available_at,source FROM observations WHERE clinic_id=? AND patient_id=? AND timestamp=?", (user["clinic_id"], patient_id, observed)).fetchone()
        if duplicate:
            if float(duplicate["glucose_mg_dl"]) != payload.glucose_mg_dl or duplicate["available_at"] != available or duplicate["source"] != payload.source:
                raise HTTPException(409, "Conflicting duplicate timestamp; original observation is preserved.")
            return False
        db.execute("INSERT INTO observations(clinic_id,patient_id,timestamp,available_at,glucose_mg_dl,source) VALUES(?,?,?,?,?,?)", (user["clinic_id"], patient_id, observed, available, payload.glucose_mg_dl, payload.source))
        audit(db, user, "observation.ingested", patient_id, {"timestamp": observed, "source": payload.source})
    return True


@router.post("/api/clinic/stream/{patient_id}")
@router.post("/api/clinic/patients/{patient_id}/observations")
def stream(patient_id: str, payload: Observation, user: dict = Depends(admin_user)):
    accepted = ingest_observation(patient_id, payload, user)
    records = imported_records(patient_id, user)
    snapshot = snapshot_for(patient_id, user, len(records) - 1, at=payload.available_at or utc_now())
    mature_outcomes(patient_id, user, snapshot["observations"], snapshot["current_time"])
    return result({"accepted": int(accepted), "duplicates": int(not accepted), "snapshot": snapshot})


class CSVInput(BaseModel):
    csv: str = Field(max_length=2_000_000)
    attested_anonymized_public: bool = False
    source_url: str | None = None
    source_license: str | None = None


@router.post("/api/clinic/intake/csv")
@router.post("/api/clinic/import/csv")
def import_csv(payload: CSVInput, user: dict = Depends(admin_user)):
    reader = csv.DictReader(io.StringIO(payload.csv))
    public_provenance = None
    if payload.attested_anonymized_public:
        if user["role"] != "admin":
            raise HTTPException(403, "An administrator must attest public research provenance.")
        if payload.source_url != PUBLIC_DATASET_URL or payload.source_license != "CC BY 4.0":
            raise HTTPException(422, "Public imports are allowlisted to ShanghaiT2DM Figshare with its CC BY 4.0 attribution.")
        public_provenance = {"source_url": payload.source_url, "source_license": payload.source_license,
                             "clock_policy": "Explicit import timezone; historical dataset timezone unverified. Virtual-clock replay only."}
    required = {"patient_id", "timestamp", "glucose_mg_dl", "available_at"}
    if not required.issubset(reader.fieldnames or []):
        raise HTTPException(422, "CSV requires patient_id,timestamp,glucose_mg_dl,available_at; optional source=simulated.")
    if set(reader.fieldnames or []) - required - {"source"}:
        raise HTTPException(422, "CSV accepts only pseudonymous patient ID, glucose, timestamps, and source; remove identifying columns.")
    prepared = []
    for index, row in enumerate(reader):
        if index >= 10000:
            raise HTTPException(422, "Import at most 10,000 rows per request.")
        try:
            observation = Observation(timestamp=row["timestamp"], glucose_mg_dl=float(row["glucose_mg_dl"]), available_at=row["available_at"], source=row.get("source") or "simulated")
            validate_observation(row["patient_id"], observation, public_provenance)
            prepared.append((row["patient_id"], observation))
        except Exception as exc:
            raise HTTPException(422, f"Invalid CSV row {index + 2}: {str(exc)[:180]}")
    if not prepared:
        raise HTTPException(422, "CSV contains no observations.")
    with connection() as db:
        accepted = sum(ingest_observation(patient_id, observation, user, db, public_provenance) for patient_id, observation in prepared)
    return result({"accepted": accepted, "duplicates": len(prepared) - accepted, "patients": sorted({p for p, _ in prepared}), "errors": []})


class FHIRInput(BaseModel):
    bundle: dict


@router.post("/api/clinic/intake/fhir")
@router.post("/api/clinic/import/fhir")
def import_fhir(payload: FHIRInput, user: dict = Depends(admin_user)):
    bundle = payload.bundle
    if bundle.get("resourceType") != "Bundle" or bundle.get("type") not in {"collection", "transaction"}:
        raise HTTPException(422, "Use a FHIR R4 collection or transaction Bundle.")
    entries = bundle.get("entry", [])
    if not isinstance(entries, list) or not entries or any(not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict) for entry in entries):
        raise HTTPException(422, "Bundle.entry must contain resource objects.")
    if len(entries) > 1000:
        raise HTTPException(422, "Import at most 1,000 FHIR resources.")
    for entry in entries:
        for field in ["meta", "subject", "code", "valueQuantity"]:
            if field in entry["resource"] and not isinstance(entry["resource"][field], dict):
                raise HTTPException(422, f"FHIR {field} must be an object.")
    with connection() as db:
        references = {}
        for entry in entries:
            resource = entry.get("resource", {})
            if resource.get("resourceType") == "Patient":
                patient_id = str(resource.get("id", ""))
                if resource.get("name") or resource.get("telecom") or resource.get("address") or resource.get("identifier"):
                    raise HTTPException(422, "Public demo accepts synthetic Patient IDs only; remove identifying fields.")
                create_synthetic(patient_id, user, db)
                references[f"Patient/{patient_id}"] = patient_id
                if entry.get("fullUrl"):
                    references[entry["fullUrl"]] = patient_id
                historical = {}
                if resource.get("gender") in {"male", "female"}:
                    historical["sex"] = resource["gender"].title()
                if resource.get("birthDate") or historical:
                    available = resource.get("meta", {}).get("lastUpdated")
                    if not available:
                        raise HTTPException(422, "Dated Patient demographics need meta.lastUpdated.")
                    available = iso_time(available)
                    if resource.get("birthDate"):
                        try:
                            born = datetime.strptime(resource["birthDate"], "%Y-%m-%d").date()
                            asof = time_key(available).date()
                            age = asof.year - born.year - ((asof.month, asof.day) < (born.month, born.day))
                            if not 18 <= age <= 120:
                                raise ValueError("Adult demo patient required")
                        except (ValueError, TypeError):
                            raise HTTPException(422, "Synthetic birthDate must be YYYY-MM-DD and describe an adult at availability.")
                        historical["age"] = age
                    add_context_entry(patient_id, ContextEntry(kind="historical", value=historical, observed_at=available,
                                      available_at=available, provenance="simulated"), user, db)
        accepted, duplicates, context_count = 0, 0, 0
        for entry in entries:
            resource = entry.get("resource", {})
            kind = resource.get("resourceType")
            if kind == "Patient":
                continue
            if kind not in {"Observation", "Condition", "CarePlan"}:
                raise HTTPException(422, "Supported resources: Patient, Condition, Observation, CarePlan.")
            patient_id = references.get(resource.get("subject", {}).get("reference"))
            if not patient_id:
                raise HTTPException(422, "Every subject reference must resolve to a synthetic Patient in this bundle.")
            available = resource.get("meta", {}).get("lastUpdated")
            if not available:
                raise HTTPException(422, "Every clinical resource needs meta.lastUpdated as its availability timestamp.")
            if kind == "Observation":
                coding = resource.get("code", {}).get("coding", [])
                if not isinstance(coding, list) or any(not isinstance(code, dict) for code in coding):
                    raise HTTPException(422, "Observation.code.coding must contain coding objects.")
                glucose = any(c.get("system") == "http://loinc.org" and c.get("code") in {"2339-0", "2345-7", "41653-7"} for c in coding)
                bmi = any(c.get("system") == "http://loinc.org" and c.get("code") == "39156-5" for c in coding)
                if bmi and not glucose:
                    quantity = resource.get("valueQuantity", {})
                    if quantity.get("system") != "http://unitsofmeasure.org" or quantity.get("code") != "kg/m2":
                        raise HTTPException(422, "BMI needs UCUM kg/m2.")
                    try:
                        value = float(quantity.get("value", float("nan")))
                    except (TypeError, ValueError):
                        raise HTTPException(422, "BMI must be numeric.")
                    if not math.isfinite(value) or not 10 <= value <= 80:
                        raise HTTPException(422, "BMI must be finite and between 10 and 80 kg/m2.")
                    added = add_context_entry(patient_id, ContextEntry(kind="historical", value={"bmi": value}, observed_at=resource.get("effectiveDateTime", ""), available_at=available, provenance="simulated"), user, db)
                    context_count += int(not added.get("duplicate"))
                    continue
                if not glucose:
                    raise HTTPException(422, "Observation supports glucose LOINC 2339-0/2345-7/41653-7 or BMI 39156-5.")
                quantity = resource.get("valueQuantity", {})
                if quantity.get("system") != "http://unitsofmeasure.org" or quantity.get("code") not in {"mg/dL", "mmol/L"}:
                    raise HTTPException(422, "Glucose needs a UCUM mg/dL or mmol/L quantity.")
                try:
                    value = float(quantity.get("value", float("nan")))
                    if quantity["code"] == "mmol/L":
                        value *= 18.0182
                    observation = Observation(timestamp=resource.get("effectiveDateTime", ""), glucose_mg_dl=value, available_at=available)
                except (ValueError, TypeError):
                    raise HTTPException(422, "Glucose value must be finite and between 20 and 600 mg/dL.")
                new = ingest_observation(patient_id, observation, user, db)
                accepted += int(new)
                duplicates += int(not new)
            else:
                observed = resource.get("recordedDate") if kind == "Condition" else resource.get("created")
                if not observed:
                    raise HTTPException(422, "Condition needs recordedDate; CarePlan needs created.")
                title = resource.get("code", {}).get("text", "Condition") if kind == "Condition" else resource.get("title", "Care plan")
                added = add_context_entry(patient_id, ContextEntry(kind="condition" if kind == "Condition" else "care_plan", value=str(title)[:2000], observed_at=observed, available_at=available, provenance="simulated"), user, db)
                context_count += int(not added.get("duplicate"))
    return result({"accepted": accepted, "duplicates": duplicates, "context_entries": context_count, "patients": sorted(set(references.values())), "errors": [],
                   "conformance": "Limited FHIR R4 prototype; no ABDM conformance certification."})


@router.get("/api/clinic/timeline/{patient_id}")
@router.get("/api/clinic/patients/{patient_id}/timeline")
def timeline(patient_id: str, at: str | None = None, user: dict = Depends(current_user), scenario: str = "recorded"):
    profile = get_profile(patient_id, user)
    cutoff = iso_time(at, required_zone=False) if at else utc_now()
    if scenario not in {"recorded", "sensor_gap"}:
        raise HTTPException(422, "Unknown replay scenario.")
    events = [{"type": "context", "timestamp": row["observed_at"], **{key: row[key] for key in ["id", "kind", "value", "observed_at", "available_at", "provenance"]}} for row in context_at(patient_id, user, cutoff)]
    is_imported = profile.get("source") in {"synthetic", "anonymized_public"}
    records = imported_records(patient_id, user, cutoff) if is_imported else []
    if not is_imported:
        from backend.main import data_store
        records = [row for row in data_store()["observations"].get(patient_id, []) if time_key(row["timestamp"]) <= time_key(cutoff)]
    if scenario == "sensor_gap":
        records = records[:-3]
    events.extend({"type": "observation", "timestamp": row["timestamp"], "value": row["glucose_mg_dl"], "provenance": row.get("source", "measured"), "available_at": row.get("available_at", row["timestamp"])} for row in records[-96:])
    with connection() as db:
        forecasts = [dict(row) for row in db.execute("SELECT * FROM forecasts WHERE clinic_id=? AND patient_id=? ORDER BY issued_at", (user["clinic_id"], patient_id))]
        actions = [dict(row) for row in db.execute("SELECT a.*,r.patient_id FROM actions a JOIN reviews r ON r.id=a.review_id WHERE a.clinic_id=? AND r.patient_id=? ORDER BY a.id", (user["clinic_id"], patient_id))]
        reviews = [dict(row) for row in db.execute("SELECT * FROM reviews WHERE clinic_id=? AND patient_id=?", (user["clinic_id"], patient_id))]
    known = {time_key(row["timestamp"]): row["glucose_mg_dl"] for row in records}
    for forecast in forecasts:
        if time_key(forecast["issued_at"]) > time_key(cutoff):
            continue
        snapshot = json.loads(forecast["snapshot_json"])
        curves = snapshot.get("clinic_model", {}).get("forecasts", {}).get(snapshot.get("clinic_model", {}).get("model", {}).get("primary", "population"), []) or snapshot.get("forecasts", {}).get("population", []) or snapshot.get("forecasts", {}).get("twin", [])
        outcomes = [{"target_time": point["timestamp"], "horizon_minutes": point["horizon_minutes"], "predicted": point["glucose_mg_dl"], "actual": known.get(time_key(point["timestamp"])) if time_key(point["timestamp"]) <= time_key(cutoff) else None} for point in curves]
        events.append({"type": "forecast", "timestamp": forecast["issued_at"], "id": forecast["id"], "model_version": forecast["model_version"], "quality": snapshot["quality"], "outcomes": outcomes, "provenance": "model"})
    # Reviewer actions use wall-clock audit time, displayed separately from the historical sensor clock.
    reviews = [row for row in reviews if time_key(row["issued_at"]) <= time_key(cutoff)]
    allowed_review_ids = {row["id"] for row in reviews}
    events.extend({"type": "review_action", "timestamp": row["recorded_at"], "provenance": "clinician", "clock_kind": "wall_clock", **row} for row in actions if row["review_id"] in allowed_review_ids)
    events.sort(key=lambda row: time_key(row["timestamp"]), reverse=True)
    from backend.twin import observation_quality
    quality = observation_quality([{**row, "timestamp": time_key(row["timestamp"]).isoformat()} for row in records], time_key(cutoff).isoformat())
    return result({"patient": profile, "at": cutoff, "events": events, "reviews": reviews, "monitoring": monitoring(user, at),
                   "quality": quality, "scenario": scenario, "doctor_review_status": "pending"})


@router.get("/api/clinic/report/{patient_id}")
@router.get("/api/clinic/patients/{patient_id}/summary.pdf")
def report(patient_id: str, at: str | None = None, user: dict = Depends(current_user), scenario: str = "recorded"):
    from backend.report import consultation_pdf
    evidence = timeline(patient_id, at, user, scenario)["data"]
    document = consultation_pdf(evidence, user)
    with connection() as db:
        audit(db, user, "report.exported", patient_id, {"at": evidence["at"]})
    return Response(document, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="GlucoTwin_{patient_id}_Summary.pdf"', "Cache-Control": "no-store"})


@router.get("/api/clinic/audit")
def audit_log(user: dict = Depends(admin_user)):
    with connection() as db:
        return result([dict(row) for row in db.execute("SELECT * FROM audit WHERE clinic_id=? ORDER BY id DESC LIMIT 200", (user["clinic_id"],))])
