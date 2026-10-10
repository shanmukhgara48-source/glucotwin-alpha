"""Durable pipeline checks use synthetic inputs and isolated SQLite files."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend.auth import bootstrap
from backend.clinic import ReviewAction, queue
from backend.operational import ConnectionInput, ConnectionState, GeneratorInput, IncomingObservation, change_connection, configure_generator, create_connection, ingest, readiness, receipt_record, tick_generators, update_review
from backend.storage import connection, initialize
from backend.worker import claim, execute, process_next


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("GLUCOTWIN_DB_PATH", str(tmp_path / "clinic.sqlite3"))
    monkeypatch.setenv("GLUCOTWIN_CREDENTIALS_PATH", str(tmp_path / "credentials.json"))
    monkeypatch.setenv("GLUCOTWIN_KEY_PATH", str(tmp_path / "encryption.key"))
    monkeypatch.setenv("GLUCOTWIN_DISABLE_WORKER", "1")
    monkeypatch.setenv("GLUCOTWIN_ADMIN_PASSWORD", "test-only-admin-password")
    bootstrap()
    now = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
    admin = {"id": "admin", "clinic_id": "demo-clinic", "role": "admin"}
    source = create_connection(ConnectionInput(name="Synthetic pipeline", patient_id="SIM-PIPE"), admin)["data"]
    return admin, source, now


def fake_forecaster(rows, profile, issued_at, **kwargs):
    latest = rows[-1]
    anchor = datetime.fromisoformat(latest["timestamp"])
    curves = [{"horizon_minutes": horizon, "timestamp": (anchor + timedelta(minutes=horizon)).isoformat(),
               "glucose_mg_dl": latest["glucose_mg_dl"] + 10, "lower": 120, "upper": 220} for horizon in [30, 60]]
    return {"model": {"version": "synthetic-test:arrival-research-v1", "primary": "hybrid"},
            "quality": {"status": "ok", "last_reading_at": latest["timestamp"], "minutes_since_reading": 0},
            "forecasts": {"population": curves, "hybrid": curves},
            "event_risks": [{"horizon_minutes": 30, "probability": .8, "exceeds_threshold": True, "research_review_eligible": True}],
            "adaptation": {"matured_samples": len(kwargs.get("outcomes", []))},
            "temporal": {"issued_at": issued_at, "data_cutoff_at": latest["timestamp"]}, "clinical_queue_eligible": False}


def seed(pipeline):
    admin, source, now = pipeline
    for index in range(5):
        measured = now - timedelta(minutes=15 * (4 - index))
        ingest(source["id"], IncomingObservation(source_event_id=f"e{index}", timestamp=measured.isoformat(), glucose_mg_dl=160 + index), admin, now.isoformat())


def test_ingestion_jobs_commit_together_and_processing_is_idempotent(pipeline):
    admin, source, now = pipeline
    seed(pipeline)
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 5
        assert db.execute("SELECT COUNT(*) FROM forecast_jobs").fetchone()[0] == 5
        assert all(row[0] == now.isoformat() for row in db.execute("SELECT available_at FROM observations"))
    for _ in range(5):
        assert process_next("w1", now.isoformat(), fake_forecaster)
    assert not process_next("w1", now.isoformat(), fake_forecaster)
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM forecast_jobs WHERE status='completed'").fetchone()[0] == 5
        forecast = db.execute("SELECT id FROM forecasts").fetchone()[0]
    receipt = receipt_record(forecast, admin)
    assert receipt["issued_at"] == now.isoformat()
    assert receipt["clock_kind"] == "server_received"
    assert len(receipt["snapshot"]["observations"]) == 5
    original = receipt["snapshot"]
    with connection() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM forecasts WHERE id=?", (forecast,))
    assert receipt_record(forecast, admin)["snapshot"] == original


def test_duplicate_conflict_is_quarantined_and_does_not_replace_evidence(pipeline):
    admin, source, now = pipeline
    payload = IncomingObservation(source_event_id="provider-1", timestamp=now.isoformat(), glucose_mg_dl=140)
    first, status = ingest(source["id"], payload, admin, now.isoformat())
    assert status == 202 and first["accepted"]
    duplicate, status = ingest(source["id"], payload, admin, (now + timedelta(seconds=2)).isoformat())
    assert status == 200 and duplicate["duplicate"]
    conflict, status = ingest(source["id"], payload.model_copy(update={"glucose_mg_dl": 300}), admin, now.isoformat())
    assert status == 409 and conflict["quarantine_id"]
    with connection() as db:
        assert db.execute("SELECT glucose_mg_dl FROM observations").fetchone()[0] == 140
        assert db.execute("SELECT COUNT(*) FROM forecast_jobs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ingest_quarantine").fetchone()[0] == 1


def test_claim_lease_recovery_and_bounded_retry(pipeline):
    _, _, now = pipeline
    seed(pipeline)
    old = claim("old-worker", now.isoformat())
    later = now + timedelta(seconds=61)
    recovered = claim("new-worker", later.isoformat())
    assert recovered["id"] == old["id"]
    with pytest.raises(RuntimeError, match="lease"):
        execute(old, "old-worker", later.isoformat(), fake_forecaster)
    execute(recovered, "new-worker", later.isoformat(), fake_forecaster)
    def broken(*args, **kwargs):
        raise ValueError("Secret health payload must never be logged")
    for attempt in range(5):
        process_next("failure-worker", (later + timedelta(seconds=100 * (attempt + 1))).isoformat(), broken)
    with connection() as db:
        failed = db.execute("SELECT * FROM forecast_jobs WHERE status='failed'").fetchone()
        assert failed is not None and failed["attempts"] == 5
        assert failed["last_error"] == "ValueError"


def test_five_abandoned_leases_fail_without_extra_claim_or_forecast(pipeline, monkeypatch):
    from backend import operational
    admin, source, now = pipeline
    ingest(source["id"], IncomingObservation(source_event_id="abandoned", timestamp=now.isoformat(), glucose_mg_dl=140), admin, now.isoformat())
    identifier = None
    for attempt in range(5):
        claimed = claim(f"crashed-{attempt}", (now + timedelta(seconds=61 * attempt)).isoformat())
        identifier = identifier or claimed["id"]
        assert claimed["id"] == identifier and claimed["attempts"] == attempt + 1
    exhausted_at = (now + timedelta(seconds=61 * 5)).isoformat()
    assert claim("sixth-worker", exhausted_at) is None
    assert claim("later-worker", (now + timedelta(minutes=10)).isoformat()) is None
    with connection() as db:
        failed = db.execute("SELECT * FROM forecast_jobs WHERE id=?", (identifier,)).fetchone()
        assert failed["status"] == "failed" and failed["attempts"] == 5
        assert failed["last_error"] == "LeaseAttemptsExhausted"
        assert failed["lease_owner"] is None and failed["lease_until"] is None
        assert db.execute("SELECT COUNT(*) FROM forecast_jobs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM operational_events WHERE type='job.failed'").fetchone()[0] == 1
    with pytest.raises(RuntimeError, match="lease"):
        execute(claimed, "crashed-4", exhausted_at, fake_forecaster)

    # Only an explicit administrator retry starts another bounded attempt cycle.
    monkeypatch.setattr(operational, "utc_now", lambda: exhausted_at)
    assert operational.retry_job(identifier, admin)["data"]["status"] == "pending"
    retried = claim("manual-retry", exhausted_at)
    assert retried["id"] == identifier and retried["attempts"] == 1
    execute(retried, "manual-retry", exhausted_at, fake_forecaster)
    with connection() as db:
        assert db.execute("SELECT status FROM forecast_jobs WHERE id=?", (identifier,)).fetchone()[0] == "completed"
        assert db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 1


def test_late_window_completes_separate_event_without_rewriting_point(pipeline):
    admin, source, now = pipeline
    seed(pipeline)
    process_next("w", now.isoformat(), fake_forecaster)
    with connection() as db:
        forecast = db.execute("SELECT id FROM forecasts").fetchone()[0]
    t30 = now + timedelta(minutes=30)
    ingest(source["id"], IncomingObservation(source_event_id="target", timestamp=t30.isoformat(), glucose_mg_dl=150), admin, t30.isoformat())
    # Existing queued jobs share a receipt until the newly arrived evidence changes the digest.
    for _ in range(5):
        process_next("w", t30.isoformat(), fake_forecaster)
    with connection() as db:
        point = dict(db.execute("SELECT * FROM forecast_outcomes WHERE forecast_id=? AND horizon_minutes=30", (forecast,)).fetchone())
        assert point["event_occurred"] is None
        assert db.execute("SELECT COUNT(*) FROM event_outcomes WHERE forecast_id=?", (forecast,)).fetchone()[0] == 0
    arrived = now + timedelta(minutes=45)
    ingest(source["id"], IncomingObservation(source_event_id="late-intermediate", timestamp=(now + timedelta(minutes=15)).isoformat(), glucose_mg_dl=190), admin, arrived.isoformat())
    process_next("w", arrived.isoformat(), fake_forecaster)
    with connection() as db:
        after = dict(db.execute("SELECT * FROM forecast_outcomes WHERE id=?", (point["id"],)).fetchone())
        event = db.execute("SELECT * FROM event_outcomes WHERE forecast_id=? AND horizon_minutes=30", (forecast,)).fetchone()
        assert after == point
        assert event["event_occurred"] == 1 and event["available_at"] == arrived.isoformat()


def test_review_revision_future_filter_and_clinic_scope(pipeline):
    admin, source, now = pipeline
    seed(pipeline)
    process_next("w", now.isoformat(), fake_forecaster)
    review = queue(now.isoformat(), admin)["data"]["items"][0]
    changed = update_review(review["id"], ReviewAction(status="reviewed", expected_revision=review["revision"], reason="Reviewed research evidence", disposition="reviewed_no_action"), admin)["data"]
    assert changed["revision"] == review["revision"] + 1
    with pytest.raises(HTTPException) as error:
        update_review(review["id"], ReviewAction(status="closed", expected_revision=review["revision"], reason="Stale tab"), admin)
    assert error.value.status_code == 409
    assert queue((now - timedelta(minutes=1)).isoformat(), admin)["data"]["items"] == []
    with pytest.raises(HTTPException) as error:
        receipt_record(review["forecast_id"], {"id": "other", "clinic_id": "other-clinic", "role": "admin"})
    assert error.value.status_code == 404


def test_paused_source_and_real_connection_are_gated(pipeline):
    admin, source, now = pipeline
    seed(pipeline)
    change_connection(source["id"], ConnectionState(status="paused"), admin)
    assert claim("w", now.isoformat()) is None
    with pytest.raises(HTTPException):
        ingest(source["id"], IncomingObservation(source_event_id="paused", timestamp=now.isoformat(), glucose_mg_dl=100), admin, now.isoformat())
    pending = create_connection(ConnectionInput(name="Clinic access pending", source_type="clinic_pending"), admin)["data"]
    assert pending["status"] == "pending" and pending["connection_key"] is None
    with pytest.raises(HTTPException):
        change_connection(pending["id"], ConnectionState(status="enabled"), admin)


def test_old_database_migrates_and_audit_mutations_are_rejected(pipeline):
    with connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] >= 6
        assert "disposition" in {row[1] for row in db.execute("PRAGMA table_info(actions)")}
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE audit SET event='tampered'")


def test_generator_seed_has_actual_receipts_and_native_wall_clock_ticks(pipeline, monkeypatch):
    admin, source, now = pipeline
    monkeypatch.setattr("backend.operational.utc_now", lambda: now.isoformat())
    configured = configure_generator(source["id"], GeneratorInput(enabled=True, seed=True), admin)["data"]
    assert configured["seeded_readings"] == 8
    next_at = datetime.fromisoformat(configured["next_read_at"])
    assert next_at == now + timedelta(minutes=14)
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 0
        assert {row[0] for row in db.execute("SELECT available_at FROM observations")} == {now.isoformat()}
    process_next("native-generator", now.isoformat())
    with connection() as db:
        row = db.execute("SELECT * FROM forecasts").fetchone()
        assert row["issued_at"] == now.isoformat()
        model = json.loads(row["snapshot_json"])["clinic_model"]
        assert model["quality"]["status"] == "ok"
        assert model["forecasts"]["population"]
        assert model["clinical_queue_eligible"] is False
    assert tick_generators((next_at - timedelta(seconds=1)).isoformat()) == 0
    assert tick_generators(next_at.isoformat()) == 1
    assert tick_generators(next_at.isoformat()) == 0
    with connection() as db:
        latest = db.execute("SELECT timestamp,available_at FROM observations ORDER BY timestamp DESC LIMIT 1").fetchone()
        assert latest[0] == next_at.isoformat() and latest[1] == next_at.isoformat()
    change_connection(source["id"], ConnectionState(status="revoked"), admin)
    assert tick_generators((next_at + timedelta(minutes=15)).isoformat()) == 0


def test_one_minute_feed_is_fresh_but_never_claims_model_compatibility(pipeline, monkeypatch):
    admin, _, now = pipeline
    source = create_connection(ConnectionInput(name="Fast feed display", patient_id="SIM-FAST", cadence_minutes=1), admin)["data"]
    monkeypatch.setattr("backend.operational.utc_now", lambda: now.isoformat())
    configured = configure_generator(source["id"], GeneratorInput(enabled=True, seed=True), admin)["data"]
    due = configured["next_read_at"]
    assert tick_generators(due) == 1
    process_next("fast-display", due)
    with connection() as db:
        row = db.execute("SELECT snapshot_json FROM forecasts WHERE patient_id='SIM-FAST'").fetchone()
        model = json.loads(row[0])["clinic_model"]
        assert model["quality"]["status"] == "unsupported_cadence"
        assert model["forecasts"] == {"population": [], "hybrid": []}
    with connection() as db:
        before = db.execute("SELECT COUNT(*) FROM observations WHERE patient_id='SIM-FAST'").fetchone()[0]
    assert tick_generators((time_from(due) + timedelta(minutes=5)).isoformat()) == 0
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM observations WHERE patient_id='SIM-FAST'").fetchone()[0] == before


def time_from(value):
    return datetime.fromisoformat(value)


def test_fifty_streams_keep_pipeline_and_patient_receipts_separate(pipeline):
    admin, _, now = pipeline
    for index in range(50):
        source = create_connection(ConnectionInput(name=f"Synthetic stream {index}", patient_id=f"SIM-LOAD-{index}"), admin)["data"]
        for step in range(5):
            measured = now - timedelta(minutes=15 * (4 - step))
            ingest(source["id"], IncomingObservation(source_event_id=f"sample-{step}", timestamp=measured.isoformat(), glucose_mg_dl=120 + index), admin, now.isoformat())
    processed = 0
    while process_next("load-check", now.isoformat(), fake_forecaster):
        processed += 1
    with connection() as db:
        assert processed == 250
        assert db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 50
        assert db.execute("SELECT COUNT(DISTINCT patient_id) FROM forecasts").fetchone()[0] == 50
        assert db.execute("SELECT COUNT(*) FROM forecast_jobs WHERE status!='completed'").fetchone()[0] == 0
        for row in db.execute("SELECT patient_id,snapshot_json FROM forecasts"):
            snapshot = json.loads(row["snapshot_json"])
            assert snapshot["patient"]["id"] == row["patient_id"]


def test_http_connection_key_is_scoped_and_never_grants_clinic_access(pipeline):
    from fastapi.testclient import TestClient
    from backend.main import app
    admin, source, now = pipeline
    other = create_connection(ConnectionInput(name="Other synthetic source", patient_id="SIM-OTHER"), admin)["data"]
    with TestClient(app) as client:
        payload = {"source_event_id": "device-http-event", "timestamp": datetime.now(timezone.utc).isoformat(), "glucose_mg_dl": 145}
        headers = {"X-Connection-Key": source["connection_key"]}
        assert client.post(f"/api/v2/connections/{source['id']}/observations", json=payload, headers=headers).status_code == 202
        assert client.post(f"/api/v2/connections/{other['id']}/observations", json=payload, headers=headers).status_code == 401
        assert client.get("/api/v2/queue", headers=headers).status_code == 401
        response = client.post("/api/auth/login", json={"username": "admin", "password": "test-only-admin-password"})
        bearer = {"Authorization": "Bearer " + response.json()["data"]["token"]}
        listed = client.get("/api/v2/connections", headers=bearer).json()["data"]["items"]
        assert all("connection_key_hash" not in item and "connection_key" not in item for item in listed)
        assert client.patch(f"/api/v2/connections/{source['id']}", json={"status": "revoked"}, headers=bearer).status_code == 200
        assert client.post(f"/api/v2/connections/{source['id']}/observations", json=payload, headers=headers).status_code == 401


def test_readiness_requires_current_model_worker_and_checksum(pipeline, monkeypatch, tmp_path):
    from backend.worker import heartbeat
    from backend import arrival_model
    admin, _, _ = pipeline
    assert readiness(admin).status_code == 503
    heartbeat("readiness-check")
    response = readiness(admin)
    assert response.status_code == 200
    data = json.loads(response.body)["data"]
    assert data["schema_version"] == 7 and data["model_versions"]
    assert data["clinical_ready"] is False and data["doctor_review_status"] == "pending"
    monkeypatch.setenv("GLUCOTWIN_EXPECTED_MODEL_SHA256", "0" * 64)
    assert readiness(admin).status_code == 503
    monkeypatch.delenv("GLUCOTWIN_EXPECTED_MODEL_SHA256")
    monkeypatch.setattr(arrival_model, "ROOT", tmp_path)
    assert readiness(admin).status_code == 503


def test_readiness_database_failure_is_unavailable_without_payload(pipeline, monkeypatch):
    from contextlib import contextmanager
    from backend import operational
    admin, _, _ = pipeline

    @contextmanager
    def unavailable():
        raise sqlite3.OperationalError("Private clinical note and credential must not reach the response")
        yield

    original = operational.connection
    monkeypatch.setattr(operational, "connection", unavailable)
    response = readiness(admin)
    assert response.status_code == 503
    data = json.loads(response.body)["data"]
    assert data["database"] == "unavailable" and data["clinical_ready"] is False
    assert "Private" not in response.body.decode() and "credential" not in response.body.decode()

    # The operational-state read is also part of the database readiness boundary.
    monkeypatch.setattr(operational, "connection", original)

    def operations_unavailable(user):
        raise sqlite3.OperationalError("Private operational payload")

    monkeypatch.setattr(operational, "operations", operations_unavailable)
    assert readiness(admin).status_code == 503


def test_any_future_measurement_is_quarantined_not_permanently_poisoned(pipeline):
    admin, source, now = pipeline
    future = now + timedelta(seconds=10)
    payload = IncomingObservation(source_event_id="clock-skew", timestamp=future.isoformat(), glucose_mg_dl=140)
    data, status = ingest(source["id"], payload, admin, now.isoformat())
    assert status == 409 and data["reason"] == "future_measurement"
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM forecast_jobs").fetchone()[0] == 0
    data, status = ingest(source["id"], payload, admin, future.isoformat())
    assert status == 202 and data["accepted"]


def test_delayed_issue_event_window_uses_measurement_anchor(pipeline):
    admin, source, now = pipeline
    seed(pipeline)
    process_next("delay-window", (now + timedelta(minutes=1)).isoformat(), fake_forecaster)
    with connection() as db:
        forecast = db.execute("SELECT id FROM forecasts").fetchone()[0]
    for minute, glucose in [(15, 190), (30, 150)]:
        measured = now + timedelta(minutes=minute)
        ingest(source["id"], IncomingObservation(source_event_id=f"delayed-outcome-{minute}", timestamp=measured.isoformat(), glucose_mg_dl=glucose), admin, measured.isoformat())
    while process_next("delay-window", (now + timedelta(minutes=30)).isoformat(), fake_forecaster):
        pass
    with connection() as db:
        point = db.execute("SELECT * FROM forecast_outcomes WHERE forecast_id=? AND horizon_minutes=30", (forecast,)).fetchone()
        event = db.execute("SELECT * FROM event_outcomes WHERE forecast_id=? AND horizon_minutes=30", (forecast,)).fetchone()
        assert point["actual_glucose_mg_dl"] == 150 and point["event_occurred"] is None
        assert event["event_occurred"] == 1
        assert event["target_time"] == (now + timedelta(minutes=30)).isoformat()
