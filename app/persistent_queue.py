from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class PersistentTaskQueue:
    """Small durable FIFO queue backed by SQLite.

    This component is intentionally independent from TaskManager so it can be
    integrated behind the existing execution layer without changing behavior
    until its integration is tested. Claims are transactional and survive
    process restarts.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _decode(value: str) -> dict[str, Any]:
        try:
            result = json.loads(value)
            return result if isinstance(result, dict) else {}
        except (TypeError, ValueError):
            return {}

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL UNIQUE,
                    payload TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    claimed_at TEXT,
                    completed_at TEXT,
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_queue_ready
                ON task_queue(status, available_at, id)
                """
            )

    def enqueue(
        self,
        task_id: int,
        payload: Optional[dict[str, Any]] = None,
        available_at: Optional[str] = None,
    ) -> dict[str, Any]:
        now = self._now()
        ready_at = available_at or now
        encoded = json.dumps(payload or {}, ensure_ascii=False, default=str)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_queue (
                    task_id, payload, status, attempts, available_at,
                    created_at, updated_at
                ) VALUES (?, ?, 'queued', 0, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    payload = excluded.payload,
                    status = CASE
                        WHEN task_queue.status IN ('completed', 'cancelled')
                        THEN task_queue.status
                        ELSE 'queued'
                    END,
                    available_at = excluded.available_at,
                    error_message = '',
                    updated_at = excluded.updated_at
                """,
                (task_id, encoded, ready_at, now, now),
            )
            row = connection.execute(
                "SELECT * FROM task_queue WHERE task_id = ?",
                (task_id,),
            ).fetchone()

        return self._row(row)

    def claim_next(self, now: Optional[str] = None) -> Optional[dict[str, Any]]:
        current = now or self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM task_queue
                WHERE status = 'queued' AND available_at <= ?
                ORDER BY id ASC LIMIT 1
                """,
                (current,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None

            updated = connection.execute(
                """
                UPDATE task_queue
                SET status='running', attempts=attempts+1,
                    claimed_at=?, updated_at=?
                WHERE id=? AND status='queued'
                """,
                (current, current, row["id"]),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None

            claimed = connection.execute(
                "SELECT * FROM task_queue WHERE id = ?",
                (row["id"],),
            ).fetchone()
            connection.commit()

        return self._row(claimed)

    def complete(self, task_id: int) -> Optional[dict[str, Any]]:
        return self._transition(task_id, "completed", "")

    def fail(
        self,
        task_id: int,
        error_message: str,
        retry_at: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if retry_at:
            now = self._now()
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE task_queue
                    SET status='queued', available_at=?,
                        error_message=?, updated_at=?
                    WHERE task_id=? AND status='running'
                    """,
                    (retry_at, error_message[:2000], now, task_id),
                )
                row = connection.execute(
                    "SELECT * FROM task_queue WHERE task_id=?",
                    (task_id,),
                ).fetchone()
            return self._row(row)

        return self._transition(task_id, "failed", error_message[:2000])

    def cancel(self, task_id: int) -> Optional[dict[str, Any]]:
        return self._transition(task_id, "cancelled", "")

    def get(self, task_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_queue WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return self._row(row) if row else None

    def _transition(
        self,
        task_id: int,
        status: str,
        error_message: str,
    ) -> Optional[dict[str, Any]]:
        now = self._now()
        completed_at = now if status in {"completed", "cancelled", "failed"} else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_queue
                SET status=?, error_message=?, completed_at=?, updated_at=?
                WHERE task_id=? AND status='running'
                """,
                (status, error_message, completed_at, now, task_id),
            )
            row = connection.execute(
                "SELECT * FROM task_queue WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = PersistentTaskQueue._decode(result["payload"])
        return result
