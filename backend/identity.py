"""Local identity lifecycle, cookie-session metadata and encrypted MFA secrets."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from pathlib import Path

from cryptography.fernet import Fernet

from backend.storage import ROOT, connection


def initialize_identity():
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS platform_user_state(user_id TEXT PRIMARY KEY REFERENCES users(id),active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS platform_bindings(user_id TEXT PRIMARY KEY REFERENCES users(id),clinic_id TEXT NOT NULL,patient_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS platform_invites(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires_at TEXT NOT NULL,used_at TEXT);
        CREATE TABLE IF NOT EXISTS auth_session_meta(token_hash TEXT PRIMARY KEY REFERENCES sessions(token_hash) ON DELETE CASCADE,csrf_hash TEXT NOT NULL,last_seen TEXT NOT NULL,mfa_verified INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS auth_attempts(id INTEGER PRIMARY KEY,identity TEXT NOT NULL,attempted_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS auth_attempt_lookup ON auth_attempts(identity,attempted_at);
        CREATE TABLE IF NOT EXISTS auth_mfa(user_id TEXT PRIMARY KEY REFERENCES users(id),encrypted_secret TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0);
        """)


def encryption_key() -> bytes:
    configured = os.environ.get("GLUCOTWIN_ENCRYPTION_KEY")
    if configured:
        key = configured.encode()
        Fernet(key)
        return key
    if os.environ.get("GLUCOTWIN_ENV", "research") != "research":
        raise RuntimeError("An explicit encryption key is required outside the local research environment.")
    path = Path(os.environ.get("GLUCOTWIN_KEY_PATH", ROOT / ".run" / "encryption.key"))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_bytes().strip()
    key = Fernet.generate_key()
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    return key


def encrypt(value: str) -> str:
    return Fernet(encryption_key()).encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return Fernet(encryption_key()).decrypt(value.encode()).decode()


def totp(secret: str, at: float | None = None) -> str:
    counter = int((time.time() if at is None else at) // 30)
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def valid_totp(secret: str, code: str) -> bool:
    now = time.time()
    return len(code) == 6 and code.isdigit() and any(hmac.compare_digest(totp(secret, now + delta), code) for delta in (-30, 0, 30))


def active(db, user_id: str) -> bool:
    row = db.execute("SELECT active FROM platform_user_state WHERE user_id=?", (user_id,)).fetchone()
    return row is None or bool(row[0])


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
