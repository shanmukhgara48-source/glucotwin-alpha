"""Privacy, cookie authentication and care publication tests on disposable synthetic records."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.identity import totp
from backend.storage import connection


@pytest.fixture
def platform(tmp_path, monkeypatch):
    monkeypatch.setenv("GLUCOTWIN_DB_PATH", str(tmp_path / "platform.sqlite3"))
    monkeypatch.setenv("GLUCOTWIN_CREDENTIALS_PATH", str(tmp_path / "credentials.json"))
    monkeypatch.setenv("GLUCOTWIN_KEY_PATH", str(tmp_path / "secret.key"))
    monkeypatch.setenv("GLUCOTWIN_DISABLE_WORKER", "1")
    for role in ["admin", "reviewer", "clinician", "coordinator", "patient"]:
        monkeypatch.setenv(f"GLUCOTWIN_{role.upper()}_PASSWORD", f"private-test-{role}-password")
    with TestClient(app) as client:
        yield client


def signin(client, role):
    response = client.post("/api/v2/auth/login", json={"username": role, "password": f"private-test-{role}-password"})
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert "token" not in body
    return {"X-CSRF-Token": body["csrf_token"]}


def test_cookie_session_is_http_only_and_requires_csrf(platform):
    headers = signin(platform, "admin")
    cookies = platform.cookies
    assert cookies.get("glucotwin_session")
    assert platform.get("/api/v2/auth/me").status_code == 200
    assert platform.post("/api/v2/auth/logout").status_code == 403
    assert platform.post("/api/v2/auth/logout", headers=headers).status_code == 200
    assert platform.get("/api/v2/auth/me").status_code == 401


def test_patient_cannot_read_clinic_or_other_patient_evidence(platform):
    signin(platform, "patient")
    for path in ["/api/patients", "/api/clinic/queue", "/api/replay/2072", "/api/clinic/report/SIM-COMPANION", "/api/v2/platform/staff", "/api/v2/connections", "/api/v2/reviews", "/api/v2/platform/patients"]:
        assert platform.get(path).status_code in {403, 404}, path
    data = platform.get("/api/v2/patient/me").json()["data"]
    assert data["patient"]["id"] == "SIM-COMPANION"
    assert "forecasts" not in data and data["predictions_enabled"] is False


def test_patient_context_is_self_reported_and_receipt_is_server_time(platform):
    headers = signin(platform, "patient")
    observed = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    response = platform.post("/api/v2/patient/context", headers=headers, json={"kind": "meal", "value": "Synthetic lunch context", "observed_at": observed})
    assert response.status_code == 200
    data = platform.get("/api/v2/patient/me").json()["data"]
    assert data["contexts"][0]["provenance"] == "self_reported"
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert platform.post("/api/v2/patient/context", headers=headers, json={"kind": "symptom", "value": "Future", "observed_at": future}).status_code == 422


def test_invitation_is_single_use_and_deactivation_revokes_sessions(platform):
    headers = signin(platform, "admin")
    invited = platform.post("/api/v2/platform/staff", headers=headers, json={"username": "new-reviewer", "name": "New reviewer", "role": "clinician"}).json()["data"]
    password = "private-test-new-account"
    assert platform.post("/api/v2/auth/login", json={"username": "new-reviewer", "password": password}).status_code == 401
    body = {"invitation_code": invited["invitation_code"], "password": password}
    assert platform.post("/api/v2/auth/activate", json=body).status_code == 200
    assert platform.post("/api/v2/auth/activate", json=body).status_code == 422
    login = platform.post("/api/auth/login", json={"username": "new-reviewer", "password": password}).json()["data"]
    assert platform.post(f"/api/v2/platform/staff/{invited['user']['id']}/deactivate", headers=headers).status_code == 200
    assert platform.get("/api/auth/me", headers={"Authorization": "Bearer " + login["token"]}).status_code == 401


def test_concurrent_activation_consumes_invitation_once(platform):
    from concurrent.futures import ThreadPoolExecutor
    headers = signin(platform, "admin")
    invited = platform.post("/api/v2/platform/staff", headers=headers, json={"username": "concurrent-invite", "name": "Synthetic invitation", "role": "clinician"}).json()["data"]
    body = {"invitation_code": invited["invitation_code"], "password": "private-concurrent-password"}
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda _: platform.post("/api/v2/auth/activate", json=body).status_code, range(2)))
    assert sorted(outcomes) == [200, 422]


def test_coordinator_cannot_publish_and_patient_only_completes_own_task(platform):
    body = {"patient_id": "SIM-COMPANION", "title": "Synthetic follow-up", "instructions": "Review your demonstration note."}
    headers = signin(platform, "coordinator")
    assert platform.post("/api/v2/platform/tasks", headers=headers, json=body).status_code == 403
    headers = signin(platform, "clinician")
    task = platform.post("/api/v2/platform/tasks", headers=headers, json=body).json()["data"]
    headers = signin(platform, "patient")
    assert platform.post(f"/api/v2/patient/tasks/{task['id']}/complete", headers=headers).status_code == 200
    assert platform.post("/api/v2/patient/tasks/99999/complete", headers=headers).status_code == 404
    report = platform.get("/api/v2/patient/report")
    assert report.status_code == 200 and report.content.startswith(b"%PDF")


def test_private_context_stays_hidden_until_a_clinician_shares_a_note(platform):
    with connection() as db:
        stamp = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO context(clinic_id,patient_id,kind,value_json,observed_at,available_at,provenance,created_by) VALUES(?,?,?,?,?,?,?,?)", ("demo-clinic", "SIM-COMPANION", "clinical_note", json.dumps("Private assessment"), stamp, stamp, "care_team", "reviewer"))
    payload = {"patient_id": "SIM-COMPANION", "note": "Approved synthetic consultation note"}
    headers = signin(platform, "coordinator")
    assert platform.post("/api/v2/platform/shared-notes", headers=headers, json=payload).status_code == 403
    headers = signin(platform, "clinician")
    assert platform.post("/api/v2/platform/shared-notes", headers=headers, json=payload).status_code == 200
    signin(platform, "patient")
    contexts = platform.get("/api/v2/patient/me").json()["data"]["contexts"]
    assert [row["value"] for row in contexts] == [payload["note"]]
    assert contexts[0]["provenance"] == "clinician_approved"


def test_mfa_is_encrypted_and_required_on_subsequent_login(platform):
    headers = signin(platform, "clinician")
    old_session = platform.post("/api/auth/login", json={"username": "clinician", "password": "private-test-clinician-password"}).json()["data"]["token"]
    setup = platform.post("/api/v2/auth/mfa/setup", headers=headers).json()["data"]
    code = totp(setup["secret"])
    assert platform.post("/api/v2/auth/mfa/confirm", headers=headers, json={"otp": code}).status_code == 200
    assert platform.get("/api/auth/me", headers={"Authorization": "Bearer " + old_session}).status_code == 401
    assert platform.get("/api/v2/auth/me").status_code == 200
    with connection() as db:
        encrypted = db.execute("SELECT encrypted_secret FROM auth_mfa WHERE user_id='clinician'").fetchone()[0]
    assert setup["secret"] not in encrypted
    assert platform.post("/api/v2/auth/login", json={"username": "clinician", "password": "private-test-clinician-password"}).status_code == 401
    assert platform.post("/api/v2/auth/login", json={"username": "clinician", "password": "private-test-clinician-password", "otp": code}).status_code == 200


def test_failed_signins_are_throttled(platform):
    for _ in range(5):
        assert platform.post("/api/v2/auth/login", json={"username": "absent", "password": "incorrect"}).status_code == 401
    assert platform.post("/api/v2/auth/login", json={"username": "absent", "password": "incorrect"}).status_code == 429


def test_intake_preview_never_commits(platform):
    headers = signin(platform, "admin")
    text = "patient_id,timestamp,glucose_mg_dl,available_at,source\nSIM-PREVIEW,2026-10-01T10:00:00Z,140,2026-10-01T10:01:00Z,simulated\nSIM-PREVIEW,2026-10-01T10:00:00Z,200,2026-10-01T10:01:00Z,simulated"
    data = platform.post("/api/v2/platform/intake/preview", headers=headers, json={"csv": text}).json()["data"]
    assert data["can_import"] is False and data["invalid_count"] == 1 and data["committed"] is False
    with connection() as db:
        assert not db.execute("SELECT 1 FROM observations WHERE patient_id='SIM-PREVIEW'").fetchone()


def test_patient_consent_withdrawal_revokes_only_the_bound_connection(platform):
    headers = signin(platform, "admin")
    source = platform.post("/api/v2/connections", headers=headers, json={"name": "Companion test stream", "patient_id": "SIM-COMPANION", "source_type": "synthetic"}).json()["data"]
    headers = signin(platform, "patient")
    assert platform.post("/api/v2/patient/consents", headers=headers, json={"action": "withdraw", "purpose": "research_collection", "connection_id": source["id"]}).status_code == 200
    with connection() as db:
        row = db.execute("SELECT status,connection_key_hash FROM source_connections WHERE id=?", (source["id"],)).fetchone()
        assert row[0] == "revoked" and row[1] is None
    assert platform.post("/api/v2/connections/" + source["id"] + "/observations", headers={"X-Connection-Key": source["connection_key"]}, json={"event_id": "revoked", "timestamp": utc_iso(), "glucose_mg_dl": 140}).status_code == 401


def utc_iso():
    return datetime.now(timezone.utc).isoformat()
