"""Alembic uses the caller's transaction and does not log connection credentials."""
from alembic import context
from backend.dbcore import schema_metadata

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use scripts/migrate_database.py with an explicit PostgreSQL URL.")
context.configure(connection=connection, target_metadata=schema_metadata(), transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
