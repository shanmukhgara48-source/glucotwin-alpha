"""Record trusted context receipt alongside the declared historical times."""
from alembic import op
from sqlalchemy import text
from backend.dbcore import schema_checksum

revision = "20261010_02"
down_revision = "20261010_01"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    connection.execute(text("ALTER TABLE context ADD COLUMN received_at TEXT"))
    connection.execute(text("UPDATE glucotwin_schema SET version=7, checksum=:checksum WHERE id=1"), {"checksum": schema_checksum()})


def downgrade():
    raise RuntimeError("Destructive schema downgrade is disabled; restore an explicitly selected backup.")
