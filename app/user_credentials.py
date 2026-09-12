from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from app.passwords import PasswordService


class UserCredentialStore:
    """Durable per-user credentials, separated from project ownership data."""

    def __init__(self, database_path: str, password_service: Optional[PasswordService] = None):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.passwords = password_service or PasswordService()

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
                CREATE TABLE IF NOT EXISTS user_credentials (
                    user_id INTEGER PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_credentials_updated ON user_credentials(updated_at)"
            )

    def set_password(self, user_id: int, password: str) -> None:
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("invalid user_id")
        if not isinstance(password, str) or len(password) < 12:
            raise ValueError("password must contain at least 12 characters")
        password_hash = self.passwords.hash_password(password)
        with self._connect() as connection:
            user = connection.execute(
                "SELECT id FROM users WHERE id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
            if user is None:
                raise ValueError("active user does not exist")
            connection.execute(
                """
                INSERT INTO user_credentials(user_id, password_hash, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    updated_at = excluded.updated_at
                """,
                (user_id, password_hash),
            )

    def verify(self, user_id: int, password: str) -> bool:
        if not isinstance(user_id, int) or user_id <= 0:
            return False
        if not isinstance(password, str) or not password:
            return False
        with self._connect() as connection:
            row = connection.execute(
                "SELECT password_hash FROM user_credentials WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return False
        return self.passwords.verify_password(password, row["password_hash"])

    def get_user_id_by_username(self, username: str) -> Optional[int]:
        if not isinstance(username, str):
            return None
        normalized = username.strip()
        if not normalized:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM users WHERE username = ? AND is_active = 1",
                (normalized,),
            ).fetchone()
        return int(row["id"]) if row else None

    def authenticate(self, username: str, password: str) -> Optional[int]:
        user_id = self.get_user_id_by_username(username)
        if user_id is None or not self.verify(user_id, password):
            return None
        return user_id
