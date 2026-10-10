"""Opt-in real PostgreSQL smoke tests; never target an existing user database."""
import os
import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url

from backend.dbcore import (PostgresConnection, bind_qmarks, engine_for,
                            postgres_connection, schema_checksum, schema_manifest)

URL = os.environ.get("GLUCOTWIN_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Set an isolated GLUCOTWIN_TEST_PG_URL for actual PG checks.")


@pytest.fixture
def url():
    if not make_url(URL).database.startswith("glucotwin_validation_"):
        pytest.fail("PostgreSQL tests require an explicitly isolated glucotwin_validation_* database.")
    return URL


def profile(db):
    identifier = "pgtest-" + uuid4().hex
    db.execute("INSERT INTO profiles VALUES(?,?,?)", (identifier, identifier, '{}'))
    return identifier


def forecast(db, identifier):
    return db.execute("INSERT INTO forecasts(clinic_id,patient_id,issued_at,input_cutoff,model_version,scenario,snapshot_json,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                      (identifier, identifier, "2026-10-10T09:01:00Z", "2026-10-10T09:00:00Z", "pg-smoke", "synthetic", '{}', "2026-10-10T09:01:00Z")).lastrowid


def test_real_schema_and_migration_identity(url):
    with postgres_connection(url) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20261010_02"
        assert db.execute("SELECT checksum FROM glucotwin_schema").fetchone()[0] == schema_checksum()
        assert db.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('users','forecast_jobs','platform_consents','auth_mfa')").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND n.nspname='public'").fetchone()[0] == len(schema_manifest()["triggers"])
        default = db.execute("SELECT column_default FROM information_schema.columns WHERE table_name='observations' AND column_name='id'").fetchone()[0]
        assert "nextval" in default


def test_bound_parameters_and_row_access(url):
    with postgres_connection(url) as db:
        row = db.execute("SELECT ? AS value, '?' AS literal", ("research; DROP TABLE users;",)).fetchone()
        assert row[0] == row["value"] == "research; DROP TABLE users;"
        assert dict(row)["literal"] == "?"
        assert list(row.keys()) == ["value", "literal"]
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_insert_ignore_lastrowid_and_recovery_after_statement_error(url):
    with postgres_connection(url) as db:
        identifier = profile(db)
        ignored = db.execute("INSERT OR IGNORE INTO profiles VALUES(?,?,?)", (identifier, identifier, '{}'))
        assert ignored.rowcount == 0
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO profiles VALUES(?,?,?)", (identifier, identifier, '{}'))
        assert db.execute("SELECT COUNT(*) FROM profiles WHERE clinic_id=?", (identifier,)).fetchone()[0] == 1
        inserted = db.execute("INSERT INTO observations(clinic_id,patient_id,timestamp,available_at,glucose_mg_dl,source) VALUES(?,?,?,?,?,?)",
                             (identifier, identifier, "2026-10-10T09:00:00Z", "2026-10-10T09:01:00Z", 130.0, "synthetic"))
        assert isinstance(inserted.lastrowid, int) and inserted.lastrowid > 0
        assert inserted.rowcount == 1
        duplicate = db.execute("INSERT OR IGNORE INTO observations(clinic_id,patient_id,timestamp,available_at,glucose_mg_dl,source) VALUES(?,?,?,?,?,?)",
                              (identifier, identifier, "2026-10-10T09:00:00Z", "2026-10-10T09:01:00Z", 130.0, "synthetic"))
        assert duplicate.lastrowid is None and duplicate.rowcount == 0


def test_outer_transaction_rollback(url):
    identifier = "pgtest-" + uuid4().hex
    with pytest.raises(RuntimeError):
        with postgres_connection(url) as db:
            db.execute("INSERT INTO profiles VALUES(?,?,?)", (identifier, identifier, '{}'))
            raise RuntimeError("synthetic failure")
    with postgres_connection(url) as db:
        assert db.execute("SELECT COUNT(*) FROM profiles WHERE clinic_id=?", (identifier,)).fetchone()[0] == 0


def test_foreign_keys_and_append_only_records(url):
    with postgres_connection(url) as db:
        identifier = profile(db)
        prediction_id = forecast(db, identifier)
        for mutation in ["UPDATE forecasts SET model_version='changed' WHERE id=?", "DELETE FROM forecasts WHERE id=?"]:
            with pytest.raises(sqlite3.IntegrityError, match="Immutable"):
                db.execute(mutation, (prediction_id,))
        assert db.execute("SELECT model_version FROM forecasts WHERE id=?", (prediction_id,)).fetchone()[0] == "pg-smoke"
        outcome = db.execute("INSERT INTO forecast_outcomes(clinic_id,forecast_id,horizon_minutes,target_time,available_at,actual_glucose_mg_dl,provenance,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                             (identifier, prediction_id, 30, "2026-10-10T09:30:00Z", "2026-10-10T09:31:00Z", 137., "synthetic", "2026-10-10T09:31:00Z")).lastrowid
        with pytest.raises(sqlite3.IntegrityError, match="Immutable"):
            db.execute("DELETE FROM forecast_outcomes WHERE id=?", (outcome,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO reviews(clinic_id,patient_id,forecast_id,type,status,issued_at,message) VALUES(?,?,?,?,?,?,?)",
                       (identifier, identifier, 2147483647, "synthetic", "new", "2026-10-10T09:01:00Z", "synthetic FK failure"))


def test_upsert_and_known_schema_startup(url):
    with postgres_connection(url) as db:
        identifier = "pgtest-" + uuid4().hex
        db.execute("INSERT INTO monitoring VALUES(?,?) ON CONFLICT(clinic_id) DO UPDATE SET config_json=excluded.config_json", (identifier, '{"active":0}'))
        db.execute("INSERT INTO monitoring VALUES(?,?) ON CONFLICT(clinic_id) DO UPDATE SET config_json=excluded.config_json", (identifier, '{"active":1}'))
        assert db.execute("SELECT config_json FROM monitoring WHERE clinic_id=?", (identifier,)).fetchone()[0] == '{"active":1}'
        db.executescript("CREATE TABLE IF NOT EXISTS platform_tasks(id INTEGER PRIMARY KEY); CREATE TRIGGER IF NOT EXISTS consents_no_update BEFORE UPDATE ON platform_consents BEGIN SELECT RAISE(ABORT,'immutable'); END;")
        with pytest.raises(ValueError, match="frozen"):
            db.executescript("CREATE TABLE IF NOT EXISTS unknown_schema(id INTEGER PRIMARY KEY);")


def test_worker_transaction_lock_is_real(url):
    with postgres_connection(url) as db:
        db.execute("BEGIN IMMEDIATE")
        assert db.execute("SELECT COUNT(*) FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()").fetchone()[0] >= 1


def test_concurrent_invitation_activation_is_single_use(url, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone
    from fastapi import HTTPException
    from backend.identity import digest
    from backend.platform import Activate, activate
    monkeypatch.setenv("GLUCOTWIN_DATABASE_URL", url)
    identifier, invitation = "pginvite-" + uuid4().hex, uuid4().hex
    with postgres_connection(url) as db:
        db.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", (identifier, identifier, "Synthetic PG invitation", "not-an-active-password", "clinician", identifier))
        db.execute("INSERT INTO platform_user_state VALUES(?,0,?)", (identifier, datetime.now(timezone.utc).isoformat()))
        db.execute("INSERT INTO platform_invites VALUES(?,?,?,NULL)", (digest(invitation), identifier, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()))
    def consume(_):
        try:
            return 200 if activate(Activate(invitation_code=invitation, password="private-pg-invitation-password"))["data"]["activated"] else 500
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(consume, range(2))) == [200, 422]
