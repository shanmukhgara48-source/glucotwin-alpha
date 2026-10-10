"""Opaque, revocable bearer sessions and salted password hashes for local clinic access."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.storage import ROOT, audit, connection, utc_now

router = APIRouter()
SESSION_HOURS = 8


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
    credentials = []
    with connection() as db:
        for user_id, name, role in [("admin", "Clinic administrator", "admin"), ("reviewer", "Demo clinician", "reviewer")]:
            if db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
                continue
            password = os.environ.get(f"GLUCOTWIN_{role.upper()}_PASSWORD") or secrets.token_urlsafe(18)
            if len(password) < 12:
                raise RuntimeError(f"GLUCOTWIN_{role.upper()}_PASSWORD must contain at least 12 characters")
            db.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", (user_id, user_id, name, password_hash(password), role, "demo-clinic"))
            credentials.append({"username": user_id, "password": password, "role": role})
    if credentials:
        target = Path(os.environ.get("GLUCOTWIN_CREDENTIALS_PATH", ROOT / ".run" / "clinic-credentials.json"))
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(target, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump({"local_only": True, "accounts": credentials}, handle, indent=2)


def public_user(row) -> dict:
    return {key: row[key] for key in ("id", "username", "name", "role", "clinic_id")}


def current_user(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Sign in to access clinic records.")
    token_hash = hashlib.sha256(header[7:].encode()).hexdigest()
    with connection() as db:
        row = db.execute("SELECT users.*,sessions.expires_at FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=?",
                         (token_hash,)).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(401, "Session expired or invalid. Sign in again.")
        return public_user(row)


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "An administrator account is required.")
    return user


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


@router.post("/api/auth/login")
def login(payload: Login):
    bootstrap()
    with connection() as db:
        row = db.execute("SELECT * FROM users WHERE username=?", (payload.username,)).fetchone()
        if row is None or not password_valid(payload.password, row["password_hash"]):
            raise HTTPException(401, "Invalid username or password.")
        user = public_user(row)
        token = secrets.token_urlsafe(40)
        expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat()
        db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["id"], expires, utc_now()))
        audit(db, user, "session.created", user["id"])
        return {"success": True, "data": {"token": token, "user": user, "expires_at": expires}}


@router.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {"success": True, "data": user}


@router.post("/api/auth/logout")
def logout(request: Request, user: dict = Depends(current_user)):
    with connection() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(request.headers["authorization"][7:].encode()).hexdigest(),))
        audit(db, user, "session.revoked", user["id"])
    return {"success": True, "data": {"signed_out": True}}
