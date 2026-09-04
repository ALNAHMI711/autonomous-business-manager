
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Database:
    def __init__(self, database_path: str):
        self.database_path = database_path

        Path(database_path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
        )

        connection.row_factory = sqlite3.Row

        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    workflow_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    description TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY(project_id)
                        REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS work_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    title TEXT NOT NULL,
                    workflow_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    description TEXT NOT NULL,
                    next_step TEXT,
                    error_message TEXT,
                    requires_approval INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY(project_id)
                        REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_card_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY(work_card_id)
                        REFERENCES work_cards(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS browser_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    site_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    storage_path TEXT,
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY(project_id)
                        REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS secrets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    encrypted_value TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY(project_id)
                        REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS uploaded_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    original_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY(project_id)
                        REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_project
                    ON chat_messages(project_id);

                CREATE INDEX IF NOT EXISTS idx_cards_project
                    ON work_cards(project_id);

                CREATE INDEX IF NOT EXISTS idx_cards_status
                    ON work_cards(status);

                CREATE INDEX IF NOT EXISTS idx_events_project
                    ON events(project_id);

                CREATE INDEX IF NOT EXISTS idx_sessions_project
                    ON browser_sessions(project_id);
                """
            )

    def execute_script(
        self,
        sql: str,
    ) -> None:
        with self.connection() as db:
            db.executescript(sql)

    # ---------------------------------------------------------------
    # Projects
    # ---------------------------------------------------------------

    def create_project(
        self,
        name: str,
        workflow_type: str,
        description: str = "",
    ) -> int:
        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO projects
                    (name, workflow_type, description)
                VALUES (?, ?, ?)
                """,
                (
                    name,
                    workflow_type,
                    description,
                ),
            )

            return int(cursor.lastrowid)

    def get_project(
        self,
        project_id: int,
    ) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                """
                SELECT *
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()

            return dict(row) if row else None

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT *
                FROM projects
                ORDER BY id DESC
                """
            ).fetchall()

            return [dict(row) for row in rows]

    def update_project_status(
        self,
        project_id: int,
        status: str,
    ) -> None:
        with self.connection() as db:
            db.execute(
                """
                UPDATE projects
                SET status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    status,
                    project_id,
                ),
            )

    # ---------------------------------------------------------------
    # Chat
    # ---------------------------------------------------------------

    def add_message(
        self,
        role: str,
        content: str,
        project_id: int | None = None,
    ) -> int:
        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO chat_messages
                    (project_id, role, content)
                VALUES (?, ?, ?)
                """,
                (
                    project_id,
                    role,
                    content,
                ),
            )

            return int(cursor.lastrowid)

    def get_messages(
        self,
        project_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.connection() as db:
            if project_id is None:
                rows = db.execute(
                    """
                    SELECT *
                    FROM chat_messages
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT *
                    FROM chat_messages
                    WHERE project_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (
                        project_id,
                        limit,
                    ),
                ).fetchall()

            return [
                dict(row)
                for row in reversed(rows)
            ]

    # ---------------------------------------------------------------
    # Work Cards
    # ---------------------------------------------------------------

    def create_work_card(
        self,
        title: str,
        workflow_type: str,
        description: str,
        project_id: int | None = None,
        status: str = "queued",
        next_step: str | None = None,
        requires_approval: bool = False,
    ) -> int:
        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO work_cards (
                    project_id,
                    title,
                    workflow_type,
                    status,
                    description,
                    next_step,
                    requires_approval
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    title,
                    workflow_type,
                    status,
                    description,
                    next_step,
                    1 if requires_approval else 0,
                ),
            )

            return int(cursor.lastrowid)

    def get_work_card(
        self,
        card_id: int,
    ) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                """
                SELECT *
                FROM work_cards
                WHERE id = ?
                """,
                (card_id,),
            ).fetchone()

            return dict(row) if row else None

    def list_work_cards(
        self,
        project_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.connection() as db:
            if project_id is None:
                rows = db.execute(
                    """
                    SELECT *
                    FROM work_cards
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = db.execute(
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

            return [dict(row) for row in rows]

    def update_work_card(
        self,
        card_id: int,
        status: str | None = None,
        next_step: str | None = None,
        error_message: str | None = None,
        requires_approval: bool | None = None,
    ) -> None:
        fields = []
        values: list[Any] = []

        if status is not None:
            fields.append("status = ?")
            values.append(status)

        if next_step is not None:
            fields.append("next_step = ?")
            values.append(next_step)

        if error_message is not None:
            fields.append("error_message = ?")
            values.append(error_message)

        if requires_approval is not None:
            fields.append("requires_approval = ?")
            values.append(
                1 if requires_approval else 0
            )

        if not fields:
            return

        fields.append(
            "updated_at = CURRENT_TIMESTAMP"
        )

        values.append(card_id)

        query = f"""
            UPDATE work_cards
            SET {", ".join(fields)}
            WHERE id = ?
        """

        with self.connection() as db:
            db.execute(query, values)

    def add_approval(
        self,
        work_card_id: int,
        action: str,
        decision: str,
    ) -> int:
        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO approvals
                    (work_card_id, action, decision)
                VALUES (?, ?, ?)
                """,
                (
                    work_card_id,
                    action,
                    decision,
                ),
            )

            return int(cursor.lastrowid)

    # ---------------------------------------------------------------
    # Browser Sessions
    # ---------------------------------------------------------------

    def create_browser_session(
        self,
        site_name: str,
        project_id: int | None = None,
        storage_path: str | None = None,
    ) -> int:
        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO browser_sessions
                    (project_id, site_name, storage_path)
                VALUES (?, ?, ?)
                """,
                (
                    project_id,
                    site_name,
                    storage_path,
                ),
            )

            return int(cursor.lastrowid)

    def update_browser_session(
        self,
        session_id: int,
        status: str,
    ) -> None:
        with self.connection() as db:
            db.execute(
                """
                UPDATE browser_sessions
                SET status = ?,
                    last_checked_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    status,
                    session_id,
                ),
            )

    def get_browser_session(
        self,
        session_id: int,
    ) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                """
                SELECT *
                FROM browser_sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()

            return dict(row) if row else None

    # ---------------------------------------------------------------
    # Secrets
    # ---------------------------------------------------------------

    def save_secret(
        self,
        name: str,
        encrypted_value: str,
    ) -> None:
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO secrets
                    (name, encrypted_value)
                VALUES (?, ?)
                ON CONFLICT(name)
                DO UPDATE SET
                    encrypted_value = excluded.encrypted_value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    name,
                    encrypted_value,
                ),
            )

    def get_secret(
        self,
        name: str,
    ) -> str | None:
        with self.connection() as db:
            row = db.execute(
                """
                SELECT encrypted_value
                FROM secrets
                WHERE name = ?
                """,
                (name,),
            ).fetchone()

            return (
                row["encrypted_value"]
                if row
                else None
            )

    # ---------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------

    def add_event(
        self,
        event_type: str,
        message: str,
        project_id: int | None = None,
        metadata_json: str | None = None,
    ) -> int:
        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO events (
                    project_id,
                    event_type,
                    message,
                    metadata_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    project_id,
                    event_type,
                    message,
                    metadata_json,
                ),
            )

            return int(cursor.lastrowid)

    def list_events(
        self,
        project_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.connection() as db:
            if project_id is None:
                rows = db.execute(
                    """
                    SELECT *
                    FROM events
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT *
                    FROM events
                    WHERE project_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (
                        project_id,
                        limit,
                    ),
                ).fetchall()

            return [dict(row) for row in rows]

    # ---------------------------------------------------------------
    # Uploaded Files
    # ---------------------------------------------------------------

    def add_uploaded_file(
        self,
        original_name: str,
        stored_path: str,
        size_bytes: int,
        sha256: str,
        project_id: int | None = None,
    ) -> int:
        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO uploaded_files (
                    project_id,
                    original_name,
                    stored_path,
                    size_bytes,
                    sha256
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    original_name,
                    stored_path,
                    size_bytes,
                    sha256,
                ),
            )

            return int(cursor.lastrowid)
