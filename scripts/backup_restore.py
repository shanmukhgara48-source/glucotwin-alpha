"""Consistent SQLite backup and verified, offline restore for the local clinic."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def verify(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"Database does not exist: {path}")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Database integrity check failed: {integrity}")
        return {"integrity": integrity, "schema_version": db.execute("PRAGMA user_version").fetchone()[0],
                "tables": [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]}


def backup(source: Path, destination: Path) -> dict:
    if source.resolve() == destination.resolve():
        raise ValueError("Backup must have a different destination")
    verify(source)
    if destination.exists():
        raise ValueError("Destination exists; choose a new backup filename")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # SQLite's backup API captures a consistent snapshot, including WAL transactions.
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    os.chmod(destination, 0o600)
    return verify(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore", "verify"])
    parser.add_argument("--database", type=Path, default=Path(os.getenv("GLUCOTWIN_DB_PATH", ROOT / ".run/clinic.sqlite3")))
    parser.add_argument("--file", type=Path, help="Backup output or restore source")
    parser.add_argument("--offline", action="store_true", help="Confirm the API is stopped before restoring")
    args = parser.parse_args()
    if args.operation == "verify":
        result = verify(args.database)
    elif not args.file:
        parser.error("--file is required")
    elif args.operation == "backup":
        result = backup(args.database, args.file)
    else:
        if not args.offline:
            parser.error("Stop the API and pass --offline before restoring")
        # Never overwrite an existing clinic database; preserve its recovery path.
        result = backup(args.file, args.database)
    import json
    print(json.dumps({"success": True, "data": result}, indent=2))


if __name__ == "__main__":
    main()
