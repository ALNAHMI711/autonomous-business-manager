#!/usr/bin/env python3
"""Restore a verified SQLite backup into a new database path.

Usage:
  python deploy/restore_database.py BACKUP DESTINATION

The destination must not exist unless --force is supplied. The source is
validated with SQLite's integrity_check before copying, and the restored
database is checked again after the copy.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def _integrity_ok(path: Path) -> bool:
    with sqlite3.connect(path) as connection:
        return connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="verified SQLite backup to restore")
    parser.add_argument("destination", help="new SQLite database path")
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow replacing an existing destination",
    )
    args = parser.parse_args()

    source = Path(args.source)
    destination = Path(args.destination)

    if not source.is_file():
        raise SystemExit(f"backup not found: {source}")

    if not _integrity_ok(source):
        raise SystemExit(f"backup integrity check failed: {source}")

    if destination.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite existing database: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary = destination.with_name(destination.name + ".restore.tmp")
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(source) as source_db:
            with sqlite3.connect(temporary) as destination_db:
                source_db.backup(destination_db)

        if not _integrity_ok(temporary):
            raise SystemExit("restored database integrity check failed")

        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)

    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
