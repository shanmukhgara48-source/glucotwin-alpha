"""SQLAlchemy PostgreSQL adapter for the prototype's small DB-API interface.

SQLite remains the default in storage.py. PostgreSQL migrations are explicit and
versioned; this module does not copy private SQLite runtime data into a server.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from threading import Lock

from sqlalchemy import (Column, Float, ForeignKeyConstraint, Index, Integer, MetaData,
                        PrimaryKeyConstraint, Table, Text, UniqueConstraint, create_engine, text)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT / "migrations/schema_v7.json"
WRITE_LOCK = 7162601010
_initialization_lock = Lock()
_initialized = set()


@lru_cache(maxsize=1)
def schema_manifest():
    return json.loads(SCHEMA_FILE.read_text())


def schema_checksum():
    return hashlib.sha256(SCHEMA_FILE.read_bytes()).hexdigest()


def schema_metadata(manifest=None):
    metadata = MetaData()
    types = {"INTEGER": Integer, "REAL": Float, "TEXT": Text}
    for table in (manifest or schema_manifest())["tables"]:
        columns = [Column(c["name"], types[c["type"]](), nullable=c["nullable"] and c["name"] not in table["pk"],
                          server_default=text(c["default"]) if c["default"] is not None else None)
                   for c in table["columns"]]
        constraints = [PrimaryKeyConstraint(*table["pk"])] if table["pk"] else []
        constraints += [UniqueConstraint(*u["column_names"], name=u.get("name")) for u in table["uniques"]]
        constraints += [ForeignKeyConstraint(f["constrained_columns"], [f'{f["referred_table"]}.{name}' for name in f["referred_columns"]],
                          ondelete=f.get("options", {}).get("ondelete")) for f in table["foreign_keys"]]
        created = Table(table["name"], metadata, *columns, *constraints)
        for index in table["indexes"]:
            where = index.get("dialect_options", {}).get("sqlite_where")
            Index(index["name"], *[created.c[name] for name in index["column_names"]], unique=bool(index["unique"]),
                  postgresql_where=text(where) if where else None)
    return metadata


@lru_cache(maxsize=8)
def engine_for(url):
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("PostgreSQL URL required.")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, hide_parameters=True)


def initialize_postgres(url):
    from alembic import command
    from alembic.config import Config
    with _initialization_lock:
        if url in _initialized:
            return
        config = Config(str(ROOT / "migrations/alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        with engine_for(url).begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": WRITE_LOCK})
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            checksum = connection.execute(text("SELECT checksum FROM glucotwin_schema WHERE id=1")).scalar_one()
            if checksum != schema_checksum():
                raise RuntimeError("Frozen schema checksum differs; create an explicit new migration.")
        _initialized.add(url)


class CompatRow(Mapping):
    def __init__(self, keys, values):
        self._keys, self._values = tuple(keys), tuple(values)
        self._mapping = dict(zip(self._keys, self._values))

    def __getitem__(self, key):
        return self._values[key] if isinstance(key, int) else self._mapping[key]

    def __iter__(self):
        return iter(self._mapping)

    def __len__(self):
        return len(self._mapping)


class CompatCursor:
    def __init__(self, rows=(), rowcount=0, lastrowid=None):
        self.rows, self.rowcount, self.lastrowid, self.position = list(rows), rowcount, lastrowid, 0

    def fetchone(self):
        if self.position >= len(self.rows):
            return None
        row = self.rows[self.position]
        self.position += 1
        return row

    def fetchall(self):
        remaining = self.rows[self.position:]
        self.position = len(self.rows)
        return remaining

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row


def bind_qmarks(sql, parameters):
    if isinstance(parameters, dict):
        return sql, parameters
    pieces, quoted, index, i = [], None, 0, 0
    while i < len(sql):
        char = sql[i]
        if quoted:
            pieces.append(char)
            if char == quoted:
                if i + 1 < len(sql) and sql[i + 1] == quoted:
                    pieces.append(sql[i + 1]); i += 1
                else:
                    quoted = None
        elif char in {"'", '"'}:
            quoted = char; pieces.append(char)
        elif char == "?":
            pieces.append(f":p{index}"); index += 1
        else:
            pieces.append(char)
        i += 1
    if index != len(parameters):
        raise ValueError("Parameter count differs from SQL placeholders.")
    return "".join(pieces), {f"p{i}": value for i, value in enumerate(parameters)}


class PostgresConnection:
    def __init__(self, connection):
        self.raw = connection

    def execute(self, statement, parameters=()):
        sql = statement.strip().rstrip(";")
        upper = sql.upper()
        if upper == "BEGIN IMMEDIATE":
            self.raw.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": WRITE_LOCK})
            return CompatCursor()
        if upper.startswith("PRAGMA"):
            if upper in {"PRAGMA QUICK_CHECK", "PRAGMA INTEGRITY_CHECK"}:
                self.raw.execute(text("SELECT 1"))
                return CompatCursor([CompatRow(["quick_check"], ["ok"])], 1)
            if upper == "PRAGMA USER_VERSION":
                value = self.raw.execute(text("SELECT version FROM glucotwin_schema WHERE id=1")).scalar_one()
                return CompatCursor([CompatRow(["user_version"], [value])], 1)
            if upper in {"PRAGMA FOREIGN_KEYS=ON", "PRAGMA JOURNAL_MODE=WAL"}:
                return CompatCursor()
            raise ValueError("Unsupported SQLite pragma on PostgreSQL.")
        ignored = bool(re.match(r"INSERT\s+OR\s+IGNORE\b", sql, re.I))
        if ignored:
            sql = re.sub(r"INSERT\s+OR\s+IGNORE\b", "INSERT", sql, count=1, flags=re.I)
            sql += " ON CONFLICT DO NOTHING"
        inserted = re.match(r"INSERT\s+INTO\s+([a-zA-Z_][a-zA-Z_0-9]*)", sql, re.I)
        auto_id = False
        if inserted and " RETURNING " not in sql.upper():
            table = next((t for t in schema_manifest()["tables"] if t["name"] == inserted.group(1)), None)
            auto_id = bool(table and table["pk"] == ["id"] and next(c for c in table["columns"] if c["name"] == "id")["type"] == "INTEGER")
            if auto_id:
                sql += " RETURNING id"
        bound_sql, values = bind_qmarks(sql, parameters)
        try:
            # PostgreSQL aborts transactions on statement failure; SQLite does not.
            # A savepoint preserves callers that catch uniqueness/trigger errors.
            with self.raw.begin_nested():
                result = self.raw.execute(text(bound_sql), values)
                rows = [CompatRow(result.keys(), row) for row in result.fetchall()] if result.returns_rows else []
                count = len(rows) if auto_id else result.rowcount
        except IntegrityError as error:
            raise sqlite3.IntegrityError(str(error.orig)) from error
        except SQLAlchemyError as error:
            raise sqlite3.DatabaseError(str(error.orig) if hasattr(error, "orig") else str(error)) from error
        return CompatCursor(rows, count, rows[0][0] if auto_id and rows else None)

    def executescript(self, script):
        # Identity/platform startup repeats known IF NOT EXISTS DDL. The frozen
        # Alembic schema already owns these objects; reject unknown schema drift.
        manifest = schema_manifest()
        known = {t["name"] for t in manifest["tables"]} | {x["name"] for t in manifest["tables"] for x in t["indexes"]} | {t["name"] for t in manifest["triggers"]}
        declarations = re.findall(r"CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX|TRIGGER)\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][a-zA-Z_0-9]*)", script, re.I)
        if not declarations or any(name not in known for name in declarations):
            raise ValueError("Schema script is not in the frozen migration; add a versioned migration.")
        stripped = re.sub(r"CREATE\s+TRIGGER\b.*?\bEND\s*;", "", script, flags=re.I | re.S)
        for statement in stripped.split(";"):
            if statement.strip() and not re.match(r"\s*CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\s+IF\s+NOT\s+EXISTS\b", statement, re.I):
                raise ValueError("Only known idempotent schema declarations may be skipped.")
        return CompatCursor()


@contextmanager
def postgres_connection(url):
    initialize_postgres(url)
    with engine_for(url).begin() as connection:
        yield PostgresConnection(connection)
