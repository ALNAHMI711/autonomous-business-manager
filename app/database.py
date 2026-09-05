from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class Database:
    def __init__(self, database_path: str):
        self.database_path = Path(database_path)

        if self.database_path.parent:
            self.database_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
        if row is None:
            return None
        return dict(row)

    @staticmethod
    def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id)
                        REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS work_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    workflow_type TEXT DEFAULT 'assistant',
                    status TEXT DEFAULT 'queued',
                    error_message TEXT,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id)
                        REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_card_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(work_card_id)
                        REFERENCES work_cards(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS browser_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    site TEXT NOT NULL,
                    profile_path TEXT,
                    storage_state_path TEXT,
                    status TEXT DEFAULT 'closed',
                    current_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, site),
                    FOREIGN KEY(project_id)
                        REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS secrets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    encrypted_value TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    project_id INTEGER,
                    work_card_id INTEGER,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id)
                        REFERENCES projects(id)
                        ON DELETE SET NULL,
                    FOREIGN KEY(work_card_id)
                        REFERENCES work_cards(id)
                        ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS uploaded_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    content_size INTEGER DEFAULT 0,
                    analysis TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_projects_status
                    ON projects(status);

                CREATE INDEX IF NOT EXISTS idx_chat_project
                    ON chat_messages(project_id);

                CREATE INDEX IF NOT EXISTS idx_work_cards_project
                    ON work_cards(project_id);

                CREATE INDEX IF NOT EXISTS idx_work_cards_status
                    ON work_cards(status);

                CREATE INDEX IF NOT EXISTS idx_events_created
                    ON events(created_at);

                CREATE INDEX IF NOT EXISTS idx_browser_project
                    ON browser_sessions(project_id);
                """
            )

    def execute_script(self, sql: str) -> None:
        with self._connect() as connection:
            connection.executescript(sql)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def create_project(
        self,
        name: str,
        description: str = "",
    ) -> dict[str, Any]:
        now = self._now()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO projects
                    (name, description, status, created_at, updated_at)
                VALUES
                    (?, ?, 'active', ?, ?)
                """,
                (
                    name,
                    description,
                    now,
                    now,
                ),
            )

            project_id = cursor.lastrowid

            row = connection.execute(
                """
                SELECT *
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()

        return self._row_to_dict(row) or {}

    def get_project(
        self,
        project_id: int,
    ) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()

        return self._row_to_dict(row)

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM projects
                ORDER BY id DESC
                """
            ).fetchall()

        return self._rows_to_dicts(rows)

    def update_project(
        self,
        project_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        current = self.get_project(project_id)

        if not current:
            return None

        new_name = (
            name
            if name is not None
            else current["name"]
        )

        new_description = (
            description
            if description is not None
            else current["description"]
        )

        new_status = (
            status
            if status is not None
            else current["status"]
        )

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE projects
                SET
                    name = ?,
                    description = ?,
                    status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    new_name,
                    new_description,
                    new_status,
                    self._now(),
                    project_id,
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()

        return self._row_to_dict(row)

    def delete_project(self, project_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM projects
                WHERE id = ?
                """,
                (project_id,),
            )

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def create_chat_message(
        self,
        role: str,
        content: str,
        project_id: Optional[int] = None,
    ) -> dict[str, Any]:
        now = self._now()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO chat_messages
                    (project_id, role, content, created_at)
                VALUES
                    (?, ?, ?, ?)
                """,
                (
                    project_id,
                    role,
                    content,
                    now,
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM chat_messages
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        return self._row_to_dict(row) or {}

    def list_chat_messages(
        self,
        project_id: Optional[int],
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if project_id is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM chat_messages
                    WHERE project_id IS NULL
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM chat_messages
                    WHERE project_id = ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (
                        project_id,
                        limit,
                    ),
                ).fetchall()

        return self._rows_to_dicts(rows)

    # ------------------------------------------------------------------
    # Work cards
    # ------------------------------------------------------------------

    def create_work_card(
        self,
        project_id: Optional[int],
        title: str,
        description: str = "",
        workflow_type: str = "assistant",
        status: str = "queued",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        now = self._now()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO work_cards
                    (
                        project_id,
                        title,
                        description,
                        workflow_type,
                        status,
                        metadata,
                        created_at,
                        updated_at
                    )
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    title,
                    description,
                    workflow_type,
                    status,
                    self._json(metadata or {}),
                    now,
                    now,
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM work_cards
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        return self._row_to_dict(row) or {}

    def get_work_card(
        self,
        card_id: int,
    ) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM work_cards
                WHERE id = ?
                """,
                (card_id,),
            ).fetchone()

        result = self._row_to_dict(row)

        if result and isinstance(result.get("metadata"), str):
            try:
                result["metadata"] = json.loads(result["metadata"])
            except json.JSONDecodeError:
                pass

        return result

    def list_work_cards(
        self,
        project_id: int,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM work_cards
                WHERE project_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (
                    project_id,
                    limit,
                ),
            ).fetchall()

        results = self._rows_to_dicts(rows)

        for result in results:
            if isinstance(result.get("metadata"), str):
                try:
                    result["metadata"] = json.loads(
                        result["metadata"]
                    )
                except json.JSONDecodeError:
                    pass

        return results

    def list_all_work_cards(
        self,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM work_cards
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        results = self._rows_to_dicts(rows)

        for result in results:
            if isinstance(result.get("metadata"), str):
                try:
                    result["metadata"] = json.loads(
                        result["metadata"]
                    )
                except json.JSONDecodeError:
                    pass

        return results

    def update_work_card(
        self,
        card_id: int,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        current = self.get_work_card(card_id)

        if not current:
            return None

        new_status = (
            status
            if status is not None
            else current["status"]
        )

        new_error = (
            error_message
            if error_message is not None
            else current.get("error_message")
        )

        current_metadata = current.get("metadata") or {}

        if metadata is not None:
            current_metadata = metadata

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE work_cards
                SET
                    status = ?,
                    error_message = ?,
                    metadata = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    new_error,
                    self._json(current_metadata),
                    self._now(),
                    card_id,
                ),
            )

        return self.get_work_card(card_id)

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------

    def create_approval(
        self,
        work_card_id: int,
        action: str,
        note: str = "",
    ) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO approvals
                    (
                        work_card_id,
                        action,
                        note,
                        created_at
                    )
                VALUES
                    (?, ?, ?, ?)
                """,
                (
                    work_card_id,
                    action,
                    note,
                    self._now(),
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM approvals
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        return self._row_to_dict(row) or {}

    def list_approvals(
        self,
        work_card_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if work_card_id is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM approvals
                    ORDER BY id DESC
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM approvals
                    WHERE work_card_id = ?
                    ORDER BY id DESC
                    """,
                    (work_card_id,),
                ).fetchall()

        return self._rows_to_dicts(rows)

    # ------------------------------------------------------------------
    # Browser sessions
    # ------------------------------------------------------------------

    def upsert_browser_session(
        self,
        project_id: int,
        site: str,
        profile_path: Optional[str] = None,
        storage_state_path: Optional[str] = None,
        status: str = "open",
        current_url: Optional[str] = None,
    ) -> dict[str, Any]:
        now = self._now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO browser_sessions
                    (
                        project_id,
                        site,
                        profile_path,
                        storage_state_path,
                        status,
                        current_url,
                        created_at,
                        updated_at
                    )
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, site)
                DO UPDATE SET
                    profile_path = excluded.profile_path,
                    storage_state_path = excluded.storage_state_path,
                    status = excluded.status,
                    current_url = excluded.current_url,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    site,
                    profile_path,
                    storage_state_path,
                    status,
                    current_url,
                    now,
                    now,
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM browser_sessions
                WHERE project_id = ?
                  AND site = ?
                """,
                (
                    project_id,
                    site,
                ),
            ).fetchone()

        return self._row_to_dict(row) or {}

    def get_browser_session(
        self,
        project_id: int,
        site: str,
    ) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM browser_sessions
                WHERE project_id = ?
                  AND site = ?
                """,
                (
                    project_id,
                    site,
                ),
            ).fetchone()

        return self._row_to_dict(row)

    def list_browser_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM browser_sessions
                ORDER BY updated_at DESC
                """
            ).fetchall()

        return self._rows_to_dicts(rows)

    def update_browser_session(
        self,
        project_id: int,
        site: str,
        status: Optional[str] = None,
        current_url: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        current = self.get_browser_session(
            project_id,
            site,
        )

        if not current:
            return None

        new_status = (
            status
            if status is not None
            else current["status"]
        )

        new_url = (
            current_url
            if current_url is not None
            else current["current_url"]
        )

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE browser_sessions
                SET
                    status = ?,
                    current_url = ?,
                    updated_at = ?
                WHERE project_id = ?
                  AND site = ?
                """,
                (
                    new_status,
                    new_url,
                    self._now(),
                    project_id,
                    site,
                ),
            )

        return self.get_browser_session(
            project_id,
            site,
        )

    # ------------------------------------------------------------------
    # Secrets
    # ------------------------------------------------------------------

    def create_secret(
        self,
        name: str,
        encrypted_value: str,
        description: str = "",
    ) -> dict[str, Any]:
        now = self._now()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO secrets
                    (
                        name,
                        encrypted_value,
                        description,
                        created_at,
                        updated_at
                    )
                VALUES
                    (?, ?, ?, ?, ?)
                ON CONFLICT(name)
                DO UPDATE SET
                    encrypted_value = excluded.encrypted_value,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (
                    name,
                    encrypted_value,
                    description,
                    now,
                    now,
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM secrets
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

            if row is None:
                row = connection.execute(
                    """
                    SELECT *
                    FROM secrets
                    WHERE name = ?
                    """,
                    (name,),
                ).fetchone()

        return self._row_to_dict(row) or {}

    def get_secret(
        self,
        name: str,
    ) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM secrets
                WHERE name = ?
                """,
                (name,),
            ).fetchone()

        return self._row_to_dict(row)

    def list_secrets_metadata(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    name,
                    description,
                    created_at,
                    updated_at
                FROM secrets
                ORDER BY name ASC
                """
            ).fetchall()

        return self._rows_to_dicts(rows)

    def delete_secret(
        self,
        name: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM secrets
                WHERE name = ?
                """,
                (name,),
            )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def create_event(
        self,
        event_type: str,
        message: str,
        project_id: Optional[int] = None,
        work_card_id: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO events
                    (
                        event_type,
                        message,
                        project_id,
                        work_card_id,
                        metadata,
                        created_at
                    )
                VALUES
                    (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    message,
                    project_id,
                    work_card_id,
                    self._json(metadata or {}),
                    self._now(),
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM events
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        result = self._row_to_dict(row) or {}

        if isinstance(result.get("metadata"), str):
            try:
                result["metadata"] = json.loads(
                    result["metadata"]
                )
            except json.JSONDecodeError:
                pass

        return result

    def list_events(
        self,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        results = self._rows_to_dicts(rows)

        for result in results:
            if isinstance(result.get("metadata"), str):
                try:
                    result["metadata"] = json.loads(
                        result["metadata"]
                    )
                except json.JSONDecodeError:
                    pass

        return results

    # ------------------------------------------------------------------
    # Uploaded files
    # ------------------------------------------------------------------

    def save_uploaded_file(
        self,
        filename: str,
        content_size: int,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO uploaded_files
                    (
                        filename,
                        content_size,
                        analysis,
                        created_at
                    )
                VALUES
                    (?, ?, ?, ?)
                """,
                (
                    filename,
                    content_size,
                    self._json(analysis),
                    self._now(),
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM uploaded_files
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        result = self._row_to_dict(row) or {}

        if isinstance(result.get("analysis"), str):
            try:
                result["analysis"] = json.loads(
                    result["analysis"]
                )
            except json.JSONDecodeError:
                pass

        return result

    def list_uploaded_files(
        self,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM uploaded_files
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        results = self._rows_to_dicts(rows)

        for result in results:
            if isinstance(result.get("analysis"), str):
                try:
                    result["analysis"] = json.loads(
                        result["analysis"]
                    )
                except json.JSONDecodeError:
                    pass

        return results
