from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


class OwnershipStore:
    BOOTSTRAP_USER_ID = 1
    BOOTSTRAP_USERNAME = "admin"

    def __init__(self, database_path: str):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO users(id, username, is_active, created_at) VALUES (1, 'admin', 1, datetime('now'))"
            )
            projects = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='projects'").fetchone()
            if not projects:
                return
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(projects)").fetchall()}
            if "owner_id" not in columns:
                connection.execute("ALTER TABLE projects ADD COLUMN owner_id INTEGER NOT NULL DEFAULT 1")
            connection.execute("UPDATE projects SET owner_id = 1 WHERE owner_id IS NULL OR owner_id <= 0")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)")

    def create_user(self, username: str) -> int:
        username = username.strip()
        if not username or len(username) > 120:
            raise ValueError("invalid username")
        with self._connect() as connection:
            cursor = connection.execute("INSERT INTO users(username, is_active, created_at) VALUES (?, 1, datetime('now'))", (username,))
            return int(cursor.lastrowid)

    def get_user(self, user_id: int) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute("SELECT id, username, is_active, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def project_owner(self, project_id: int) -> Optional[int]:
        with self._connect() as connection:
            row = connection.execute("SELECT owner_id FROM projects WHERE id = ?", (project_id,)).fetchone()
        return int(row["owner_id"]) if row and row["owner_id"] is not None else None

    def user_can_access_project(self, user_id: int, project_id: int) -> bool:
        owner_id = self.project_owner(project_id)
        return owner_id is not None and owner_id == int(user_id)

    def list_project_ids(self, user_id: int) -> list[int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id FROM projects WHERE owner_id = ? ORDER BY id", (user_id,)).fetchall()
        return [int(row["id"]) for row in rows]

    def assign_project(self, project_id: int, owner_id: int) -> bool:
        if not self.get_user(owner_id):
            raise ValueError("owner user does not exist")
        with self._connect() as connection:
            row = connection.execute("SELECT owner_id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                return False
            current_owner = row["owner_id"]
            if current_owner is not None and int(current_owner) != int(owner_id):
                return False
            cursor = connection.execute("UPDATE projects SET owner_id = ? WHERE id = ?", (owner_id, project_id))
            return cursor.rowcount > 0

    def bind_new_project(self, project_id: int, owner_id: int) -> bool:
        """Bind a project returned by the create-project route to its session owner.

        The legacy projects schema defaults newly inserted rows to the bootstrap
        admin (id=1). Only this narrowly-scoped creation path may transfer that
        default owner; normal assignment remains takeover-safe via assign_project.
        """
        if not self.get_user(owner_id):
            raise ValueError("owner user does not exist")
        with self._connect() as connection:
            row = connection.execute("SELECT owner_id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                return False
            current_owner = row["owner_id"]
            if current_owner is None or int(current_owner) == int(owner_id):
                return connection.execute(
                    "UPDATE projects SET owner_id = ? WHERE id = ?",
                    (owner_id, project_id),
                ).rowcount > 0
            if int(current_owner) != self.BOOTSTRAP_USER_ID:
                return False
            return connection.execute(
                "UPDATE projects SET owner_id = ? WHERE id = ? AND owner_id = ?",
                (owner_id, project_id, self.BOOTSTRAP_USER_ID),
            ).rowcount > 0
