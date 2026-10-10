"""Apply explicit PostgreSQL migrations without copying any runtime data."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.dbcore import initialize_postgres, postgres_connection, schema_checksum

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("GLUCOTWIN_DATABASE_URL"))
    args = parser.parse_args()
    if not args.url:
        parser.error("Supply --url or GLUCOTWIN_DATABASE_URL.")
    initialize_postgres(args.url)
    with postgres_connection(args.url) as db:
        revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        version = db.execute("PRAGMA user_version").fetchone()[0]
    print({"dialect": "postgresql", "alembic_revision": revision, "schema_version": version, "schema_sha256": schema_checksum(), "data_imported": False})
