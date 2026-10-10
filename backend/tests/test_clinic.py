"""Clinic acceptance tests use isolated databases and fully synthetic inputs."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.auth import password_hash
from backend.storage import backup, connection, restore


@pytest.fixture
def clinic(tmp_path, monkeypatch):
    monkeypatch.setenv("GLUCOTWIN_DB_PATH", str(tmp_path / "clinic.sqlite3"))
    monkeypatch.setenv("GLUCOTWIN_CREDENTIALS_PATH", str(tmp_path / "credentials.json"))
    monkeypatch.setenv("GLUCOTWIN_ADMIN_PASSWORD", "test-only-admin-password")
    monkeypatch.setenv("GLUCOTWIN_REVIEWER_PASSWORD", "test-only-reviewer-password")
    start = datetime(2021, 1, 4, 10)
    records = [{"timestamp": (start + timedelta(minutes=15 * index)).isoformat(), "glucose_mg_dl": 140 + index / 5} for index in range(40)]
    profile = {"id": "P-001", "name": "Public research profile", "age": 55, "bmi": 27, "sex": "Female", "recording_id": "r1"}
    monkeypatch.setattr(main, "data_store", lambda: {"patients": [profile], "observations": {"P-001": records}, "bundle": None})
    from backend import hybrid
    monkeypatch.setattr(hybrid, "load_clinic_bundle", lambda *args, **kwargs: {})
    with TestClient(main.app) as client:
        tokens = {}
        for username in ["admin", "reviewer"]:
            response = client.post("/api/auth/login", json={"username": username, "password": f"test-only-{username}-password"})
            assert response.status_code == 200
            tokens[username] = {"Authorization": f"Bearer {response.json()['data']['token']}"}
        yield client, tokens, records, tmp_path


def test_patient_endpoints_require_authentication(clinic):
    client, tokens, _, _ = clinic
    assert client.get("/api/health").status_code == 200
    for path in ["/api/patients", "/api/replay/P-001", "/api/benchmarks", "/api/provenance", "/api/clinic/queue", "/api/clinic/report/P-001"]:
        assert client.get(path).status_code == 401
    assert client.get("/api/patients", headers=tokens["reviewer"]).status_code == 200


def test_login_logout_and_admin_permissions(clinic):
    client, tokens, _, _ = clinic
    assert client.post("/api/auth/login", json={"username": "reviewer", "password": "wrong"}).status_code == 401
    assert client.put("/api/clinic/monitoring", headers=tokens["reviewer"], json={}).status_code == 403
    assert client.post("/api/auth/logout", headers=tokens["reviewer"]).status_code == 200
    assert client.get("/api/auth/me", headers=tokens["reviewer"]).status_code == 401


def test_cross_clinic_records_are_inaccessible(clinic):
    client, _, _, _ = clinic
    with connection() as db:
        db.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", ("other", "other", "Other reviewer", password_hash("test-only-other-password"), "reviewer", "other-clinic"))
    token = client.post("/api/auth/login", json={"username": "other", "password": "test-only-other-password"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/patients", headers=headers).json()["data"] == []
    for path in ["/api/replay/P-001", "/api/clinic/timeline/P-001", "/api/clinic/report/P-001"]:
        assert client.get(path, headers=headers).status_code == 404


def test_review_lifecycle_dedup_and_forecast_immutability(clinic):
    client, tokens, _, _ = clinic
    headers = tokens["reviewer"]
    first = client.post("/api/clinic/capture/P-001", headers=headers, json={"cursor": 10}).json()["data"]
    duplicate = client.post("/api/clinic/capture/P-001", headers=headers, json={"cursor": 10}).json()["data"]
    next_capture = client.post("/api/clinic/capture/P-001", headers=headers, json={"cursor": 11}).json()["data"]
    assert first["forecast_id"] == duplicate["forecast_id"]
    assert first["review_id"] == duplicate["review_id"] == next_capture["review_id"]
    review_id = first["review_id"]
    assert client.patch(f"/api/clinic/reviews/{review_id}", headers=headers, json={"status": "closed", "reason": "too early"}).status_code == 409
    assert client.patch(f"/api/clinic/reviews/{review_id}", headers=headers, json={"status": "reviewed", "reason": "Inspected evidence", "note": "<b>literal text</b>"}).status_code == 200
    assert client.patch(f"/api/clinic/reviews/{review_id}", headers=headers, json={"status": "follow_up_planned", "reason": "Check next visit"}).status_code == 422
    assert client.patch(f"/api/clinic/reviews/{review_id}", headers=headers, json={"status": "follow_up_planned", "reason": "Check next visit", "next_review_at": "2026-10-11T10:00:00Z"}).status_code == 200
    with connection() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE forecasts SET snapshot_json='{}' WHERE id=?", (first["forecast_id"],))
    detail = client.get(f"/api/clinic/reviews/{review_id}", headers=headers).json()["data"]
    assert len(detail["actions"]) == 2 and detail["status"] == "follow_up_planned"


def test_missing_data_and_inactive_monitoring(clinic):
    client, tokens, _, _ = clinic
    client.put("/api/clinic/monitoring", headers=tokens["admin"], json={"start_hour": 1, "end_hour": 2, "days": list(range(7))})
    captured = client.post("/api/clinic/capture/P-001", headers=tokens["reviewer"], json={"cursor": 12, "scenario": "sensor_gap"}).json()["data"]
    assert captured["snapshot"]["forecasts"] == {"twin": [], "population": []}
    assert captured["monitoring"]["active"] is False
    queue = client.get("/api/clinic/queue", headers=tokens["reviewer"]).json()["data"]
    assert queue["items"][0]["type"] == "missing_data"
    evidence = client.get("/api/clinic/timeline/P-001?at=2021-01-04T13:00:00&scenario=sensor_gap", headers=tokens["reviewer"]).json()["data"]
    assert evidence["quality"]["minutes_since_reading"] == 45
    assert max(row["timestamp"] for row in evidence["events"] if row["type"] == "observation") == "2021-01-04T12:15:00"


def test_late_context_and_future_data_do_not_rewrite_issued_record(clinic):
    client, tokens, records, _ = clinic
    headers = tokens["reviewer"]
    capture = client.post("/api/clinic/capture/P-001", headers=headers, json={"cursor": 10}).json()["data"]
    with connection() as db:
        before = db.execute("SELECT snapshot_json FROM forecasts WHERE id=?", (capture["forecast_id"],)).fetchone()[0]
    client.post("/api/clinic/context/P-001", headers=headers, json={"kind": "historical", "value": {"bmi": 99}, "observed_at": "2021-01-04T09:00:00Z", "available_at": "2021-01-04T18:00:00Z", "provenance": "simulated"})
    for row in records[11:]:
        row["glucose_mg_dl"] = 300
    snapshot = client.get("/api/replay/P-001?cursor=10", headers=headers).json()["data"]
    assert snapshot["patient"]["bmi"] == 27
    with connection() as db:
        assert db.execute("SELECT snapshot_json FROM forecasts WHERE id=?", (capture["forecast_id"],)).fetchone()[0] == before


def test_streaming_duplicate_validation_and_late_arrival(clinic):
    client, tokens, _, _ = clinic
    headers = tokens["admin"]
    start = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
    for i in range(8):
        stamp = (start + timedelta(minutes=15 * i)).isoformat()
        payload = {"timestamp": stamp, "available_at": stamp, "glucose_mg_dl": 140 + 2 * i}
        response = client.post("/api/clinic/stream/SIM-NEW", headers=headers, json=payload)
        assert response.status_code == 200
    assert response.json()["data"]["snapshot"]["quality"]["status"] == "ok"
    assert client.post("/api/clinic/stream/SIM-NEW", headers=headers, json=payload).json()["data"]["duplicates"] == 1
    assert client.post("/api/clinic/stream/SIM-NEW", headers=headers, json={**payload, "glucose_mg_dl": 300}).status_code == 409
    late = {"timestamp": (start + timedelta(minutes=120)).isoformat(), "available_at": (start + timedelta(minutes=180)).isoformat(), "glucose_mg_dl": 170}
    response = client.post("/api/clinic/stream/SIM-NEW", headers=headers, json=late)
    assert response.json()["data"]["snapshot"]["quality"]["status"] == "gap"
    assert client.post("/api/clinic/stream/SIM-NEW", headers=headers, json={"timestamp": "2026-10-10T10:00:00", "glucose_mg_dl": 100}).status_code == 422


def test_csv_and_fhir_intake_preserve_identity_units_and_timestamps(clinic):
    client, tokens, _, _ = clinic
    headers = tokens["admin"]
    csv_text = "patient_id,timestamp,glucose_mg_dl,available_at,source\nSIM-CSV,2026-10-10T10:00:00Z,140,2026-10-10T10:00:00Z,simulated\n"
    assert client.post("/api/clinic/intake/csv", headers=headers, json={"csv": csv_text}).json()["data"]["accepted"] == 1
    assert client.post("/api/clinic/intake/csv", headers=headers, json={"csv": csv_text}).json()["data"]["duplicates"] == 1
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": [
        {"resource": {"resourceType": "Patient", "id": "SIM-FHIR"}},
        {"resource": {"resourceType": "Observation", "subject": {"reference": "Patient/SIM-FHIR"}, "code": {"coding": [{"system": "http://loinc.org", "code": "2339-0"}]}, "valueQuantity": {"value": 8, "system": "http://unitsofmeasure.org", "code": "mmol/L"}, "effectiveDateTime": "2026-10-10T10:00:00Z", "meta": {"lastUpdated": "2026-10-10T10:00:00Z"}}}]}
    response = client.post("/api/clinic/intake/fhir", headers=headers, json={"bundle": bundle})
    assert response.status_code == 200 and response.json()["data"]["accepted"] == 1
    snapshot = client.get("/api/replay/SIM-FHIR", headers=headers).json()["data"]
    assert snapshot["observations"][0]["glucose_mg_dl"] == pytest.approx(144.1456)
    bundle["entry"][1]["resource"]["subject"]["reference"] = "Patient/unknown"
    assert client.post("/api/clinic/intake/fhir", headers=headers, json={"bundle": bundle}).status_code == 422


def test_backup_restore_and_consultation_pdf(clinic):
    client, tokens, _, tmp_path = clinic
    headers = tokens["reviewer"]
    captured = client.post("/api/clinic/capture/P-001", headers=headers, json={"cursor": 10}).json()["data"]
    client.patch(f"/api/clinic/reviews/{captured['review_id']}", headers=headers, json={"status": "reviewed", "reason": "Evidence inspected", "note": "<img src=x> & literal text"})
    destination = tmp_path / "backup.sqlite3"
    backup(destination)
    with connection() as db:
        db.execute("UPDATE reviews SET status='closed'")
    restore(destination)
    detail = client.get(f"/api/clinic/reviews/{captured['review_id']}", headers=headers).json()["data"]
    assert detail["status"] == "reviewed" and len(detail["actions"]) == 1
    pdf = client.get("/api/clinic/report/P-001?at=2021-01-04T12:30:00", headers=headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert pdf.headers["content-type"] == "application/pdf"


def test_bulk_intake_rolls_back_and_fhir_context_is_dated_and_idempotent(clinic):
    client, tokens, _, _ = clinic
    headers = tokens["admin"]
    invalid_csv = "patient_id,timestamp,glucose_mg_dl,available_at,source\nSIM-ROLLBACK,2026-10-10T10:00:00Z,140,2026-10-10T10:00:00Z,simulated\nSIM-ROLLBACK,2026-10-10T10:00:00Z,200,2026-10-10T10:00:00Z,simulated\n"
    assert client.post("/api/clinic/intake/csv", headers=headers, json={"csv": invalid_csv}).status_code == 409
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM observations WHERE patient_id='SIM-ROLLBACK'").fetchone()[0] == 0
    stamp = "2026-10-10T09:00:00Z"
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": [
        {"resource": {"resourceType": "Patient", "id": "SIM-DATED", "gender": "female", "birthDate": "1971-01-01", "meta": {"lastUpdated": stamp}}},
        {"resource": {"resourceType": "Observation", "subject": {"reference": "Patient/SIM-DATED"}, "code": {"coding": [{"system": "http://loinc.org", "code": "39156-5"}]}, "valueQuantity": {"value": 28, "system": "http://unitsofmeasure.org", "code": "kg/m2"}, "effectiveDateTime": stamp, "meta": {"lastUpdated": stamp}}},
        {"resource": {"resourceType": "Condition", "subject": {"reference": "Patient/SIM-DATED"}, "code": {"text": "Type 2 diabetes (synthetic)"}, "recordedDate": stamp, "meta": {"lastUpdated": stamp}}}]}
    assert client.post("/api/clinic/intake/fhir", headers=headers, json={"bundle": bundle}).status_code == 200
    assert client.post("/api/clinic/intake/fhir", headers=headers, json={"bundle": bundle}).status_code == 200
    from backend.clinic import profile_at
    user = {"id": "admin", "clinic_id": "demo-clinic", "role": "admin"}
    old = profile_at("SIM-DATED", user, "2026-10-10T08:00:00Z")
    new = profile_at("SIM-DATED", user, "2026-10-10T10:00:00Z")
    assert "bmi" not in old and new["bmi"] == 28 and new["age"] == 55 and new["sex"] == "Female"
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM context WHERE patient_id='SIM-DATED'").fetchone()[0] == 3
    bundle["entry"][0]["resource"]["id"] = "SIM-REJECTED"
    assert client.post("/api/clinic/intake/fhir", headers=headers, json={"bundle": bundle}).status_code == 422
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM profiles WHERE patient_id='SIM-REJECTED'").fetchone()[0] == 0


def test_public_csv_requires_admin_provenance_and_future_reviews_are_hidden(clinic):
    client, tokens, _, _ = clinic
    body = {"csv": "patient_id,timestamp,glucose_mg_dl,available_at,source\nPUB-2079,2021-08-09T10:00:00Z,140,2021-08-09T10:00:00Z,anonymized_public\n", "attested_anonymized_public": True,
            "source_url": "https://figshare.com/articles/dataset/diabetes_datasets_zip/21600933", "source_license": "CC BY 4.0"}
    assert client.post("/api/clinic/intake/csv", headers=tokens["reviewer"], json=body).status_code == 403
    response = client.post("/api/clinic/intake/csv", headers=tokens["admin"], json=body)
    assert response.status_code == 200 and response.json()["data"]["accepted"] == 1
    snapshot = client.get("/api/replay/PUB-2079", headers=tokens["admin"]).json()["data"]
    assert snapshot["patient"]["source"] == "anonymized_public" and snapshot["playback"]["kind"] == "public_csv_replay"
    client.post("/api/clinic/capture/P-001", headers=tokens["reviewer"], json={"cursor": 15})
    earlier = client.get("/api/clinic/timeline/P-001?at=2021-01-04T10:00:00", headers=tokens["reviewer"]).json()["data"]
    assert earlier["reviews"] == [] and all(event["type"] != "forecast" for event in earlier["events"])


def test_outcomes_mature_only_after_target_and_are_append_only(clinic):
    client, tokens, _, _ = clinic
    headers = tokens["reviewer"]
    captured = client.post("/api/clinic/capture/P-001", headers=headers, json={"cursor": 10}).json()["data"]
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM forecast_outcomes").fetchone()[0] == 0
    client.post("/api/clinic/capture/P-001", headers=headers, json={"cursor": 11})
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM forecast_outcomes").fetchone()[0] == 0
    client.post("/api/clinic/capture/P-001", headers=headers, json={"cursor": 12})
    with connection() as db:
        outcome = db.execute("SELECT * FROM forecast_outcomes WHERE forecast_id=?", (captured["forecast_id"],)).fetchone()
        assert outcome["horizon_minutes"] == 30 and outcome["actual_glucose_mg_dl"] == pytest.approx(142.4)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE forecast_outcomes SET actual_glucose_mg_dl=300 WHERE id=?", (outcome["id"],))
    prior = client.get("/api/clinic/timeline/P-001?at=2021-01-04T12:30:00", headers=headers).json()["data"]
    assert all(outcome["actual"] is None for event in prior["events"] if event["type"] == "forecast" for outcome in event["outcomes"] if outcome["target_time"] > prior["at"])


def test_sixty_minute_risk_is_supplementary_not_actionable(clinic, monkeypatch):
    client, tokens, _, _ = clinic
    from backend import hybrid
    monkeypatch.setattr(hybrid, "clinic_forecast", lambda *args, **kwargs: {
        "model": {"version": "test-30-primary", "primary": "population"}, "forecasts": {"population": [], "hybrid": []},
        "event_risks": [{"horizon_minutes": 30, "probability": .1, "threshold": .4, "event_eligible": True, "exceeds_threshold": False},
                        {"horizon_minutes": 60, "probability": .9, "threshold": .4, "event_eligible": True, "exceeds_threshold": True}]})
    headers = tokens["reviewer"]
    snapshot = client.get("/api/replay/P-001?cursor=10", headers=headers).json()["data"]
    assert snapshot["alerts"] == [] and snapshot["clinic_model"]["event_risks"][1]["exceeds_threshold"]
    client.post("/api/clinic/capture/P-001", headers=headers, json={"cursor": 10})
    assert client.get("/api/clinic/queue", headers=headers).json()["data"]["items"][0]["type"] == "forecast_review"


def test_unsupported_primary_cannot_inherit_legacy_warning(clinic, monkeypatch):
    client, tokens, records, _ = clinic
    from backend import hybrid
    for index, row in enumerate(records[:11]):
        row["glucose_mg_dl"] = 100 + index * 7.8
    monkeypatch.setattr(hybrid, "clinic_forecast", lambda *args, **kwargs: {
        "model": {"version": "test-primary-unavailable", "primary": "population"},
        "forecasts": {"population": [], "hybrid": []}, "event_risks": []})
    snapshot = client.get("/api/replay/P-001?cursor=10", headers=tokens["reviewer"]).json()["data"]
    assert snapshot["forecasts"]["twin"][0]["glucose_mg_dl"] > 180
    assert snapshot["alerts"] == []
