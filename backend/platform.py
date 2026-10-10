"""Care-team administration and an own-record patient companion. Research data only."""
from __future__ import annotations

import csv
import io
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from backend.auth import admin_user, clinic_user, current_user, password_hash, public_user
from backend.identity import digest, initialize_identity
from backend.storage import audit, connection, utc_now

router = APIRouter(prefix="/api/v2")


def result(data):
    return {"success": True, "data": data}


def initialize_platform():
    initialize_identity()
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS platform_consents(id INTEGER PRIMARY KEY,clinic_id TEXT NOT NULL,patient_id TEXT NOT NULL,actor_id TEXT NOT NULL,action TEXT NOT NULL,purpose TEXT NOT NULL,connection_id TEXT,recorded_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS platform_tasks(id INTEGER PRIMARY KEY,clinic_id TEXT NOT NULL,patient_id TEXT NOT NULL,title TEXT NOT NULL,instructions TEXT NOT NULL,due_at TEXT,published INTEGER NOT NULL,created_by TEXT NOT NULL,created_at TEXT NOT NULL,completed_at TEXT);
        CREATE TRIGGER IF NOT EXISTS consents_no_update BEFORE UPDATE ON platform_consents BEGIN SELECT RAISE(ABORT,'Consent history is append only'); END;
        CREATE TRIGGER IF NOT EXISTS consents_no_delete BEFORE DELETE ON platform_consents BEGIN SELECT RAISE(ABORT,'Consent history is append only'); END;
        """)
        # This companion is a separate fictional identity, never a matched Shanghai participant.
        profile = {"id": "SIM-COMPANION", "name": "Synthetic companion", "source": "synthetic", "timezone": "Asia/Kolkata", "recording_id": "SIM-COMPANION-stream", "provenance": "Fully synthetic companion demonstration; excluded from measured benchmarks."}
        db.execute("INSERT OR IGNORE INTO profiles VALUES(?,?,?)", ("demo-clinic", profile["id"], json.dumps(profile)))
        if not db.execute("SELECT 1 FROM observations WHERE clinic_id=? AND patient_id=? LIMIT 1", ("demo-clinic", profile["id"])).fetchone():
            now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            for index, glucose in enumerate([121, 124, 130, 137, 133, 128, 126, 129]):
                stamp = (now - timedelta(minutes=(7 - index) * 15 + 1)).isoformat()
                db.execute("INSERT INTO observations(clinic_id,patient_id,timestamp,available_at,glucose_mg_dl,source) VALUES(?,?,?,?,?,?)", ("demo-clinic", profile["id"], stamp, stamp, glucose, "simulated"))
        if not db.execute("SELECT 1 FROM platform_tasks WHERE patient_id=? LIMIT 1", (profile["id"],)).fetchone():
            db.execute("INSERT INTO platform_tasks(clinic_id,patient_id,title,instructions,due_at,published,created_by,created_at) VALUES(?,?,?,?,?,1,?,?)", ("demo-clinic", profile["id"], "Prepare for the demonstration consultation", "Synthetic example: add a meal or activity note so the reviewer can inspect its provenance.", None, "reviewer", utc_now()))


def bound_patient(user: dict) -> str:
    if user["role"] != "patient" or not user.get("patient_id"):
        raise HTTPException(403, "A patient account bound to its own record is required.")
    return user["patient_id"]


def patient_exists(db, user: dict, patient_id: str):
    row = db.execute("SELECT profile_json FROM profiles WHERE clinic_id=? AND patient_id=?", (user["clinic_id"], patient_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Patient not found in this clinic.")
    return json.loads(row[0])


class Enroll(BaseModel):
    patient_id: str = Field(pattern=r"^SIM-[A-Za-z0-9_-]{1,58}$")
    label: str = Field(default="Synthetic research patient", min_length=1, max_length=80)
    timezone: str = "Asia/Kolkata"


@router.post("/platform/enroll")
def enroll(payload: Enroll, user: dict = Depends(admin_user)):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Use a valid IANA timezone.")
    profile = {"id": payload.patient_id, "name": payload.label, "source": "synthetic", "timezone": payload.timezone, "recording_id": payload.patient_id + "-stream", "provenance": "Synthetic enrollment only. Private clinical enrollment is gated pending an authorized source and approvals."}
    with connection() as db:
        if db.execute("SELECT 1 FROM profiles WHERE clinic_id=? AND patient_id=?", (user["clinic_id"], payload.patient_id)).fetchone():
            raise HTTPException(409, "That patient is already enrolled.")
        db.execute("INSERT INTO profiles VALUES(?,?,?)", (user["clinic_id"], payload.patient_id, json.dumps(profile)))
        audit(db, user, "patient.synthetic_enrolled", payload.patient_id)
    return result({"patient": profile, "clinical_gate": "pending"})


@router.get("/platform/patients")
def patients(user: dict = Depends(clinic_user)):
    with connection() as db:
        items = [json.loads(row[0]) for row in db.execute("SELECT profile_json FROM profiles WHERE clinic_id=? ORDER BY patient_id", (user["clinic_id"],))]
    return result({"items": items})


@router.get("/platform/staff")
def staff(user: dict = Depends(admin_user)):
    with connection() as db:
        items = []
        for row in db.execute("SELECT users.*,COALESCE(platform_user_state.active,1) active FROM users LEFT JOIN platform_user_state ON users.id=platform_user_state.user_id WHERE clinic_id=? ORDER BY username", (user["clinic_id"],)):
            item = {**public_user(row), "active": bool(row["active"])}
            bound = db.execute("SELECT patient_id FROM platform_bindings WHERE user_id=?", (row["id"],)).fetchone()
            if bound:
                item["patient_id"] = bound[0]
            mfa = db.execute("SELECT enabled FROM auth_mfa WHERE user_id=?", (row["id"],)).fetchone()
            item["mfa_enabled"] = bool(mfa and mfa[0])
            items.append(item)
    return result({"items": items})


class Invite(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9._-]{3,64}$")
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(pattern=r"^(clinician|coordinator|patient)$")
    patient_id: str | None = None


@router.post("/platform/staff")
def invite(payload: Invite, user: dict = Depends(admin_user)):
    identifier, code = secrets.token_hex(12), secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    with connection() as db:
        if db.execute("SELECT 1 FROM users WHERE username=?", (payload.username,)).fetchone():
            raise HTTPException(409, "That username is already in use.")
        if payload.role == "patient":
            if not payload.patient_id:
                raise HTTPException(422, "Patient accounts require a clinic-bound patient record.")
            patient_exists(db, user, payload.patient_id)
        db.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", (identifier, payload.username, payload.name, password_hash(secrets.token_urlsafe(32)), payload.role, user["clinic_id"]))
        db.execute("INSERT INTO platform_user_state VALUES(?,0,?)", (identifier, utc_now()))
        db.execute("INSERT INTO platform_invites VALUES(?,?,?,NULL)", (digest(code), identifier, expires))
        if payload.role == "patient":
            db.execute("INSERT INTO platform_bindings VALUES(?,?,?)", (identifier, user["clinic_id"], payload.patient_id))
        audit(db, user, "account.invited", identifier, {"role": payload.role})
    return result({"user": {"id": identifier, "username": payload.username, "name": payload.name, "role": payload.role, "clinic_id": user["clinic_id"], "active": False}, "invitation_code": code, "expires_at": expires, "delivery": "Private manual handover; no message was sent."})


class Activate(BaseModel):
    invitation_code: str = Field(min_length=16, max_length=120)
    password: str = Field(min_length=12, max_length=200)


@router.post("/auth/activate")
def activate(payload: Activate):
    with connection() as db:
        # Serialize the read/use transition so two activations cannot consume one invitation.
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM platform_invites WHERE token_hash=?", (digest(payload.invitation_code),)).fetchone()
        if row is None or row["used_at"] or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(422, "The invitation is invalid, expired, or already used.")
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(payload.password), row["user_id"]))
        db.execute("UPDATE platform_user_state SET active=1 WHERE user_id=?", (row["user_id"],))
        db.execute("UPDATE platform_invites SET used_at=? WHERE token_hash=?", (utc_now(), digest(payload.invitation_code)))
        actor = public_user(db.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone())
        audit(db, actor, "account.activated", actor["id"])
    return result({"activated": True})


@router.post("/platform/staff/{user_id}/deactivate")
def deactivate(user_id: str, user: dict = Depends(admin_user)):
    if user_id == user["id"]:
        raise HTTPException(409, "Keep the active administrator account available.")
    with connection() as db:
        if not db.execute("SELECT 1 FROM users WHERE id=? AND clinic_id=?", (user_id, user["clinic_id"])).fetchone():
            raise HTTPException(404, "Account not found in this clinic.")
        db.execute("INSERT INTO platform_user_state VALUES(?,0,?) ON CONFLICT(user_id) DO UPDATE SET active=0", (user_id, utc_now()))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit(db, user, "account.deactivated", user_id)
    return result({"deactivated": True, "sessions_revoked": True})


@router.get("/patient/me")
def patient_me(user: dict = Depends(current_user)):
    from backend.clinic import monitoring
    identifier = bound_patient(user)
    now = utc_now()
    with connection() as db:
        profile = patient_exists(db, user, identifier)
        observations = [dict(row) for row in db.execute("SELECT timestamp,available_at,glucose_mg_dl,source FROM observations WHERE clinic_id=? AND patient_id=? AND available_at<=? ORDER BY timestamp DESC LIMIT 240", (user["clinic_id"], identifier, now))]
        contexts = [{**dict(row), "value": json.loads(row["value_json"])} for row in db.execute("SELECT * FROM context WHERE clinic_id=? AND patient_id=? AND available_at<=? ORDER BY observed_at DESC LIMIT 100", (user["clinic_id"], identifier, now)) if row["provenance"] in {"self_reported", "clinician_approved"}]
        tasks = [dict(row) for row in db.execute("SELECT * FROM platform_tasks WHERE clinic_id=? AND patient_id=? AND published=1 ORDER BY created_at DESC", (user["clinic_id"], identifier))]
        consents = [dict(row) for row in db.execute("SELECT * FROM platform_consents WHERE clinic_id=? AND patient_id=? ORDER BY id DESC", (user["clinic_id"], identifier))]
        sources = [dict(row) for row in db.execute("SELECT id,name,status,source_type,cadence_minutes,source_timezone FROM source_connections WHERE clinic_id=? AND patient_id=?", (user["clinic_id"], identifier))]
    return result({"patient": profile, "observations": list(reversed(observations)), "contexts": contexts, "tasks": tasks, "consents": consents, "connections": sources, "monitoring": monitoring(user), "source_status": "synthetic" if profile.get("source") == "synthetic" else "clinic_connection_pending", "clinical_gate": "pending", "predictions_enabled": False})


class PatientContext(BaseModel):
    kind: str = Field(pattern=r"^(meal|activity|symptom)$")
    value: str = Field(min_length=1, max_length=2000)
    observed_at: str


@router.post("/patient/context")
def patient_context(payload: PatientContext, user: dict = Depends(current_user)):
    from backend.clinic import iso_time, time_key
    identifier = bound_patient(user)
    observed, arrived = iso_time(payload.observed_at), utc_now()
    if time_key(observed) > time_key(arrived):
        raise HTTPException(422, "Context cannot be dated in the future.")
    with connection() as db:
        patient_exists(db, user, identifier)
        cursor = db.execute("INSERT INTO context(clinic_id,patient_id,kind,value_json,observed_at,available_at,provenance,created_by) VALUES(?,?,?,?,?,?,?,?)", (user["clinic_id"], identifier, payload.kind, json.dumps(payload.value), observed, arrived, "self_reported", user["id"]))
        audit(db, user, "patient.context_added", identifier, {"kind": payload.kind})
    return result({"id": cursor.lastrowid, "provenance": "self_reported", "available_at": arrived})


class Consent(BaseModel):
    action: str = Field(pattern=r"^(grant|withdraw)$")
    purpose: str = Field(pattern=r"^research_collection$")
    connection_id: str | None = None


@router.post("/patient/consents")
def patient_consent(payload: Consent, user: dict = Depends(current_user)):
    identifier = bound_patient(user)
    with connection() as db:
        patient_exists(db, user, identifier)
        if payload.connection_id:
            source = db.execute("SELECT id FROM source_connections WHERE id=? AND clinic_id=? AND patient_id=?", (payload.connection_id, user["clinic_id"], identifier)).fetchone()
            if source is None:
                raise HTTPException(404, "Connection not found for this patient.")
        db.execute("INSERT INTO platform_consents(clinic_id,patient_id,actor_id,action,purpose,connection_id,recorded_at) VALUES(?,?,?,?,?,?,?)", (user["clinic_id"], identifier, user["id"], payload.action, payload.purpose, payload.connection_id, utc_now()))
        if payload.action == "withdraw":
            if payload.connection_id:
                db.execute("UPDATE source_connections SET status='revoked',connection_key_hash=NULL WHERE id=?", (payload.connection_id,))
            else:
                db.execute("UPDATE source_connections SET status='revoked',connection_key_hash=NULL WHERE clinic_id=? AND patient_id=?", (user["clinic_id"], identifier))
        audit(db, user, "consent." + payload.action, identifier, {"purpose": payload.purpose})
    return result({"recorded": True, "action": payload.action, "clinical_gate": "pending", "message": "Consent records do not activate clinical monitoring or override outstanding approvals."})


class Task(BaseModel):
    patient_id: str
    title: str = Field(min_length=1, max_length=160)
    instructions: str = Field(min_length=1, max_length=4000)
    due_at: str | None = None
    published: bool = True


class SharedNote(BaseModel):
    patient_id: str
    note: str = Field(min_length=1, max_length=4000)


@router.post("/platform/shared-notes")
def share_note(payload: SharedNote, user: dict = Depends(clinic_user)):
    if user["role"] not in {"admin", "clinician", "reviewer"}:
        raise HTTPException(403, "A clinician must approve patient-visible notes.")
    stamp = utc_now()
    with connection() as db:
        patient_exists(db, user, payload.patient_id)
        cursor = db.execute("INSERT INTO context(clinic_id,patient_id,kind,value_json,observed_at,available_at,provenance,created_by,received_at) VALUES(?,?,?,?,?,?,?,?,?)", (user["clinic_id"], payload.patient_id, "shared_note", json.dumps(payload.note), stamp, stamp, "clinician_approved", user["id"], stamp))
        audit(db, user, "care_note.approved_for_patient", str(cursor.lastrowid))
    return result({"id": cursor.lastrowid, "provenance": "clinician_approved"})


@router.post("/platform/tasks")
def publish_task(payload: Task, user: dict = Depends(clinic_user)):
    from backend.clinic import iso_time
    if user["role"] not in {"admin", "clinician", "reviewer"}:
        raise HTTPException(403, "A clinician must publish patient follow-up instructions.")
    due = iso_time(payload.due_at) if payload.due_at else None
    with connection() as db:
        patient_exists(db, user, payload.patient_id)
        cursor = db.execute("INSERT INTO platform_tasks(clinic_id,patient_id,title,instructions,due_at,published,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)", (user["clinic_id"], payload.patient_id, payload.title, payload.instructions, due, int(payload.published), user["id"], utc_now()))
        audit(db, user, "care_task.published" if payload.published else "care_task.drafted", payload.patient_id)
    return result({"id": cursor.lastrowid, "published": payload.published})


@router.post("/patient/tasks/{task_id}/complete")
def complete_task(task_id: int, user: dict = Depends(current_user)):
    identifier = bound_patient(user)
    with connection() as db:
        row = db.execute("SELECT id FROM platform_tasks WHERE id=? AND clinic_id=? AND patient_id=? AND published=1", (task_id, user["clinic_id"], identifier)).fetchone()
        if row is None:
            raise HTTPException(404, "Published task not found for this patient.")
        db.execute("UPDATE platform_tasks SET completed_at=COALESCE(completed_at,?) WHERE id=?", (utc_now(), task_id))
        audit(db, user, "care_task.completed", str(task_id))
    return result({"completed": True})


@router.get("/patient/report")
def patient_report(user: dict = Depends(current_user)):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    import html
    data = patient_me(user)["data"]
    stream = io.BytesIO()
    doc = SimpleDocTemplate(stream, title="Patient companion summary", leftMargin=44, rightMargin=44)
    styles = getSampleStyleSheet()
    story = [Paragraph("GlucoTwin - patient companion summary", styles["Title"]), Paragraph("Synthetic research companion. Clinic connection and clinical approvals pending.", styles["BodyText"]), Spacer(1, 16)]
    if data["observations"]:
        row = data["observations"][-1]
        story.append(Paragraph(f"Latest recorded reading: {row['glucose_mg_dl']:.1f} mg/dL at {html.escape(row['timestamp'])}. Source: {html.escape(row['source'])}.", styles["BodyText"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Published follow-up", styles["Heading2"]))
    for task in data["tasks"]:
        story.append(Paragraph(html.escape(task["title"]), styles["Heading3"]))
        story.append(Paragraph(html.escape(task["instructions"]), styles["BodyText"]))
    story.append(Paragraph("Patient-visible context and approved notes", styles["Heading2"]))
    for entry in data["contexts"][:12]:
        story.append(Paragraph(html.escape(f"{entry['observed_at']} - {entry['kind']} ({entry['provenance']}): {entry['value']}"), styles["BodyText"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("This export contains patient-visible context and published follow-up. Model forecasts and private clinician notes are not included.", styles["BodyText"]))
    doc.build(story)
    return Response(stream.getvalue(), media_type="application/pdf", headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="GlucoTwin_Patient_Summary.pdf"'})


@router.get("/platform/gates")
def gates(user: dict = Depends(clinic_user)):
    return result({"environment": "research", "clinic_connection": "pending", "clinical_release": "disabled", "required": [{"name": name, "status": "pending"} for name in ["Authorized clinic and device source", "Device cadence, timezone and latency verification", "Clinician workflow and operating-point review", "Privacy, intended-use and applicable approvals", "Approved prospective shadow protocol", "Always-on encrypted deployment and off-host recovery"]], "measured_evidence": "Internal retrospective validation only", "live_patient_data_enabled": False})


@router.get("/platform/audit")
def audit_log(user: dict = Depends(admin_user)):
    with connection() as db:
        items = [dict(row) for row in db.execute("SELECT id,actor_id,event,resource,recorded_at FROM audit WHERE clinic_id=? ORDER BY id DESC LIMIT 200", (user["clinic_id"],))]
    return result({"items": items})


class Preview(BaseModel):
    csv: str = Field(max_length=2_000_000)


@router.post("/platform/intake/preview")
def preview(payload: Preview, user: dict = Depends(admin_user)):
    from backend.clinic import Observation, validate_observation
    try:
        reader = csv.DictReader(io.StringIO(payload.csv))
        required = {"patient_id", "timestamp", "glucose_mg_dl", "available_at", "source"}
        if set(reader.fieldnames or []) != required:
            raise HTTPException(422, "Use only the required patient, timestamp, glucose, availability and source columns.")
        rows, accepted, seen = [], 0, {}
        for index, row in enumerate(reader, start=2):
            message, state = "Valid synthetic observation", "valid"
            try:
                observed, arrived = validate_observation(row["patient_id"], Observation(timestamp=row["timestamp"], available_at=row["available_at"], glucose_mg_dl=float(row["glucose_mg_dl"]), source=row["source"]))
                key = (row["patient_id"], observed)
                fingerprint = (float(row["glucose_mg_dl"]), arrived, row["source"])
                if key in seen and seen[key] != fingerprint:
                    raise ValueError("Conflicting duplicate in this file")
                if key in seen:
                    state, message = "duplicate", "Identical duplicate; import is idempotent"
                with connection() as db:
                    old = db.execute("SELECT glucose_mg_dl,available_at,source FROM observations WHERE clinic_id=? AND patient_id=? AND timestamp=?", (user["clinic_id"], row["patient_id"], observed)).fetchone()
                if old and (float(old[0]), old[1], old[2]) != fingerprint:
                    raise ValueError("Conflicts with an accepted observation")
                if old:
                    state, message = "duplicate", "Already present; import is idempotent"
                seen[key] = fingerprint
                accepted += 1
            except (ValueError, HTTPException) as error:
                state, message = "invalid", str(error.detail if isinstance(error, HTTPException) else error)
            rows.append({"row": index, "patient_id": row.get("patient_id"), "timestamp": row.get("timestamp"), "status": state, "message": message})
            if index > 5001:
                raise HTTPException(422, "Preview is limited to 5,000 rows.")
    except csv.Error:
        raise HTTPException(422, "The CSV could not be parsed.")
    return result({"rows": rows, "valid_count": accepted, "invalid_count": len(rows) - accepted, "can_import": bool(rows) and accepted == len(rows), "committed": False})
