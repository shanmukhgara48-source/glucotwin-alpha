"""Small durable SQLite worker: leases, bounded retries and immutable receipts."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import timedelta

from backend.clinic import mature_outcomes, time_key
from backend.operational import emit, tick_generators
from backend.storage import audit, connection, utc_now

MAX_ATTEMPTS = 5
LEASE_SECONDS = 60


def _actor(clinic_id: str) -> dict:
    return {"id": "forecast-worker", "clinic_id": clinic_id, "role": "worker"}


def heartbeat(worker_id: str, status: str = "running"):
    with connection() as db:
        db.execute("INSERT INTO worker_status VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET last_heartbeat_at=excluded.last_heartbeat_at,status=excluded.status", (worker_id, utc_now(), status))


def claim(worker_id: str, now: str | None = None) -> dict | None:
    now = now or utc_now()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        # A crashed worker consumes an attempt just as a caught execution failure does.
        abandoned = db.execute("SELECT * FROM forecast_jobs WHERE status='processing' AND lease_until<? AND attempts>=?", (now, MAX_ATTEMPTS)).fetchall()
        for job in abandoned:
            db.execute("UPDATE forecast_jobs SET status='failed',last_error='LeaseAttemptsExhausted',lease_owner=NULL,lease_until=NULL WHERE id=?", (job["id"],))
            emit(db, job["clinic_id"], "job.failed", job["patient_id"], job["id"])
        row = db.execute("SELECT j.* FROM forecast_jobs j JOIN source_connections c ON c.id=j.connection_id WHERE c.status='enabled' AND j.attempts<? AND ((j.status IN ('pending','retry') AND j.available_after<=?) OR (j.status='processing' AND j.lease_until<?)) ORDER BY j.id LIMIT 1", (MAX_ATTEMPTS, now, now)).fetchone()
        if row is None:
            return None
        lease = (time_key(now) + timedelta(seconds=LEASE_SECONDS)).isoformat()
        db.execute("UPDATE forecast_jobs SET status='processing',attempts=attempts+1,lease_owner=?,lease_until=? WHERE id=?", (worker_id, lease, row["id"]))
        return dict(db.execute("SELECT * FROM forecast_jobs WHERE id=?", (row["id"],)).fetchone())


def mature_event_outcomes(db, user: dict, patient_id: str, records: list[dict], cutoff: str):
    """Complete event labels independently of a previously appended endpoint outcome."""
    known = {time_key(row["timestamp"]): row for row in records
             if time_key(row["timestamp"]) <= time_key(cutoff) and time_key(row.get("available_at", row["timestamp"])) <= time_key(cutoff)}
    for forecast in db.execute("SELECT * FROM forecasts WHERE clinic_id=? AND patient_id=?", (user["clinic_id"], patient_id)).fetchall():
        snapshot = json.loads(forecast["snapshot_json"])
        model = snapshot.get("clinic_model") or {}
        temporal = model.get("temporal") or {}
        anchor = temporal.get("measurement_anchor_at") or temporal.get("measurement_at")
        curves = model.get("forecasts", {}).get("population", []) or snapshot.get("forecasts", {}).get("population", [])
        for point in curves:
            target = time_key(point["timestamp"])
            horizon = int(point["horizon_minutes"])
            origin = time_key(anchor) if anchor else target - timedelta(minutes=horizon)
            expected = [origin + timedelta(minutes=step) for step in range(15, horizon + 1, 15)]
            if not all(stamp in known for stamp in expected):
                continue
            available = max(time_key(known[stamp].get("available_at", known[stamp]["timestamp"])) for stamp in expected).isoformat()
            event = int(any(known[stamp]["glucose_mg_dl"] > 180 for stamp in expected))
            inserted = db.execute("INSERT OR IGNORE INTO event_outcomes(clinic_id,forecast_id,horizon_minutes,target_time,event_occurred,available_at,provenance,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                                  (user["clinic_id"], forecast["id"], horizon, point["timestamp"], event, available, "complete_native_window", utc_now()))
            if inserted.rowcount:
                audit(db, user, "forecast.event_outcome_observed", str(forecast["id"]), {"horizon_minutes": horizon})
                emit(db, user["clinic_id"], "forecast.outcome", patient_id, forecast["id"])


def _ledger(db, clinic_id: str, patient_id: str) -> tuple[list[dict], list[dict]]:
    issued, outcomes = [], []
    for row in db.execute("SELECT id,issued_at,snapshot_json,model_version FROM forecasts WHERE clinic_id=? AND patient_id=? AND clock_kind='server_received'", (clinic_id, patient_id)):
        model = json.loads(row["snapshot_json"]).get("clinic_model") or {}
        for point in model.get("forecasts", {}).get("population", []):
            issued.append({"forecast_id": row["id"], "patient_id": patient_id, "issued_at": row["issued_at"], "target_at": point["timestamp"],
                           "horizon_minutes": point["horizon_minutes"], "population_mg_dl": point["glucose_mg_dl"], "model_version": row["model_version"]})
    for row in db.execute("SELECT o.* FROM forecast_outcomes o JOIN forecasts f ON f.id=o.forecast_id WHERE o.clinic_id=? AND f.patient_id=? AND f.clock_kind='server_received'", (clinic_id, patient_id)):
        outcomes.append({"forecast_id": row["forecast_id"], "patient_id": patient_id, "target_at": row["target_time"], "horizon_minutes": row["horizon_minutes"],
                         "glucose_mg_dl": row["actual_glucose_mg_dl"], "available_at": row["available_at"]})
    return issued, outcomes


def execute(job: dict, worker_id: str, issued_at: str | None = None, forecaster=None) -> int:
    if forecaster is None:
        from backend.arrival_model import arrival_forecast
        forecaster = arrival_forecast
    issued_at = issued_at or utc_now()
    user = _actor(job["clinic_id"])
    # The transaction prevents a stale lease owner from committing a second receipt.
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT * FROM forecast_jobs WHERE id=?", (job["id"],)).fetchone()
        if not current or current["status"] != "processing" or current["lease_owner"] != worker_id or time_key(current["lease_until"]) < time_key(issued_at):
            raise RuntimeError("Forecast job lease is unavailable")
        source = db.execute("SELECT * FROM source_connections WHERE id=? AND clinic_id=?", (job["connection_id"], job["clinic_id"])).fetchone()
        if source is None or source["status"] != "enabled" or source["source_type"] != "synthetic":
            raise RuntimeError("Connection is disabled or pending")
        profile_row = db.execute("SELECT profile_json FROM profiles WHERE clinic_id=? AND patient_id=?", (job["clinic_id"], job["patient_id"])).fetchone()
        profile = json.loads(profile_row[0])
        rows = [dict(row) for row in db.execute("SELECT timestamp,available_at,glucose_mg_dl,received_at AS server_received_at,source FROM observations WHERE clinic_id=? AND patient_id=? AND connection_id=? ORDER BY timestamp", (job["clinic_id"], job["patient_id"], job["connection_id"]))
                if time_key(row["timestamp"]) <= time_key(issued_at) and time_key(row["available_at"]) <= time_key(issued_at)]
        contexts = [dict(row) for row in db.execute("SELECT * FROM context WHERE clinic_id=? AND patient_id=?", (job["clinic_id"], job["patient_id"]))
                    if time_key(row["observed_at"]) <= time_key(issued_at) and time_key(row["available_at"]) <= time_key(issued_at)
                    and time_key(row["received_at"] or row["available_at"]) <= time_key(issued_at)]
        profile["context_entries"] = [{**row, "value": json.loads(row["value_json"]),
                                      "available_at": max(time_key(row["available_at"]), time_key(row["received_at"] or row["available_at"])).isoformat()} for row in contexts]
        mature_outcomes(job["patient_id"], user, rows, issued_at, db)
        mature_event_outcomes(db, user, job["patient_id"], rows, issued_at)
        issued, outcomes = _ledger(db, job["clinic_id"], job["patient_id"])
        model = forecaster(rows, profile, issued_at, issued_forecasts=issued, outcomes=outcomes,
                           source_timezone=source["source_timezone"], source_kind="synthetic")
        if source["cadence_minutes"] != 15:
            model["quality"] = {"status": "unsupported_cadence", "message": "Arrival research model requires verified 15-minute observations."}
            model["forecasts"] = {"population": [], "hybrid": []}
            model["event_risks"] = []
            model["research_review_eligible"] = False
            model["clinical_queue_eligible"] = False
            model.setdefault("temporal", {})["research_review_eligible"] = False
        version = model.get("model", {}).get("version", "arrival-model-unavailable")
        digest = hashlib.sha256(json.dumps({"observations": rows, "context": profile["context_entries"], "outcomes": outcomes}, sort_keys=True).encode()).hexdigest()
        old = db.execute("SELECT id FROM forecasts WHERE clinic_id=? AND patient_id=? AND source_connection_id=? AND input_digest=? AND model_version=?", (job["clinic_id"], job["patient_id"], job["connection_id"], digest, version)).fetchone()
        if old:
            identifier = old["id"]
        else:
            snapshot = {"patient": profile, "current_time": issued_at, "observations": rows[-96:], "input_observation_count": len(rows), "quality": model.get("quality", {}),
                        "clinic_model": model, "scenario": "synthetic_arrival", "clock_kind": "server_received", "clinical_status": "Synthetic research; clinic connection pending."}
            inserted = db.execute("INSERT INTO forecasts(clinic_id,patient_id,issued_at,input_cutoff,model_version,scenario,snapshot_json,recorded_at,source_connection_id,input_digest,clock_kind) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                  (job["clinic_id"], job["patient_id"], issued_at, issued_at, version, "synthetic_arrival", json.dumps(snapshot), utc_now(), job["connection_id"], digest, "server_received"))
            identifier = inserted.lastrowid
            quality = model.get("quality", {}).get("status")
            risks = model.get("event_risks", [])
            primary = next((risk for risk in risks if int(risk.get("horizon_minutes", 0)) == 30), {})
            eligible = bool(primary.get("research_review_eligible") or model.get("temporal", {}).get("research_review_eligible"))
            if quality not in {"ok", "fresh"}:
                kind, message = "missing_data", model.get("quality", {}).get("message", "Insufficient arrival-aware sensor history.")
            elif eligible and primary.get("exceeds_threshold"):
                kind, message = "predicted_excursion", "Synthetic research excursion forecast; inspect the immutable receipt."
            else:
                kind, message = "forecast_review", "Arrival-aware research receipt available; no clinical warning service."
            review = db.execute("SELECT id FROM reviews WHERE clinic_id=? AND patient_id=? AND type=? AND status!='closed' ORDER BY id DESC LIMIT 1", (job["clinic_id"], job["patient_id"], kind)).fetchone()
            if review:
                db.execute("UPDATE reviews SET latest_forecast_id=?,last_seen_at=?,occurrence_count=occurrence_count+1,revision=revision+1 WHERE id=?", (identifier, issued_at, review["id"]))
            else:
                config = db.execute("SELECT config_json FROM monitoring WHERE clinic_id=?", (job["clinic_id"],)).fetchone()
                reviewer = json.loads(config[0]).get("reviewer_id", "reviewer") if config else "reviewer"
                db.execute("INSERT INTO reviews(clinic_id,patient_id,forecast_id,type,status,issued_at,assigned_reviewer,message,probability,latest_forecast_id,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (job["clinic_id"], job["patient_id"], identifier, kind, "new", issued_at, reviewer, message, primary.get("probability"), identifier, issued_at))
            audit(db, user, "forecast.issued", str(identifier), {"connection_id": job["connection_id"], "job_id": job["id"]})
            emit(db, job["clinic_id"], "forecast.issued", job["patient_id"], identifier)
        db.execute("UPDATE forecast_jobs SET status='completed',forecast_id=?,completed_at=?,lease_owner=NULL,lease_until=NULL,last_error=NULL WHERE id=?", (identifier, utc_now(), job["id"]))
        return identifier


def process_next(worker_id: str, now: str | None = None, forecaster=None) -> bool:
    heartbeat(worker_id)
    job = claim(worker_id, now)
    if job is None:
        return False
    try:
        execute(job, worker_id, now, forecaster)
    except Exception as exc:
        with connection() as db:
            current = db.execute("SELECT attempts,lease_owner FROM forecast_jobs WHERE id=?", (job["id"],)).fetchone()
            if current and current["lease_owner"] == worker_id:
                failed = current["attempts"] >= MAX_ATTEMPTS
                due = (time_key(now or utc_now()) + timedelta(seconds=min(60, 2 ** current["attempts"]))).isoformat()
                db.execute("UPDATE forecast_jobs SET status=?,available_after=?,last_error=?,lease_owner=NULL,lease_until=NULL WHERE id=?", ("failed" if failed else "retry", due, type(exc).__name__, job["id"]))
                emit(db, job["clinic_id"], "job.failed" if failed else "job.retry", job["patient_id"], job["id"])
    return True


class ForecastWorker:
    def __init__(self):
        self.identifier = str(uuid.uuid4())
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if os.getenv("GLUCOTWIN_DISABLE_WORKER") == "1":
            return
        self.thread = threading.Thread(target=self.run, name="glucotwin-forecast-worker", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try:
                tick_generators()
                process_next(self.identifier)
            except Exception:
                # Infrastructure errors are visible through heartbeat age; never log health payloads.
                pass
            self.stop_event.wait(.5)
        heartbeat(self.identifier, "stopped")

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)


if __name__ == "__main__":
    service = ForecastWorker()
    try:
        service.run()
    except KeyboardInterrupt:
        service.stop_event.set()
