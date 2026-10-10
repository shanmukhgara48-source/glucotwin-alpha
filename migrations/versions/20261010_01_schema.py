"""Frozen research schema: SQLite v6 plus identity/platform, real PostgreSQL DDL."""
from alembic import op
from sqlalchemy import text
from backend.dbcore import schema_checksum, schema_manifest, schema_metadata
import hashlib
import json
from pathlib import Path

revision = "20261010_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("This revision is for PostgreSQL; SQLite retains its numbered migrations.")
    original_file = Path(__file__).resolve().parents[1] / "schema_v6.json"
    original = json.loads(original_file.read_text())
    schema_metadata(original).create_all(connection)
    connection.execute(text("CREATE TABLE glucotwin_schema(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, checksum TEXT NOT NULL)"))
    connection.execute(text("INSERT INTO glucotwin_schema VALUES(1,:version,:checksum)"),
                       {"version": original["sqlite_schema_version"], "checksum": hashlib.sha256(original_file.read_bytes()).hexdigest()})
    connection.execute(text("""CREATE FUNCTION glucotwin_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Immutable GlucoTwin record' USING ERRCODE='23514'; END; $$"""))
    for trigger in original["triggers"]:
        action = "DELETE" if "BEFORE DELETE" in trigger["sql"].upper() else "UPDATE"
        # Names/table names come only from the frozen source-owned manifest.
        connection.execute(text(f'CREATE TRIGGER "{trigger["name"]}" BEFORE {action} ON "{trigger["table"]}" FOR EACH ROW EXECUTE FUNCTION glucotwin_reject_mutation()'))


def downgrade():
    raise RuntimeError("Destructive schema downgrade is disabled; restore an explicitly selected backup.")
