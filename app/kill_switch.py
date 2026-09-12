from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


class KillSwitch:
    """Durable fail-safe gate for automation execution.

    Engaging the switch blocks new automation while preserving existing
    business records and positions. Callers decide how to surface the state
    to the human operator; this class never closes or deletes user work.
    """

    def __init__(self, database_path: str) -> None:
        self.database_path = str(Path(database_path))
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS kill_switch (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    active INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO kill_switch (id, active, reason, updated_at)
                VALUES (1, 0, '', ?)
                """,
                (self._now(),),
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def is_active(self) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT active FROM kill_switch WHERE id = 1"
            ).fetchone()
            return bool(row and row[0])

    def status(self) -> dict[str, object]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT active, reason, updated_at FROM kill_switch WHERE id = 1"
            ).fetchone()
        return {
            "active": bool(row and row[0]),
            "reason": str(row[1]) if row else "",
            "updated_at": str(row[2]) if row else "",
        }

    def engage(self, reason: str = "manual_kill_switch") -> dict[str, object]:
        reason = str(reason or "manual_kill_switch").strip()[:500]
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE kill_switch SET active = 1, reason = ?, updated_at = ? WHERE id = 1",
                (reason, self._now()),
            )
        return self.status()

    def release(self) -> dict[str, object]:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE kill_switch SET active = 0, reason = '', updated_at = ? WHERE id = 1",
                (self._now(),),
            )
        return self.status()
