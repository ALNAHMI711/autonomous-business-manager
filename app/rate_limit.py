from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class LoginRateLimiter:
    """Durable per-IP login limiter backed by SQLite.

    Failed attempts are counted in a rolling window. Once the threshold is
    reached, the client is locked until the window expires. Successful login
    clears the failure state for that client.
    """

    def __init__(self, database_path: str | Path, max_failures: int = 5, window_seconds: int = 300):
        if max_failures < 1 or window_seconds < 1:
            raise ValueError("invalid rate limiter configuration")
        self.database_path = str(database_path)
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS login_rate_limits (
                    client_key TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    first_failure REAL NOT NULL,
                    locked_until REAL
                )"""
            )
            conn.commit()

    def check(self, client_key: str, now: float | None = None) -> tuple[bool, int]:
        key = client_key.strip()
        if not key:
            raise ValueError("client key is required")
        current = time.time() if now is None else now
        with self._connect() as conn:
            row = conn.execute(
                "SELECT failures, first_failure, locked_until FROM login_rate_limits WHERE client_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return True, 0
            failures, first_failure, locked_until = row
            if current - first_failure >= self.window_seconds:
                conn.execute("DELETE FROM login_rate_limits WHERE client_key = ?", (key,))
                conn.commit()
                return True, 0
            if locked_until and current < locked_until:
                return False, max(1, int(locked_until - current + 0.999))
            return True, max(0, self.max_failures - failures)

    def record_failure(self, client_key: str, now: float | None = None) -> tuple[bool, int]:
        key = client_key.strip()
        if not key:
            raise ValueError("client key is required")
        current = time.time() if now is None else now
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT failures, first_failure FROM login_rate_limits WHERE client_key = ?",
                (key,),
            ).fetchone()
            if row is None or current - row[1] >= self.window_seconds:
                failures = 1
                first_failure = current
            else:
                failures = int(row[0]) + 1
                first_failure = float(row[1])
            locked_until = first_failure + self.window_seconds if failures >= self.max_failures else None
            conn.execute(
                "INSERT INTO login_rate_limits(client_key, failures, first_failure, locked_until) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(client_key) DO UPDATE SET failures=excluded.failures, first_failure=excluded.first_failure, locked_until=excluded.locked_until",
                (key, failures, first_failure, locked_until),
            )
            conn.commit()
        if locked_until:
            # Keep the return value aligned with the endpoint contract:
            # the second value is remaining attempts, while check() returns
            # the retry-after duration for an already-locked client.
            return False, 0
        return True, self.max_failures - failures

    def record_success(self, client_key: str) -> None:
        key = client_key.strip()
        if not key:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM login_rate_limits WHERE client_key = ?", (key,))
            conn.commit()

    def purge(self, now: float | None = None) -> int:
        current = time.time() if now is None else now
        cutoff = current - self.window_seconds
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM login_rate_limits WHERE first_failure < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount
