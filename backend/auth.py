"""Opaque, revocable bearer sessions and salted password hashes for local clinic access."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.storage import ROOT, audit, connection, utc_now
from backend.identity import active, decrypt, digest, encrypt, initialize_identity, valid_totp

router = APIRouter()
SESSION_HOURS = 8
COOKIE = "glucotwin_session"
CSRF_COOKIE = "glucotwin_csrf"
IDLE_MINUTES = 30


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 260_000).hex()
    return f"pbkdf2_sha256$260000${salt}${digest}"


def password_valid(password: str, encoded: str) -> bool:
    try:
        return hmac.compare_digest(password_hash(password, encoded.split("$")[2]), encoded)
    except (ValueError, IndexError):
        return False


def bootstrap():
    initialize_identity()
    credentials = []
    with connection() as db:
        for user_id, name, role in [("admin", "Clinic administrator", "admin"), ("reviewer", "Demo clinician", "reviewer"), ("clinician", "Demo physician", "clinician"), ("coordinator", "Care coordinator", "coordinator"), ("patient", "Synthetic patient", "patient")]:
            if db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
                continue
            password = os.environ.get(f"GLUCOTWIN_{role.upper()}_PASSWORD") or secrets.token_urlsafe(18)
            if len(password) < 12:
                raise RuntimeError(f"GLUCOTWIN_{role.upper()}_PASSWORD must contain at least 12 characters")
            db.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", (user_id, user_id, name, password_hash(password), role, "demo-clinic"))
            if role == "patient":
                db.execute("INSERT OR IGNORE INTO platform_bindings VALUES(?,?,?)", (user_id, "demo-clinic", "SIM-COMPANION"))
            credentials.append({"username": user_id, "password": password, "role": role})
    if credentials:
        target = Path(os.environ.get("GLUCOTWIN_CREDENTIALS_PATH", ROOT / ".run" / "clinic-credentials.json"))
        target.parent.mkdir(parents=True, exist_ok=True)
        # Preserve previously generated private accounts when upgrading an existing installation.
        existing = json.loads(target.read_text()).get("accounts", []) if target.exists() else []
        accounts = {item["username"]: item for item in existing + credentials}
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(target, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump({"local_only": True, "accounts": list(accounts.values())}, handle, indent=2)


def public_user(row) -> dict:
    return {key: row[key] for key in ("id", "username", "name", "role", "clinic_id")}


def current_user(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    cookie_session = not header.startswith("Bearer ")
    token = request.cookies.get(COOKIE, "") if cookie_session else header[7:]
    if not token:
        raise HTTPException(401, "Sign in to access clinic records.")
    token_hash = digest(token)
    with connection() as db:
        row = db.execute("SELECT users.*,sessions.expires_at FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=?",
                         (token_hash,)).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc) or not active(db, row["id"]):
            raise HTTPException(401, "Session expired or invalid. Sign in again.")
        mfa = db.execute("SELECT enabled FROM auth_mfa WHERE user_id=?", (row["id"],)).fetchone()
        verified = db.execute("SELECT mfa_verified FROM auth_session_meta WHERE token_hash=?", (token_hash,)).fetchone()
        if mfa and mfa[0] and (verified is None or not verified[0]):
            raise HTTPException(401, "Sign in again with your verification code.")
        if cookie_session:
            meta = db.execute("SELECT * FROM auth_session_meta WHERE token_hash=?", (token_hash,)).fetchone()
            if meta is None or datetime.fromisoformat(meta["last_seen"]) < datetime.now(timezone.utc) - timedelta(minutes=IDLE_MINUTES):
                raise HTTPException(401, "Your workspace session expired. Sign in again.")
            csrf = request.cookies.get(CSRF_COOKIE, "")
            if request.method not in ("GET", "HEAD", "OPTIONS") and (not csrf or not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), csrf) or not hmac.compare_digest(digest(csrf), meta["csrf_hash"])):
                raise HTTPException(403, "The request needs a valid workspace CSRF token.")
            db.execute("UPDATE auth_session_meta SET last_seen=? WHERE token_hash=?", (utc_now(), token_hash))
        user = public_user(row)
        bound = db.execute("SELECT patient_id FROM platform_bindings WHERE user_id=? AND clinic_id=?", (user["id"], user["clinic_id"])).fetchone()
        if bound:
            user["patient_id"] = bound[0]
        return user


def clinic_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] not in {"admin", "reviewer", "clinician", "coordinator"}:
        raise HTTPException(403, "A care-team account is required.")
    return user


def connection_actor(connection_id: str, request: Request) -> dict:
    key = request.headers.get("X-Connection-Key")
    with connection() as db:
        source = db.execute("SELECT * FROM source_connections WHERE id=?", (connection_id,)).fetchone()
        if source is None:
            raise HTTPException(404, "Connection not found.")
        if key:
            if not source["connection_key_hash"] or not hmac.compare_digest(digest(key), source["connection_key_hash"]) or source["status"] in {"revoked", "pending", "access_revoked"}:
                raise HTTPException(401, "Connection authorization is invalid or inactive.")
            return {"id": "connector:" + connection_id, "username": connection_id, "name": source["name"], "role": "connector", "clinic_id": source["clinic_id"], "patient_id": source["patient_id"], "connection_id": connection_id}
    user = current_user(request)
    if user["clinic_id"] != source["clinic_id"] or user["role"] != "admin" or source["source_type"] != "synthetic":
        raise HTTPException(403, "A scoped connection credential is required.")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "An administrator account is required.")
    return user


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)
    otp: str | None = Field(default=None, max_length=6)


def check_login(payload: Login, request: Request | None = None) -> dict:
    bootstrap()
    identity = digest(payload.username.lower() + ":" + (request.client.host if request and request.client else "local"))
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    with connection() as db:
        if db.execute("SELECT COUNT(*) FROM auth_attempts WHERE identity=? AND attempted_at>?", (identity, cutoff)).fetchone()[0] >= 5:
            raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.")
        row = db.execute("SELECT * FROM users WHERE username=?", (payload.username,)).fetchone()
        valid = row is not None and active(db, row["id"]) and password_valid(payload.password, row["password_hash"])
        mfa = db.execute("SELECT * FROM auth_mfa WHERE user_id=?", (row["id"],)).fetchone() if row else None
        if valid and mfa and mfa["enabled"]:
            valid = payload.otp is not None and valid_totp(decrypt(mfa["encrypted_secret"]), payload.otp)
        if not valid:
            db.execute("INSERT INTO auth_attempts(identity,attempted_at) VALUES(?,?)", (identity, utc_now()))
        else:
            db.execute("DELETE FROM auth_attempts WHERE identity=?", (identity,))
            user = public_user(row)
            binding = db.execute("SELECT patient_id FROM platform_bindings WHERE user_id=?", (row["id"],)).fetchone()
            if binding:
                user["patient_id"] = binding[0]
    if not valid:
        raise HTTPException(401, "Invalid credentials or verification code.")
    return user


@router.post("/api/auth/login")
def login(payload: Login, request: Request):
    user = check_login(payload, request)
    with connection() as db:
        token = secrets.token_urlsafe(40)
        expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat()
        db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["id"], expires, utc_now()))
        db.execute("INSERT INTO auth_session_meta VALUES(?,?,?,?)", (digest(token), "", utc_now(), int(payload.otp is not None)))
        audit(db, user, "session.created", user["id"])
        return {"success": True, "data": {"token": token, "user": user, "expires_at": expires}}


@router.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {"success": True, "data": user}


@router.post("/api/auth/logout")
def logout(request: Request, user: dict = Depends(current_user)):
    with connection() as db:
        token = request.headers.get("authorization", "")[7:] or request.cookies.get(COOKIE, "")
        db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(token),))
        audit(db, user, "session.revoked", user["id"])
    return {"success": True, "data": {"signed_out": True}}


@router.post("/api/v2/auth/login")
def cookie_login(payload: Login, request: Request, response: Response):
    user = check_login(payload, request)
    token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat()
    with connection() as db:
        db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (digest(token), user["id"], expires, utc_now()))
        db.execute("INSERT INTO auth_session_meta VALUES(?,?,?,?)", (digest(token), digest(csrf), utc_now(), int(payload.otp is not None)))
        audit(db, user, "session.cookie_created", user["id"])
    secure = os.environ.get("GLUCOTWIN_COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True, secure=secure, samesite="strict", path="/api")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=SESSION_HOURS * 3600, httponly=True, secure=secure, samesite="strict", path="/api")
    response.headers["Cache-Control"] = "no-store"
    return {"success": True, "data": {"user": user, "expires_at": expires, "csrf_token": csrf}}


@router.get("/api/v2/auth/me")
def cookie_me(request: Request, user: dict = Depends(current_user)):
    return {"success": True, "data": {"user": user, "csrf_token": request.cookies.get(CSRF_COOKIE), "session_hours": SESSION_HOURS, "idle_minutes": IDLE_MINUTES}}


@router.post("/api/v2/auth/logout")
def cookie_logout(request: Request, response: Response, user: dict = Depends(current_user)):
    logout(request, user)
    response.delete_cookie(COOKIE, path="/api")
    response.delete_cookie(CSRF_COOKIE, path="/api")
    return {"success": True, "data": {"signed_out": True}}


@router.post("/api/v2/auth/mfa/setup")
def setup_mfa(user: dict = Depends(clinic_user)):
    import base64
    from urllib.parse import quote
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    with connection() as db:
        existing = db.execute("SELECT enabled FROM auth_mfa WHERE user_id=?", (user["id"],)).fetchone()
        if existing and existing[0]:
            raise HTTPException(409, "MFA is already enabled. Administrative recovery is required to change it.")
        db.execute("INSERT INTO auth_mfa VALUES(?,?,0) ON CONFLICT(user_id) DO UPDATE SET encrypted_secret=excluded.encrypted_secret", (user["id"], encrypt(secret)))
        audit(db, user, "mfa.setup_started", user["id"])
    return {"success": True, "data": {"secret": secret, "uri": f"otpauth://totp/GlucoTwin:{quote(user['username'])}?secret={secret}&issuer=GlucoTwin", "enabled": False}}


class VerifyMFA(BaseModel):
    otp: str = Field(min_length=6, max_length=6)


@router.post("/api/v2/auth/mfa/confirm")
def confirm_mfa(payload: VerifyMFA, request: Request, user: dict = Depends(clinic_user)):
    with connection() as db:
        row = db.execute("SELECT * FROM auth_mfa WHERE user_id=?", (user["id"],)).fetchone()
        if row is None or not valid_totp(decrypt(row["encrypted_secret"]), payload.otp):
            raise HTTPException(422, "The verification code is invalid.")
        db.execute("UPDATE auth_mfa SET enabled=1 WHERE user_id=?", (user["id"],))
        header = request.headers.get("authorization", "")
        token = header[7:] if header.startswith("Bearer ") else request.cookies.get(COOKIE, "")
        token_hash = digest(token)
        db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash!=?", (user["id"], token_hash))
        db.execute("UPDATE auth_session_meta SET mfa_verified=1 WHERE token_hash=?", (token_hash,))
        audit(db, user, "mfa.enabled", user["id"])
    return {"success": True, "data": {"enabled": True}}
