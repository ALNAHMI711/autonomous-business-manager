#!/usr/bin/env python3
"""Backup -> restore drill for the SQLite database.

Usage (on the deployment host, from the repository root):
  docker compose exec -T app python deploy/restore_drill.py [--db data/business_manager.db]

The drill takes a live online backup into a temporary directory, restores it
into a second temporary database, then proves the restored copy is healthy:
  * PRAGMA integrity_check is "ok" for the backup and the restored copy
  * every table exists in the restored copy with the same row count as the
    backup taken from the live database
It never modifies the live database and removes its temporary files. Exit
status 0 means the drill passed; anything else means it failed.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path


def _tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def table_counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        return {
            name: int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            for name in _tables(connection)
        }


def _integrity_ok(path: Path) -> bool:
    with sqlite3.connect(path) as connection:
        return connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def _copy(source: Path, destination: Path) -> None:
    with sqlite3.connect(source) as source_db:
        with sqlite3.connect(destination) as destination_db:
            source_db.backup(destination_db)


def run_drill(database: Path) -> list[str]:
    """Return a list of problems; an empty list means the drill passed."""
    problems: list[str] = []
    if not database.is_file():
        return [f"database not found: {database}"]

    with tempfile.TemporaryDirectory(prefix="restore-drill-") as workdir:
        backup = Path(workdir) / "backup.db"
        restored = Path(workdir) / "restored.db"

        _copy(database, backup)
        if not _integrity_ok(backup):
            problems.append("backup integrity check failed")
        _copy(backup, restored)
        if not _integrity_ok(restored):
            problems.append("restored database integrity check failed")

        expected = table_counts(backup)
        actual = table_counts(restored)
        for name, count in expected.items():
            if name not in actual:
                problems.append(f"table missing after restore: {name}")
            elif actual[name] != count:
                problems.append(f"row count mismatch in {name}: backup={count} restored={actual[name]}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/business_manager.db", help="live SQLite database path")
    args = parser.parse_args(argv)

    problems = run_drill(Path(args.db))
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print("PASS: backup and restore drill succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
