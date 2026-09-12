from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class AuthStore:
    """Durable session store; token hashes plus a stable user identity."""

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
            connection.execute("""
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                )
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(auth_sessions)").fetchall()}
            if "user_id" not in columns:
                connection.execute("ALTER TABLE auth_sessions ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)")

    def create(self, token_hash: str, user_id: int = 1) -> str:
        if not token_hash:
            raise ValueError("token_hash must not be empty")
        if int(user_id) <= 0:
            raise ValueError("user_id must be positive")
        self.initialize()
        now = self._now()
        expires = now + timedelta(seconds=self.ttl_seconds)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO auth_sessions(token_hash, user_id, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, NULL)",
                (token_hash, int(user_id), now.isoformat(), expires.isoformat()),
            )
        return expires.isoformat()

    def user_id(self, token_hash: str) -> int | None:
        if not token_hash:
            return None
        self.initialize()
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_id, expires_at, revoked_at FROM auth_sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        if not row or row["revoked_at"]:
            return None
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
        except (TypeError, ValueError):
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            return None
        return int(row["user_id"])

    def valid(self, token_hash: str) -> bool:
        return self.user_id(token_hash) is not None

    def revoke(self, token_hash: str) -> None:
        if not token_hash:
            return
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (self._now().isoformat(), token_hash),
            )

    def purge_expired(self) -> int:
        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL",
                (self._now().isoformat(),),
            )
            return int(cursor.rowcount)
