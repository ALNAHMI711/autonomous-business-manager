#!/usr/bin/env python3
"""Create a consistent SQLite backup for Autonomous Business Manager.

Usage:
  python deploy/backup_database.py [destination]

The backup is created with SQLite's online backup API, so the application
does not need to be stopped first. The destination defaults to
data/backups/business_manager-<UTC timestamp>.db.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", help="output SQLite backup path")
    args = parser.parse_args()

    source = Path("data/business_manager.db")
    if not source.exists():
        raise SystemExit(f"database not found: {source}")

    if args.destination:
        destination = Path(args.destination)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = Path("data/backups") / f"business_manager-{stamp}.db"

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise SystemExit(f"refusing to overwrite existing backup: {destination}")

    with sqlite3.connect(source) as source_db:
        with sqlite3.connect(destination) as backup_db:
            source_db.backup(backup_db)

    with sqlite3.connect(destination) as check_db:
        row = check_db.execute("PRAGMA integrity_check").fetchone()
        if row != ("ok",):
            destination.unlink(missing_ok=True)
            raise SystemExit(f"backup integrity check failed: {row!r}")

    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
