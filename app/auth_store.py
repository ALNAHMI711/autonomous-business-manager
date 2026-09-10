from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


class AuthStore:
    """Durable hashed session store with expiry and revocation."""

    def __init__(self, database_path: str, ttl_seconds: int = 86_400) -> None:
        self.database_path = Path(database_path)
        self.ttl_seconds = max(300, int(ttl_seconds))
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at)"
            )

    def create(self, token_hash: str) -> str:
        now = self._now()
        expires = now + timedelta(seconds=self.ttl_seconds)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO auth_sessions(token_hash, created_at, expires_at, revoked_at) VALUES (?, ?, ?, NULL)",
                (token_hash, now.isoformat(), expires.isoformat()),
            )
        return expires.isoformat()

    def valid(self, token_hash: str) -> bool:
        now = self._now().isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT expires_at, revoked_at FROM auth_sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return bool(row and not row["revoked_at"] and row["expires_at"] > now)

    def revoke(self, token_hash: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (self._now().isoformat(), token_hash),
            )

    def purge_expired(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL",
                (self._now().isoformat(),),
            )
            return int(cursor.rowcount)
