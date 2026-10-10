"""Encrypted, verified SQLite recovery; restore always targets a new offline database."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cryptography.fernet import Fernet
from backend.identity import encryption_key
from scripts.backup_restore import backup, verify


def seal(database: Path, destination: Path) -> dict:
    if destination.exists():
        raise ValueError("Destination exists; preserve the earlier backup.")
    with tempfile.TemporaryDirectory(prefix="glucotwin-backup-") as folder:
        snapshot = Path(folder) / "database.sqlite3"
        details = backup(database, snapshot)
        payload = snapshot.read_bytes()
    manifest = {"format": "glucotwin-sqlite-v1", "schema_version": details["schema_version"],
                "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps(manifest))
        package.writestr("database.sqlite3", payload)
    encrypted = Fernet(encryption_key()).encrypt(archive.getvalue())
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(encrypted)
    return {"encrypted": True, "schema_version": details["schema_version"],
            "ciphertext_bytes": len(encrypted), "off_host_copy_verified": False}


def unseal(source: Path, destination: Path, offline: bool = False) -> dict:
    if not offline:
        raise ValueError("Stop all writers and confirm --offline before restoring.")
    if destination.exists():
        raise ValueError("Restore targets must be new; the existing database is preserved.")
    archive = Fernet(encryption_key()).decrypt(source.read_bytes())
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        if set(package.namelist()) != {"manifest.json", "database.sqlite3"}:
            raise ValueError("Unexpected backup contents.")
        manifest = json.loads(package.read("manifest.json"))
        payload = package.read("database.sqlite3")
    if manifest.get("format") != "glucotwin-sqlite-v1" or hashlib.sha256(payload).hexdigest() != manifest.get("sha256"):
        raise ValueError("Backup manifest verification failed.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="glucotwin-restore-") as folder:
        candidate = Path(folder) / "candidate.sqlite3"
        candidate.write_bytes(payload)
        details = verify(candidate)
        result = backup(candidate, destination)
    return {"integrity": result["integrity"], "schema_version": details["schema_version"],
            "sha256_verified": True, "existing_database_overwritten": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    result = seal(args.database, args.file) if args.operation == "backup" else unseal(args.file, args.database, args.offline)
    print(json.dumps({"success": True, "data": result}, indent=2))
