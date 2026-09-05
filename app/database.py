from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class Database:
    """
    طبقة قاعدة البيانات الرئيسية للنظام.

    SQLite محلية، مع:
    - المشاريع
    - المحادثات
    - بطاقات العمل
    - الموافقات
    - جلسات المتصفح
    - الأسرار المشفرة
    - الأحداث والسجل
    - الملفات المرفوعة
    """

    def __init__(self, database_path: str):
        self.database_path = Path(database_path)

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    # =========================================================
    # الاتصال والمساعدات
    # =========================================================

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            check_same_thread=False,
        )

        connection.row_factory = sqlite3.Row

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA journal_mode = WAL"
        )

        connection.execute(
            "PRAGMA busy_timeout = 5000"
        )

        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def _row_to_dict(
        row: Optional[sqlite3.Row],
    ) -> Optional[dict[str, Any]]:
        if row is None:
            return None

        return dict(row)

    @staticmethod
    def _rows_to_dicts(
        rows: list[sqlite3.Row],
    ) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def _decode_json(
        value: Any,
        default: Any = None,
    ) -> Any:
        if value is None:
            return default

        if not isinstance(value, str):
            return value

        try:
            return json.loads(value)
        except Exception:
            return default

    # =========================================================
    # تهيئة قاعدة البيانات
    # =========================================================

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    workflow_type TEXT DEFAULT 'assistant',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
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
                    error_message TEXT DEFAULT '',
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
                    status TEXT DEFAULT 'active',
                    storage_path TEXT DEFAULT '',
                    last_url TEXT DEFAULT '',
                    session_expired INTEGER DEFAULT 0,
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
                    project_id INTEGER,
                    event_type TEXT NOT NULL,
                    message TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,

                    FOREIGN KEY(project_id)
                        REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS uploaded_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    filename TEXT NOT NULL,
                    path TEXT DEFAULT '',
                    content_size INTEGER DEFAULT 0,
                    analysis TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_projects_status
                    ON projects(status);

                CREATE INDEX IF NOT EXISTS idx_chat_project
                    ON chat_messages(project_id);

                CREATE INDEX IF NOT EXISTS idx_work_cards_project
                    ON work_cards(project_id);

                CREATE INDEX IF NOT EXISTS idx_work_cards_status
                    ON work_cards(status);

                CREATE INDEX IF NOT EXISTS idx_approvals_card
                    ON approvals(work_card_id);

                CREATE INDEX IF NOT EXISTS idx_browser_project
                    ON browser_sessions(project_id);

                CREATE INDEX IF NOT EXISTS idx_events_project
                    ON events(project_id);

                CREATE INDEX IF NOT EXISTS idx_events_created
                    ON events(created_at);

                CREATE INDEX IF NOT EXISTS idx_uploaded_project
                    ON uploaded_files(project_id);
                """
            )

            self._migrate_uploaded_files(
                connection
            )

    # =========================================================
    # ترقية قاعدة البيانات القديمة
    # =========================================================

    def _migrate_uploaded_files(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        """
        يضيف الأعمدة الجديدة إلى قاعدة البيانات
        القديمة بدون حذف البيانات الموجودة.
        """

        rows = connection.execute(
            "PRAGMA table_info(uploaded_files)"
        ).fetchall()

        existing_columns = {
            row["name"]
            for row in rows
        }

        migrations = {
            "project_id": (
                "ALTER TABLE uploaded_files "
                "ADD COLUMN project_id INTEGER"
            ),
            "path": (
                "ALTER TABLE uploaded_files "
                "ADD COLUMN path TEXT DEFAULT ''"
            ),
            "updated_at": (
                "ALTER TABLE uploaded_files "
                "ADD COLUMN updated_at TEXT"
            ),
        }

        for column, sql in migrations.items():
            if column not in existing_columns:
                connection.execute(sql)

        connection.execute(
            """
            UPDATE uploaded_files
            SET updated_at = created_at
            WHERE updated_at IS NULL
               OR updated_at = ''
            """
        )

    # =========================================================
    # تنفيذ SQL
    # =========================================================

    def execute_script(
        self,
        sql: str,
    ) -> None:
        with self._connect() as connection:
            connection.executescript(sql)

    # =========================================================
    # المشاريع
    # =========================================================

    def create_project(
        self,
        name: str,
        description: str = "",
        workflow_type: str = "assistant",
        status: str = "active",
    ) -> dict[str, Any]:

        now = self._now()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO projects (
                    name,
                    description,
                    status,
                    workflow_type,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    description,
                    status,
                    workflow_type,
                    now,
                    now,
                ),
            )

            project_id = cursor.lastrowid

        return self.get_project(
            int(project_id)
        )

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

    def list_projects(
        self,
        limit: int = 200,
    ) -> list[dict[str, Any]]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM projects
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return self._rows_to_dicts(rows)

    def update_project(
        self,
        project_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        workflow_type: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:

        current = self.get_project(
            project_id
        )

        if current is None:
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

        new_workflow = (
            workflow_type
            if workflow_type is not None
            else current["workflow_type"]
        )

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE projects
                SET
                    name = ?,
                    description = ?,
                    status = ?,
                    workflow_type = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    new_name,
                    new_description,
                    new_status,
                    new_workflow,
                    self._now(),
                    project_id,
                ),
            )

        return self.get_project(
            project_id
        )

    def delete_project(
        self,
        project_id: int,
    ) -> bool:

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM projects
                WHERE id = ?
                """,
                (project_id,),
            )

            return cursor.rowcount > 0

    # =========================================================
    # المحادثات
    # =========================================================

    def create_chat_message(
        self,
        project_id: Optional[int],
        role: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:

        now = self._now()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO chat_messages (
                    project_id,
                    role,
                    content,
                    metadata,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    role,
                    content,
                    self._json(
                        metadata or {}
                    ),
                    now,
                ),
            )

            message_id = cursor.lastrowid

            row = connection.execute(
                """
                SELECT *
                FROM chat_messages
                WHERE id = ?
                """,
                (message_id,),
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
                    ORDER BY created_at ASC
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
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (
                        project_id,
                        limit,
                    ),
                ).fetchall()

        return self._rows_to_dicts(rows)

    # =========================================================
    # بطاقات العمل
    # =========================================================

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
                INSERT INTO work_cards (
                    project_id,
                    title,
                    description,
                    workflow_type,
                    status,
                    error_message,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    project_id,
                    title,
                    description,
                    workflow_type,
                    status,
                    self._json(
                        metadata or {}
                    ),
                    now,
                    now,
                ),
            )

            card_id = cursor.lastrowid

        return self.get_work_card(
            int(card_id)
        ) or {}

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

        return self._row_to_dict(row)

    def list_work_cards(
        self,
        project_id: Optional[int] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:

        with self._connect() as connection:

            if project_id is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM work_cards
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM work_cards
                    WHERE project_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (
                        project_id,
                        limit,
                    ),
                ).fetchall()

        return self._rows_to_dicts(rows)

    def list_all_work_cards(
        self,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self.list_work_cards(
            project_id=None,
            limit=limit,
        )

    def update_work_card(
        self,
        card_id: int,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:

        current = self.get_work_card(
            card_id
        )

        if current is None:
            return None

        new_status = (
            status
            if status is not None
            else current["status"]
        )

        new_error = (
            error_message
            if error_message is not None
            else current.get(
                "error_message",
                "",
            )
        )

        old_metadata = self._decode_json(
            current.get("metadata"),
            {},
        )

        if not isinstance(old_metadata, dict):
            old_metadata = {}

        if metadata is not None:
            old_metadata.update(
                metadata
            )

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
                    self._json(
                        old_metadata
                    ),
                    self._now(),
                    card_id,
                ),
            )

        return self.get_work_card(
            card_id
        )

    # =========================================================
    # الموافقات
    # =========================================================

    def create_approval(
        self,
        work_card_id: int,
        action: str,
        note: str = "",
    ) -> dict[str, Any]:

        now = self._now()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO approvals (
                    work_card_id,
                    action,
                    note,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    work_card_id,
                    action,
                    note,
                    now,
                ),
            )

            approval_id = cursor.lastrowid

            row = connection.execute(
                """
                SELECT *
                FROM approvals
                WHERE id = ?
                """,
                (approval_id,),
            ).fetchone()

        return self._row_to_dict(row) or {}

    def list_approvals(
        self,
        work_card_id: Optional[int] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:

        with self._connect() as connection:

            if work_card_id is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM approvals
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM approvals
                    WHERE work_card_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (
                        work_card_id,
                        limit,
                    ),
                ).fetchall()

        return self._rows_to_dicts(rows)

    # =========================================================
    # جلسات المتصفح
    # =========================================================

    def upsert_browser_session(
        self,
        project_id: int,
        site: str,
        status: str = "active",
        storage_path: str = "",
        last_url: str = "",
        session_expired: bool = False,
    ) -> dict[str, Any]:

        now = self._now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO browser_sessions (
                    project_id,
                    site,
                    status,
                    storage_path,
                    last_url,
                    session_expired,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, site)
                DO UPDATE SET
                    status = excluded.status,
                    storage_path = excluded.storage_path,
                    last_url = excluded.last_url,
                    session_expired = excluded.session_expired,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    site,
                    status,
                    storage_path,
                    last_url,
                    1 if session_expired else 0,
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

    def list_browser_sessions(
        self,
        project_id: Optional[int] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:

        with self._connect() as connection:

            if project_id is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM browser_sessions
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM browser_sessions
                    WHERE project_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (
                        project_id,
                        limit,
                    ),
                ).fetchall()

        return self._rows_to_dicts(rows)

    def update_browser_session(
        self,
        session_id: int,
        status: Optional[str] = None,
        last_url: Optional[str] = None,
        session_expired: Optional[bool] = None,
        storage_path: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:

        with self._connect() as connection:
            current = connection.execute(
                """
                SELECT *
                FROM browser_sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()

            if current is None:
                return None

            current = dict(current)

            connection.execute(
                """
                UPDATE browser_sessions
                SET
                    status = ?,
                    last_url = ?,
                    session_expired = ?,
                    storage_path = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status
                    if status is not None
                    else current["status"],
                    last_url
                    if last_url is not None
                    else current["last_url"],
                    (
                        1 if session_expired else 0
                    )
                    if session_expired is not None
                    else current["session_expired"],
                    storage_path
                    if storage_path is not None
                    else current["storage_path"],
                    self._now(),
                    session_id,
                ),
            )

            row = connection.execute(
                """
                SELECT *
                FROM browser_sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()

        return self._row_to_dict(row)

    def delete_browser_session(
        self,
        session_id: int,
    ) -> bool:

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM browser_sessions
                WHERE id = ?
                """,
                (session_id,),
            )

            return cursor.rowcount > 0

    # =========================================================
    # الأسرار
    # =========================================================

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
                INSERT INTO secrets (
                    name,
                    encrypted_value,
                    description,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name,
                    encrypted_value,
                    description,
                    now,
                    now,
                ),
            )

            secret_id = cursor.lastrowid

        return self.get_secret(
            int(secret_id)
        ) or {}

    def get_secret(
        self,
        secret_id: int,
    ) -> Optional[dict[str, Any]]:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM secrets
                WHERE id = ?
                """,
                (secret_id,),
            ).fetchone()

        return self._row_to_dict(row)

    def get_secret_by_name(
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

    def list_secrets(
        self,
        limit: int = 200,
    ) -> list[dict[str, Any]]:

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
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return self._rows_to_dicts(rows)

    def update_secret(
        self,
        secret_id: int,
        encrypted_value: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:

        current = self.get_secret(
            secret_id
        )

        if current is None:
            return None

        new_value = (
            encrypted_value
            if encrypted_value is not None
            else current["encrypted_value"]
        )

        new_description = (
            description
            if description is not None
            else current["description"]
        )

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE secrets
                SET
                    encrypted_value = ?,
                    description = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    new_value,
                    new_description,
                    self._now(),
                    secret_id,
                ),
            )

        return self.get_secret(
            secret_id
        )

    def delete_secret(
        self,
        secret_id: int,
    ) -> bool:

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM secrets
                WHERE id = ?
                """,
                (secret_id,),
            )

            return cursor.rowcount > 0

    # =========================================================
    # الأحداث والسجل
    # =========================================================

    def create_event(
        self,
        event_type: str,
        message: str = "",
        project_id: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:

        now = self._now()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO events (
                    project_id,
                    event_type,
                    message,
                    metadata,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    event_type,
                    message,
                    self._json(
                        metadata or {}
                    ),
                    now,
                ),
            )

            event_id = cursor.lastrowid

            row = connection.execute(
                """
                SELECT *
                FROM events
                WHERE id = ?
                """,
                (event_id,),
            ).fetchone()

        return self._row_to_dict(row) or {}

    def list_events(
        self,
        project_id: Optional[int] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:

        with self._connect() as connection:

            if project_id is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM events
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM events
                    WHERE project_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (
                        project_id,
                        limit,
                    ),
                ).fetchall()

        return self._rows_to_dicts(rows)

    # =========================================================
    # الملفات المرفوعة
    # =========================================================

    def create_uploaded_file(
        self,
        project_id: Optional[int],
        filename: str,
        path: str,
        size: int = 0,
        content_size: Optional[int] = None,
        analysis: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:

        now = self._now()

        final_size = (
            content_size
            if content_size is not None
            else size
        )

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO uploaded_files (
                    project_id,
                    filename,
                    path,
                    content_size,
                    analysis,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    filename,
                    path,
                    final_size,
                    self._json(
                        analysis or {}
                    ),
                    now,
                    now,
                ),
            )

            file_id = cursor.lastrowid

            row = connection.execute(
                """
                SELECT *
                FROM uploaded_files
                WHERE id = ?
                """,
                (file_id,),
            ).fetchone()

        return self._row_to_dict(row) or {}

    def get_uploaded_file(
        self,
        file_id: int,
    ) -> Optional[dict[str, Any]]:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM uploaded_files
                WHERE id = ?
                """,
                (file_id,),
            ).fetchone()

        return self._row_to_dict(row)

    def list_uploaded_files(
        self,
        project_id: Optional[int] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:

        with self._connect() as connection:

            if project_id is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM uploaded_files
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM uploaded_files
                    WHERE project_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (
                        project_id,
                        limit,
                    ),
                ).fetchall()

        return self._rows_to_dicts(rows)

    def update_uploaded_file_analysis(
        self,
        file_id: int,
        analysis: dict[str, Any],
    ) -> Optional[dict[str, Any]]:

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE uploaded_files
                SET
                    analysis = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    self._json(analysis),
                    self._now(),
                    file_id,
                ),
            )

        return self.get_uploaded_file(
            file_id
        )

    def delete_uploaded_file(
        self,
        file_id: int,
    ) -> bool:

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM uploaded_files
                WHERE id = ?
                """,
                (file_id,),
            )

            return cursor.rowcount > 0
