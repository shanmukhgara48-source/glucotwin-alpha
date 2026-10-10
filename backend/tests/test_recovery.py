import hashlib
import sqlite3

import pytest
from cryptography.fernet import Fernet, InvalidToken
from scripts.encrypted_backup import seal, unseal
from scripts.model_release import select_model


def test_encrypted_recovery_preserves_records_and_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("GLUCOTWIN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    source, sealed, restored = [tmp_path / name for name in ("source.sqlite3", "backup.gtbackup", "restore.sqlite3")]
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE reviews(id INTEGER PRIMARY KEY,note TEXT)")
        db.execute("INSERT INTO reviews(note) VALUES(?)", ("synthetic follow-up",))
        db.execute("PRAGMA user_version=6")
    assert seal(source, sealed)["encrypted"]
    assert b"synthetic follow-up" not in sealed.read_bytes()
    assert unseal(sealed, restored, offline=True)["sha256_verified"]
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT note FROM reviews").fetchone()[0] == "synthetic follow-up"
    with pytest.raises(ValueError):
        unseal(sealed, source, offline=True)
    with pytest.raises(ValueError):
        unseal(sealed, tmp_path / "new.sqlite3", offline=False)
    monkeypatch.setenv("GLUCOTWIN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        unseal(sealed, tmp_path / "wrong-key.sqlite3", offline=True)


def test_model_rollback_preserves_both_artifacts_and_rejects_wrong_checksum(tmp_path):
    current, candidate = tmp_path / "model.joblib", tmp_path / "approved.joblib"
    current.write_bytes(b"previous-trusted-artifact")
    candidate.write_bytes(b"approved-trusted-artifact")
    old_hash = hashlib.sha256(current.read_bytes()).hexdigest()
    approved_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        select_model(candidate, current, "0" * 64)
    assert select_model(candidate, current, approved_hash)["restart_required"]
    archived = tmp_path / "model-history" / f"{old_hash}.joblib"
    assert select_model(archived, current, old_hash)["changed"]
    assert current.read_bytes() == b"previous-trusted-artifact"
