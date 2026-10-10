"""Small SQLite clinic store. Data stays in the ignored runtime directory."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def db_path() -> Path:
    return Path(os.environ.get("GLUCOTWIN_DB_PATH", ROOT / ".run" / "clinic.sqlite3"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize() -> None:
    configured = os.environ.get("GLUCOTWIN_DATABASE_URL")
    if configured:
        from backend.dbcore import initialize_postgres
        initialize_postgres(configured)
        return
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=30) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        if db.execute("PRAGMA user_version").fetchone()[0] < 1:
            db.executescript("""
            CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
              password_hash TEXT NOT NULL, role TEXT NOT NULL, clinic_id TEXT NOT NULL);
            CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
              expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE profiles(clinic_id TEXT NOT NULL, patient_id TEXT NOT NULL, profile_json TEXT NOT NULL,
              PRIMARY KEY(clinic_id,patient_id));
            CREATE TABLE monitoring(clinic_id TEXT PRIMARY KEY, config_json TEXT NOT NULL);
            CREATE TABLE observations(id INTEGER PRIMARY KEY, clinic_id TEXT NOT NULL, patient_id TEXT NOT NULL,
              timestamp TEXT NOT NULL, available_at TEXT NOT NULL, glucose_mg_dl REAL NOT NULL, source TEXT NOT NULL,
              UNIQUE(clinic_id,patient_id,timestamp));
            CREATE TABLE context(id INTEGER PRIMARY KEY, clinic_id TEXT NOT NULL, patient_id TEXT NOT NULL,
              kind TEXT NOT NULL, value_json TEXT NOT NULL, observed_at TEXT NOT NULL, available_at TEXT NOT NULL,
              provenance TEXT NOT NULL, created_by TEXT NOT NULL);
            CREATE TABLE forecasts(id INTEGER PRIMARY KEY, clinic_id TEXT NOT NULL, patient_id TEXT NOT NULL,
              issued_at TEXT NOT NULL, input_cutoff TEXT NOT NULL, model_version TEXT NOT NULL, scenario TEXT NOT NULL,
              snapshot_json TEXT NOT NULL, recorded_at TEXT NOT NULL,
              UNIQUE(clinic_id,patient_id,issued_at,scenario,model_version));
            CREATE TABLE reviews(id INTEGER PRIMARY KEY, clinic_id TEXT NOT NULL, patient_id TEXT NOT NULL,
              forecast_id INTEGER NOT NULL REFERENCES forecasts(id), type TEXT NOT NULL, status TEXT NOT NULL,
              issued_at TEXT NOT NULL, assigned_reviewer TEXT, message TEXT NOT NULL, probability REAL,
              last_review TEXT, next_review_at TEXT, closed_at TEXT);
            CREATE TABLE actions(id INTEGER PRIMARY KEY, clinic_id TEXT NOT NULL, review_id INTEGER NOT NULL REFERENCES reviews(id),
              actor_id TEXT NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL, note TEXT NOT NULL,
              next_review_at TEXT, recorded_at TEXT NOT NULL);
            CREATE TABLE audit(id INTEGER PRIMARY KEY, clinic_id TEXT NOT NULL, actor_id TEXT NOT NULL,
              event TEXT NOT NULL, resource TEXT NOT NULL, details_json TEXT NOT NULL, recorded_at TEXT NOT NULL);
            CREATE INDEX observations_prefix ON observations(clinic_id,patient_id,timestamp,available_at);
            CREATE INDEX reviews_queue ON reviews(clinic_id,status,issued_at);
            CREATE TRIGGER forecasts_immutable BEFORE UPDATE ON forecasts BEGIN SELECT RAISE(ABORT,'Issued forecasts are immutable'); END;
            CREATE TRIGGER actions_immutable BEFORE UPDATE ON actions BEGIN SELECT RAISE(ABORT,'Review actions are immutable'); END;
            PRAGMA user_version=1;
            """)
        if db.execute("PRAGMA user_version").fetchone()[0] < 2:
            db.execute("ALTER TABLE context ADD COLUMN dedupe_key TEXT")
            db.execute("CREATE UNIQUE INDEX context_dedupe ON context(clinic_id,patient_id,dedupe_key) WHERE dedupe_key IS NOT NULL")
            db.execute("PRAGMA user_version=2")
        if db.execute("PRAGMA user_version").fetchone()[0] < 3:
            db.executescript("""
            CREATE TABLE forecast_outcomes(id INTEGER PRIMARY KEY, clinic_id TEXT NOT NULL,
              forecast_id INTEGER NOT NULL REFERENCES forecasts(id), horizon_minutes INTEGER NOT NULL,
              target_time TEXT NOT NULL, available_at TEXT NOT NULL, actual_glucose_mg_dl REAL NOT NULL,
              event_occurred INTEGER, provenance TEXT NOT NULL, recorded_at TEXT NOT NULL,
              UNIQUE(forecast_id,horizon_minutes));
            CREATE TRIGGER outcomes_immutable BEFORE UPDATE ON forecast_outcomes BEGIN SELECT RAISE(ABORT,'Forecast outcomes are immutable'); END;
            PRAGMA user_version=3;
            """)
        if db.execute("PRAGMA user_version").fetchone()[0] < 4:
            db.executescript("""
            ALTER TABLE observations ADD COLUMN received_at TEXT;
            ALTER TABLE observations ADD COLUMN connection_id TEXT;
            ALTER TABLE observations ADD COLUMN source_event_id TEXT;
            ALTER TABLE forecasts ADD COLUMN source_connection_id TEXT;
            ALTER TABLE forecasts ADD COLUMN input_digest TEXT;
            ALTER TABLE forecasts ADD COLUMN clock_kind TEXT NOT NULL DEFAULT 'recorded';
            ALTER TABLE reviews ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE reviews ADD COLUMN disposition TEXT NOT NULL DEFAULT 'none';
            ALTER TABLE reviews ADD COLUMN latest_forecast_id INTEGER REFERENCES forecasts(id);
            ALTER TABLE reviews ADD COLUMN last_seen_at TEXT;
            ALTER TABLE reviews ADD COLUMN occurrence_count INTEGER NOT NULL DEFAULT 1;
            CREATE TABLE source_connections(id TEXT PRIMARY KEY,clinic_id TEXT NOT NULL,name TEXT NOT NULL,
              source_type TEXT NOT NULL,status TEXT NOT NULL,patient_id TEXT,device_id TEXT,
              cadence_minutes INTEGER NOT NULL,source_timezone TEXT NOT NULL,config_json TEXT NOT NULL,
              created_by TEXT NOT NULL,created_at TEXT NOT NULL,connection_key_hash TEXT);
            CREATE TABLE ingest_events(id TEXT PRIMARY KEY,clinic_id TEXT NOT NULL,connection_id TEXT NOT NULL REFERENCES source_connections(id),
              patient_id TEXT NOT NULL,source_event_id TEXT NOT NULL,payload_digest TEXT NOT NULL,
              observation_json TEXT NOT NULL,measured_at TEXT NOT NULL,declared_available_at TEXT,
              received_at TEXT NOT NULL,status TEXT NOT NULL,
              UNIQUE(connection_id,source_event_id));
            CREATE TABLE ingest_quarantine(id INTEGER PRIMARY KEY,clinic_id TEXT NOT NULL,connection_id TEXT NOT NULL,
              patient_id TEXT NOT NULL,source_event_id TEXT NOT NULL,reason TEXT NOT NULL,
              payload_digest TEXT NOT NULL,received_at TEXT NOT NULL);
            CREATE TABLE forecast_jobs(id INTEGER PRIMARY KEY,clinic_id TEXT NOT NULL,patient_id TEXT NOT NULL,
              connection_id TEXT NOT NULL,event_id TEXT NOT NULL UNIQUE REFERENCES ingest_events(id),
              issue_cutoff TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
              available_after TEXT NOT NULL,lease_owner TEXT,lease_until TEXT,last_error TEXT,
              forecast_id INTEGER REFERENCES forecasts(id),created_at TEXT NOT NULL,completed_at TEXT);
            CREATE INDEX jobs_due ON forecast_jobs(status,available_after,lease_until);
            CREATE TABLE event_outcomes(id INTEGER PRIMARY KEY,clinic_id TEXT NOT NULL,forecast_id INTEGER NOT NULL REFERENCES forecasts(id),
              horizon_minutes INTEGER NOT NULL,target_time TEXT NOT NULL,event_occurred INTEGER NOT NULL,
              available_at TEXT NOT NULL,provenance TEXT NOT NULL,recorded_at TEXT NOT NULL,
              UNIQUE(forecast_id,horizon_minutes));
            CREATE TABLE operational_events(id INTEGER PRIMARY KEY,clinic_id TEXT NOT NULL,type TEXT NOT NULL,
              patient_id TEXT,resource_id TEXT,created_at TEXT NOT NULL);
            CREATE TABLE worker_status(id TEXT PRIMARY KEY,last_heartbeat_at TEXT NOT NULL,status TEXT NOT NULL);
            CREATE TRIGGER forecasts_no_delete BEFORE DELETE ON forecasts BEGIN SELECT RAISE(ABORT,'Issued forecasts are immutable'); END;
            CREATE TRIGGER actions_no_delete BEFORE DELETE ON actions BEGIN SELECT RAISE(ABORT,'Review actions are immutable'); END;
            CREATE TRIGGER outcomes_no_delete BEFORE DELETE ON forecast_outcomes BEGIN SELECT RAISE(ABORT,'Forecast outcomes are immutable'); END;
            CREATE TRIGGER event_outcomes_no_update BEFORE UPDATE ON event_outcomes BEGIN SELECT RAISE(ABORT,'Event outcomes are immutable'); END;
            CREATE TRIGGER event_outcomes_no_delete BEFORE DELETE ON event_outcomes BEGIN SELECT RAISE(ABORT,'Event outcomes are immutable'); END;
            CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'Audit is append only'); END;
            CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'Audit is append only'); END;
            PRAGMA user_version=4;
            """)
        if db.execute("PRAGMA user_version").fetchone()[0] < 5:
            columns = {row[1] for row in db.execute("PRAGMA table_info(source_connections)")}
            if "connection_key_hash" not in columns:
                db.execute("ALTER TABLE source_connections ADD COLUMN connection_key_hash TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS operational_forecast_input ON forecasts(clinic_id,patient_id,source_connection_id,input_digest,model_version) WHERE source_connection_id IS NOT NULL")
            db.execute("PRAGMA user_version=5")
        if db.execute("PRAGMA user_version").fetchone()[0] < 6:
            db.execute("ALTER TABLE actions ADD COLUMN disposition TEXT NOT NULL DEFAULT 'none'")
            db.execute("PRAGMA user_version=6")
        if db.execute("PRAGMA user_version").fetchone()[0] < 7:
            db.execute("ALTER TABLE context ADD COLUMN received_at TEXT")
            db.execute("PRAGMA user_version=7")
    os.chmod(path, 0o600)


@contextmanager
def connection():
    configured = os.environ.get("GLUCOTWIN_DATABASE_URL")
    if configured:
        from backend.dbcore import initialize_postgres, postgres_connection
        initialize_postgres(configured)
        with postgres_connection(configured) as db:
            yield db
        return
    initialize()
    db = sqlite3.connect(db_path(), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def audit(db, user: dict, event: str, resource: str, details: dict | None = None):
    db.execute("INSERT INTO audit(clinic_id,actor_id,event,resource,details_json,recorded_at) VALUES(?,?,?,?,?,?)",
               (user["clinic_id"], user["id"], event, resource, json.dumps(details or {}), utc_now()))


def backup(destination: Path) -> None:
    if os.environ.get("GLUCOTWIN_DATABASE_URL"):
        raise ValueError("PostgreSQL uses its own verified backup procedure; SQLite backup is disabled for this configuration.")
    initialize()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path()) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    os.chmod(destination, 0o600)


def restore(source: Path) -> None:
    if os.environ.get("GLUCOTWIN_DATABASE_URL"):
        raise ValueError("PostgreSQL uses its own offline restore procedure; SQLite restore is disabled for this configuration.")
    # Restore only while the API is stopped; SQLite's backup API includes WAL changes.
    if not source.exists():
        raise ValueError("Backup file does not exist")
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as backup_db:
        if backup_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed")
        db_path().parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path()) as target:
            backup_db.backup(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clinic backup/restore. Stop the API before restore.")
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    (backup if args.action == "backup" else restore)(args.path)
    print(f"{args.action} completed: {args.path}")
