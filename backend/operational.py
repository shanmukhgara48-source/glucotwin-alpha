"""Arrival-aware synthetic intake and durable, inspectable forecast receipts."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.auth import admin_user, current_user, connection_actor
from backend.clinic import Capture, ReviewAction, capture, create_synthetic, get_profile, iso_time, monitoring, queue, review_action, time_key, validate_synthetic_id
from backend.storage import audit, connection, utc_now

router = APIRouter(prefix="/api/v2")


def clinic_access(user: dict = Depends(current_user)) -> dict:
    if user.get("role") not in {"admin", "reviewer", "clinician", "coordinator"}:
        raise HTTPException(403, "A care-team account is required.")
    return user


def success(data):
    from backend.main import success as envelope
    return envelope(data)


def emit(db, clinic_id: str, event_type: str, patient_id: str | None = None, resource_id=None):
    db.execute("INSERT INTO operational_events(clinic_id,type,patient_id,resource_id,created_at) VALUES(?,?,?,?,?)",
               (clinic_id, event_type, patient_id, str(resource_id) if resource_id is not None else None, utc_now()))


def connection_for(connection_id: str, user: dict, db=None) -> dict:
    if db is None:
        with connection() as owned:
            return connection_for(connection_id, user, owned)
    row = db.execute("SELECT * FROM source_connections WHERE id=? AND clinic_id=?", (connection_id, user["clinic_id"])).fetchone()
    if row is None:
        raise HTTPException(404, "Connection is unavailable in this clinic.")
    return dict(row)


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source_type: Literal["synthetic", "clinic_pending"] = "synthetic"
    patient_id: str | None = None
    device_id: str | None = Field(default=None, max_length=100)
    cadence_minutes: int = Field(default=15, ge=1, le=60)
    source_timezone: str = "Asia/Kolkata"


@router.post("/connections")
def create_connection(payload: ConnectionInput, user: dict = Depends(admin_user)):
    try:
        ZoneInfo(payload.source_timezone)
    except Exception:
        raise HTTPException(422, "Unknown source timezone.")
    if payload.source_type == "synthetic":
        if not payload.patient_id:
            raise HTTPException(422, "A synthetic connection needs its bound SIM- patient ID.")
        validate_synthetic_id(payload.patient_id)
    elif payload.patient_id:
        raise HTTPException(422, "Clinic-source setup is pending; patient binding is disabled.")
    identifier, now = str(uuid.uuid4()), utc_now()
    status = "enabled" if payload.source_type == "synthetic" else "pending"
    key = secrets.token_urlsafe(40) if status == "enabled" else None
    with connection() as db:
        if payload.patient_id:
            create_synthetic(payload.patient_id, user, db)
        db.execute("INSERT INTO source_connections(id,clinic_id,name,source_type,status,patient_id,device_id,cadence_minutes,source_timezone,config_json,created_by,created_at,connection_key_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (identifier, user["clinic_id"], payload.name, payload.source_type, status, payload.patient_id,
                    payload.device_id, payload.cadence_minutes, payload.source_timezone, "{}", user["id"], now,
                    hashlib.sha256(key.encode()).hexdigest() if key else None))
        audit(db, user, "connection.created", identifier, {"source_type": payload.source_type})
        emit(db, user["clinic_id"], "connection.created", payload.patient_id, identifier)
    item = connection_for(identifier, user)
    item.pop("connection_key_hash", None)
    item["connection_key"] = key
    return success(item)


@router.get("/connections")
def connections(user: dict = Depends(clinic_access)):
    with connection() as db:
        rows = [{key: row[key] for key in row.keys() if key != "connection_key_hash"} for row in db.execute("SELECT * FROM source_connections WHERE clinic_id=? ORDER BY created_at DESC", (user["clinic_id"],))]
    return success({"items": rows, "clinical_connection": "pending", "server_time": utc_now()})


class ConnectionState(BaseModel):
    status: Literal["enabled", "paused", "revoked"]


class GeneratorInput(BaseModel):
    enabled: bool
    seed: bool = False


@router.post("/connections/{connection_id}/generator")
def configure_generator(connection_id: str, payload: GeneratorInput, user: dict = Depends(admin_user)):
    """Native wall-clock synthetic measurements; seed is explicitly retrospective history."""
    source = connection_for(connection_id, user)
    if source["source_type"] != "synthetic" or source["status"] != "enabled":
        raise HTTPException(409, "Only an enabled synthetic connection can run its generator.")
    now = utc_now()
    cadence = source["cadence_minutes"]
    seeded = 0
    if payload.seed:
        with connection() as db:
            has_data = db.execute("SELECT 1 FROM observations WHERE clinic_id=? AND patient_id=? AND connection_id=? LIMIT 1", (user["clinic_id"], source["patient_id"], connection_id)).fetchone()
        if has_data:
            raise HTTPException(409, "Seed is only available for a new connection; existing history is preserved.")
        anchor = time_key(now) - timedelta(minutes=1)
        for index in range(8):
            measured = anchor - timedelta(minutes=cadence * (7 - index))
            data, _ = ingest(connection_id, IncomingObservation(source_event_id=f"seed:{index}:{measured.isoformat()}", timestamp=measured.isoformat(), glucose_mg_dl=synthetic_value(connection_id, measured.isoformat())), user, now)
            seeded += int(data.get("accepted", False))
    with connection() as db:
        current = connection_for(connection_id, user, db)
        config = json.loads(current["config_json"])
        latest = db.execute("SELECT timestamp FROM observations WHERE clinic_id=? AND patient_id=? AND connection_id=? ORDER BY timestamp DESC LIMIT 1", (user["clinic_id"], source["patient_id"], connection_id)).fetchone()
        next_read = time_key(latest[0]) + timedelta(minutes=cadence) if latest else time_key(now) + timedelta(minutes=cadence)
        if next_read <= time_key(now):
            next_read = time_key(now) + timedelta(minutes=cadence)
        config.update(generator_enabled=payload.enabled, next_read_at=next_read.isoformat(), generator_lease_until=None,
                      generator_policy="real_wall_clock_native_cadence", seed_policy="explicit_synthetic_backfill_received_now" if seeded else config.get("seed_policy"))
        db.execute("UPDATE source_connections SET config_json=? WHERE id=?", (json.dumps(config), connection_id))
        audit(db, user, "generator.configured", connection_id, {"enabled": payload.enabled, "seeded": seeded})
        emit(db, user["clinic_id"], "connection.changed", source["patient_id"], connection_id)
    return success({"connection_id": connection_id, "enabled": payload.enabled, "seeded_readings": seeded,
                    "cadence_minutes": cadence, "next_read_at": next_read.isoformat(), "server_time": now,
                    "forecast_compatibility": "research_15_minute" if cadence == 15 else "unsupported_model_cadence"})


def synthetic_value(connection_id: str, timestamp: str) -> float:
    phase = int(hashlib.sha256(connection_id.encode()).hexdigest()[:8], 16) % 60
    minute = time_key(timestamp).timestamp() / 60
    return round(155 + 25 * math.sin((minute + phase) / 40) + 5 * math.sin(minute / 11), 1)


def tick_generators(now: str | None = None) -> int:
    now = now or utc_now()
    due = []
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT * FROM source_connections WHERE source_type='synthetic' AND status='enabled'").fetchall():
            source = dict(row)
            config = json.loads(source["config_json"])
            target = config.get("next_read_at")
            lease = config.get("generator_lease_until")
            if not config.get("generator_enabled") or not target or time_key(target) > time_key(now) or (lease and time_key(lease) > time_key(now)):
                continue
            # A stopped service leaves a visible gap; it never invents missed readings.
            if (time_key(now) - time_key(target)).total_seconds() > 2:
                config["next_read_at"] = (time_key(now) + timedelta(minutes=source["cadence_minutes"])).isoformat()
                config["last_gap_at"] = now
                db.execute("UPDATE source_connections SET config_json=? WHERE id=?", (json.dumps(config), source["id"]))
                emit(db, source["clinic_id"], "generator.gap", source["patient_id"], source["id"])
                continue
            config["generator_lease_until"] = (time_key(now) + timedelta(seconds=30)).isoformat()
            db.execute("UPDATE source_connections SET config_json=? WHERE id=?", (json.dumps(config), source["id"]))
            due.append((source, target))
    accepted = 0
    for source, target in due:
        user = {"id": "synthetic-generator", "clinic_id": source["clinic_id"], "role": "connector", "connection_id": source["id"]}
        try:
            data, status = ingest(source["id"], IncomingObservation(source_event_id=f"generator:{target}", timestamp=target, glucose_mg_dl=synthetic_value(source["id"], target)), user, now)
            accepted += int(data.get("accepted", False))
            if status < 400:
                with connection() as db:
                    current = connection_for(source["id"], user, db)
                    config = json.loads(current["config_json"])
                    config.update(next_read_at=(time_key(target) + timedelta(minutes=source["cadence_minutes"])).isoformat(), generator_lease_until=None, last_generated_at=now)
                    db.execute("UPDATE source_connections SET config_json=? WHERE id=?", (json.dumps(config), source["id"]))
        except HTTPException:
            continue
    return accepted


@router.patch("/connections/{connection_id}")
def change_connection(connection_id: str, payload: ConnectionState, user: dict = Depends(admin_user)):
    with connection() as db:
        source = connection_for(connection_id, user, db)
        if source["source_type"] != "synthetic":
            raise HTTPException(409, "Clinic-source verification is pending; this connection cannot be enabled.")
        if source["status"] == "revoked":
            raise HTTPException(409, "A revoked connection cannot be resumed. Create a new scoped connection.")
        db.execute("UPDATE source_connections SET status=?,connection_key_hash=CASE WHEN ?='revoked' THEN NULL ELSE connection_key_hash END WHERE id=? AND clinic_id=?", (payload.status, payload.status, connection_id, user["clinic_id"]))
        audit(db, user, "connection.state_changed", connection_id, {"status": payload.status})
        emit(db, user["clinic_id"], "connection.changed", source["patient_id"], connection_id)
    item = connection_for(connection_id, user)
    item.pop("connection_key_hash", None)
    return success(item)


@router.post("/connections/{connection_id}/rotate-key")
def rotate_connection_key(connection_id: str, user: dict = Depends(admin_user)):
    key = secrets.token_urlsafe(40)
    with connection() as db:
        source = connection_for(connection_id, user, db)
        if source["source_type"] != "synthetic" or source["status"] == "revoked":
            raise HTTPException(409, "Only an active or paused synthetic connection can rotate a key.")
        db.execute("UPDATE source_connections SET connection_key_hash=? WHERE id=? AND clinic_id=?", (hashlib.sha256(key.encode()).hexdigest(), connection_id, user["clinic_id"]))
        audit(db, user, "connection.key_rotated", connection_id)
    return success({"connection_id": connection_id, "connection_key": key, "shown_once": True})


class IncomingObservation(BaseModel):
    source_event_id: str = Field(min_length=1, max_length=128)
    timestamp: str
    glucose_mg_dl: float = Field(ge=20, le=600)
    available_at: str | None = None


def ingest(connection_id: str, payload: IncomingObservation, user: dict, received_at: str | None = None) -> tuple[dict, int]:
    """Commit the accepted measurement and forecast job together; receipt time is server-owned."""
    measured = iso_time(payload.timestamp)
    declared = iso_time(payload.available_at) if payload.available_at else None
    received = iso_time(received_at or utc_now())
    if not math.isfinite(payload.glucose_mg_dl):
        raise HTTPException(422, "Glucose must be finite.")
    canonical = {**payload.model_dump(), "timestamp": measured, "available_at": declared}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        source = connection_for(connection_id, user, db)
        if source["status"] != "enabled" or source["source_type"] != "synthetic":
            raise HTTPException(409, "Clinic connection pending. Identifiable or real device intake is disabled.")
        patient_id = source["patient_id"]
        existing = db.execute("SELECT * FROM ingest_events WHERE connection_id=? AND source_event_id=?", (connection_id, payload.source_event_id)).fetchone()
        reason = None
        if existing:
            if existing["payload_digest"] == digest:
                job = db.execute("SELECT id,status,forecast_id FROM forecast_jobs WHERE event_id=?", (existing["id"],)).fetchone()
                return {"accepted": False, "duplicate": True, "event_id": existing["id"], "received_at": existing["received_at"], "job": dict(job) if job else None}, 200
            reason = "conflicting_source_event"
        if time_key(measured) > time_key(received):
            reason = "future_measurement"
        old = db.execute("SELECT * FROM observations WHERE clinic_id=? AND patient_id=? AND timestamp=?", (user["clinic_id"], patient_id, measured)).fetchone()
        if old and float(old["glucose_mg_dl"]) != payload.glucose_mg_dl:
            reason = "conflicting_measurement"
        if reason:
            row = db.execute("INSERT INTO ingest_quarantine(clinic_id,connection_id,patient_id,source_event_id,reason,payload_digest,received_at) VALUES(?,?,?,?,?,?,?)",
                             (user["clinic_id"], connection_id, patient_id, payload.source_event_id, reason, digest, received))
            audit(db, user, "ingestion.quarantined", str(row.lastrowid), {"reason": reason, "connection_id": connection_id})
            emit(db, user["clinic_id"], "ingestion.quarantined", patient_id, row.lastrowid)
            return {"accepted": False, "quarantine_id": row.lastrowid, "reason": reason}, 409
        identifier = str(uuid.uuid4())
        db.execute("INSERT INTO ingest_events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (identifier, user["clinic_id"], connection_id, patient_id, payload.source_event_id, digest,
                    json.dumps(canonical), measured, declared, received, "duplicate_sample" if old else "accepted"))
        if old:
            return {"accepted": False, "duplicate": True, "event_id": identifier, "received_at": received, "job": None}, 200
        db.execute("INSERT INTO observations(clinic_id,patient_id,timestamp,available_at,glucose_mg_dl,source,received_at,connection_id,source_event_id) VALUES(?,?,?,?,?,?,?,?,?)",
                   (user["clinic_id"], patient_id, measured, received, payload.glucose_mg_dl, "simulated", received, connection_id, payload.source_event_id))
        job = db.execute("INSERT INTO forecast_jobs(clinic_id,patient_id,connection_id,event_id,issue_cutoff,available_after,created_at) VALUES(?,?,?,?,?,?,?)",
                         (user["clinic_id"], patient_id, connection_id, identifier, received, received, received))
        audit(db, user, "observation.received", identifier, {"connection_id": connection_id, "patient_id": patient_id})
        emit(db, user["clinic_id"], "observation.received", patient_id, identifier)
        return {"accepted": True, "duplicate": False, "event_id": identifier, "patient_id": patient_id,
                "received_at": received, "job": {"id": job.lastrowid, "status": "pending", "forecast_id": None}}, 202


@router.post("/connections/{connection_id}/observations")
def receive(connection_id: str, payload: IncomingObservation, user: dict = Depends(connection_actor)):
    data, status = ingest(connection_id, payload, user)
    return JSONResponse(status_code=status, content=success(data) if status < 400 else {"error": "Observation quarantined; original evidence preserved.", "data": data})


def receipt_record(identifier: int, user: dict, db=None) -> dict:
    if db is None:
        with connection() as owned:
            return receipt_record(identifier, user, owned)
    row = db.execute("SELECT * FROM forecasts WHERE id=? AND clinic_id=?", (identifier, user["clinic_id"])).fetchone()
    if row is None:
        raise HTTPException(404, "Forecast is unavailable in this clinic.")
    item = dict(row)
    item["forecast_id"] = item["id"]
    item["snapshot"] = json.loads(item.pop("snapshot_json"))
    item["patient"] = item["snapshot"].get("patient", {})
    if "observations" not in item["snapshot"] and item["clock_kind"] == "recorded":
        from backend.main import data_store
        rows = [row for row in data_store()["observations"].get(item["patient_id"], []) if time_key(row["timestamp"]) <= time_key(item["issued_at"])]
        if item["scenario"] == "sensor_gap":
            rows = rows[:-3]
        item["snapshot"]["observations"] = rows[-96:]
    item["outcomes"] = [dict(value) for value in db.execute("SELECT * FROM forecast_outcomes WHERE forecast_id=? AND clinic_id=? ORDER BY horizon_minutes", (identifier, user["clinic_id"]))]
    item["event_outcomes"] = [dict(value) for value in db.execute("SELECT * FROM event_outcomes WHERE forecast_id=? AND clinic_id=? ORDER BY horizon_minutes", (identifier, user["clinic_id"]))]
    review = db.execute("SELECT id FROM reviews WHERE clinic_id=? AND (forecast_id=? OR latest_forecast_id=?) ORDER BY id DESC LIMIT 1", (user["clinic_id"], identifier, identifier)).fetchone()
    item["review_id"] = review["id"] if review else None
    return item


@router.get("/receipts/{forecast_id}")
def receipt(forecast_id: int, user: dict = Depends(clinic_access)):
    return success(receipt_record(forecast_id, user))


@router.get("/patients/{patient_id}/receipts")
def receipts(patient_id: str, limit: int = 50, user: dict = Depends(clinic_access)):
    get_profile(patient_id, user)
    limit = max(1, min(200, limit))
    with connection() as db:
        rows = db.execute("SELECT id FROM forecasts WHERE clinic_id=? AND patient_id=? ORDER BY issued_at DESC,id DESC LIMIT ?", (user["clinic_id"], patient_id, limit)).fetchall()
        total = db.execute("SELECT COUNT(*) FROM forecasts WHERE clinic_id=? AND patient_id=?", (user["clinic_id"], patient_id)).fetchone()[0]
        items = [receipt_record(row["id"], user, db) for row in rows]
    return success({"items": items, "total": total})


@router.post("/replay/capture/{patient_id}")
def capture_receipt(patient_id: str, payload: Capture, user: dict = Depends(clinic_access)):
    data = capture(patient_id, payload, user)["data"]
    return success(receipt_record(data["forecast_id"], user))


@router.patch("/reviews/{review_id}")
def update_review(review_id: int, payload: ReviewAction, user: dict = Depends(clinic_access)):
    if payload.expected_revision is None:
        raise HTTPException(422, "expected_revision is required for an operational review action.")
    return review_action(review_id, payload, user)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, user: dict = Depends(admin_user)):
    with connection() as db:
        job = db.execute("SELECT * FROM forecast_jobs WHERE id=? AND clinic_id=?", (job_id, user["clinic_id"])).fetchone()
        if job is None:
            raise HTTPException(404, "Job is unavailable in this clinic.")
        if job["status"] != "failed":
            raise HTTPException(409, "Only failed jobs can be retried manually.")
        source = connection_for(job["connection_id"], user, db)
        if source["status"] != "enabled":
            raise HTTPException(409, "Resume the source before retrying.")
        db.execute("UPDATE forecast_jobs SET status='pending',attempts=0,available_after=?,last_error=NULL WHERE id=?", (utc_now(), job_id))
        audit(db, user, "job.retry_requested", str(job_id))
    return success({"job_id": job_id, "status": "pending"})


@router.get("/queue")
def current_queue(at: str | None = None, user: dict = Depends(clinic_access)):
    data = queue(at, user)["data"]
    now = iso_time(at, required_zone=False) if at else utc_now()
    with connection() as db:
        for item in data["items"]:
            latest = db.execute("SELECT timestamp,available_at,received_at FROM observations WHERE clinic_id=? AND patient_id=? AND timestamp<=? AND available_at<=? ORDER BY timestamp DESC LIMIT 1", (user["clinic_id"], item["patient_id"], now, now)).fetchone()
            if latest:
                age = max(0, (time_key(now) - time_key(latest["timestamp"])).total_seconds() / 60)
                item["current_quality"] = {"status": "fresh" if age <= 20 else "stale", "last_reading_at": latest["timestamp"], "last_received_at": latest["received_at"] or latest["available_at"], "minutes_since_reading": age}
                item["source_status"] = "synthetic_stream"
            else:
                item["current_quality"] = {"status": "recorded", "last_reading_at": item["reading_freshness"].get("last_reading_at"), "last_received_at": None, "minutes_since_reading": None}
                item["source_status"] = "recorded_research"
    data.update(server_time=utc_now(), mode="research", clinical_connection="pending")
    return success(data)


@router.get("/operations")
def operations(user: dict = Depends(clinic_access)):
    with connection() as db:
        def count(table, where="1=1"):
            return db.execute(f"SELECT COUNT(*) FROM {table} WHERE clinic_id=? AND {where}", (user["clinic_id"],)).fetchone()[0]
        counts = {"pending_jobs": count("forecast_jobs", "status IN ('pending','retry','processing')"),
                  "failed_jobs": count("forecast_jobs", "status='failed'"), "quarantined_events": count("ingest_quarantine"),
                  "open_reviews": count("reviews", "status!='closed'"), "issued_forecasts": count("forecasts")}
        counts["overdue_reviews"] = db.execute("SELECT COUNT(*) FROM reviews WHERE clinic_id=? AND status!='closed' AND next_review_at<?", (user["clinic_id"], utc_now())).fetchone()[0]
        worker = db.execute("SELECT * FROM worker_status ORDER BY last_heartbeat_at DESC LIMIT 1").fetchone()
        sources = [{key: row[key] for key in row.keys() if key != "connection_key_hash"} for row in db.execute("SELECT * FROM source_connections WHERE clinic_id=?", (user["clinic_id"],))]
    state = dict(worker) if worker else {"status": "not_started", "last_heartbeat_at": None}
    if worker and (time_key(utc_now()) - time_key(worker["last_heartbeat_at"])).total_seconds() > 15:
        state["status"] = "stale"
    return success({"server_time": utc_now(), "counts": counts, "connections": sources, "worker": state,
                    "clinical_connection": "pending", "mode": "research"})


@router.get("/readiness")
def readiness(user: dict = Depends(clinic_access)):
    try:
        with connection() as db:
            integrity = db.execute("PRAGMA quick_check").fetchone()[0]
            schema = db.execute("PRAGMA user_version").fetchone()[0]
        data = operations(user)["data"]
    except Exception:
        # Health probes expose availability, never database details or bound payloads.
        return JSONResponse(status_code=503, content=success({"ready": False, "database": "unavailable",
                            "schema_version": None, "worker": {"status": "unavailable", "last_heartbeat_at": None},
                            "model_ready": False, "model_artifact_sha256": None, "model_versions": [],
                            "doctor_review_status": "pending", "clinic_connection_status": "pending", "clinical_ready": False}))
    from backend.arrival_model import ROOT, artifact_checksum, load_clinic_bundle
    import os
    artifact = ROOT / "data" / "processed" / "clinic_model.joblib"
    model = {}
    loaded_checksum = None
    try:
        checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
        model = load_clinic_bundle()
        loaded_checksum = artifact_checksum()
    except Exception:
        checksum = None
    expected = os.getenv("GLUCOTWIN_EXPECTED_MODEL_SHA256")
    versions = [model.get("metadata", {}).get("version"), *[fold.get("metadata", {}).get("version") for fold in model.get("fold_bundles", {}).values()]]
    model_ready = bool(model.get("models") and checksum and checksum == loaded_checksum and all(versions) and (expected is None or expected == checksum))
    ready = integrity == "ok" and schema >= 7 and model_ready and data["worker"]["status"] == "running"
    return JSONResponse(status_code=200 if ready else 503, content=success({"ready": ready, "database": integrity,
                        "schema_version": schema, "worker": data["worker"], "model_ready": model_ready,
                        "model_artifact_sha256": checksum, "model_versions": versions,
                        "doctor_review_status": "pending", "clinic_connection_status": "pending", "clinical_ready": False}))


@router.get("/events")
async def events(request: Request, after: int = 0, user: dict = Depends(clinic_access)):
    """Scoped, metadata-only events; browsers use authenticated fetch streaming."""
    async def stream():
        cursor = max(0, after)
        deadline = datetime.now(timezone.utc) + timedelta(minutes=10)
        while datetime.now(timezone.utc) < deadline and not await request.is_disconnected():
            try:
                current_user(request)
            except HTTPException:
                return
            with connection() as db:
                rows = [dict(row) for row in db.execute("SELECT id,type,patient_id,resource_id,created_at FROM operational_events WHERE clinic_id=? AND id>? ORDER BY id LIMIT 100", (user["clinic_id"], cursor))]
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\nevent: update\ndata: {json.dumps(row)}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
