from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value

    if not value:
        return utc_now()

    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return utc_now()


# =========================================================
# Project
# =========================================================

@dataclass
class Project:
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    status: str = "active"
    workflow_type: str = "assistant"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


# =========================================================
# Chat Message
# =========================================================

@dataclass
class ChatMessage:
    id: Optional[int] = None
    project_id: Optional[int] = None
    role: str = "user"
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


# =========================================================
# Work Card
# =========================================================

@dataclass
class WorkCard:
    id: Optional[int] = None
    project_id: Optional[int] = None
    title: str = ""
    description: str = ""
    workflow_type: str = "assistant"
    status: str = "queued"
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def task_type(self) -> str:
        """
        توافق خلفي مع الكود القديم.
        """
        return self.workflow_type

    @property
    def payload(self) -> dict[str, Any]:
        """
        توافق خلفي مع النسخ القديمة من النظام.
        """
        return self.metadata


# =========================================================
# Approval
# =========================================================

@dataclass
class Approval:
    id: Optional[int] = None
    work_card_id: Optional[int] = None
    action: str = ""
    note: str = ""
    created_at: datetime = field(default_factory=utc_now)


# =========================================================
# Browser Session
# =========================================================

@dataclass
class BrowserSession:
    id: Optional[int] = None
    project_id: Optional[int] = None
    site: str = ""
    status: str = "active"
    storage_path: str = ""
    last_url: str = ""
    session_expired: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def current_url(self) -> str:
        """
        توافق خلفي مع الاسم القديم.
        """
        return self.last_url


# =========================================================
# Secret
# =========================================================

@dataclass
class Secret:
    id: Optional[int] = None
    name: str = ""
    encrypted_value: str = ""
    description: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def secret_type(self) -> str:
        """
        توافق خلفي مع النسخ السابقة.
        """
        return "generic"


# =========================================================
# Event
# =========================================================

@dataclass
class Event:
    id: Optional[int] = None
    project_id: Optional[int] = None
    event_type: str = ""
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


# =========================================================
# Uploaded File
# =========================================================

@dataclass
class UploadedFile:
    id: Optional[int] = None
    project_id: Optional[int] = None
    filename: str = ""
    path: str = ""
    content_size: int = 0
    analysis: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def stored_path(self) -> str:
        return self.path

    @property
    def size(self) -> int:
        return self.content_size

    @property
    def analysis_status(self) -> str:
        if not self.analysis:
            return "pending"

        return str(
            self.analysis.get(
                "status",
                "completed",
            )
        )


# =========================================================
# Conversion Helpers
# =========================================================

def project_from_dict(
    data: dict[str, Any],
) -> Project:
    return Project(
        id=data.get("id"),
        name=data.get("name", ""),
        description=data.get(
            "description",
            "",
        ),
        status=data.get(
            "status",
            "active",
        ),
        workflow_type=data.get(
            "workflow_type",
            "assistant",
        ),
        created_at=parse_datetime(
            data.get("created_at")
        ),
        updated_at=parse_datetime(
            data.get("updated_at")
        ),
    )


def chat_message_from_dict(
    data: dict[str, Any],
) -> ChatMessage:
    metadata = data.get(
        "metadata",
        {},
    )

    if not isinstance(metadata, dict):
        metadata = {}

    return ChatMessage(
        id=data.get("id"),
        project_id=data.get(
            "project_id"
        ),
        role=data.get(
            "role",
            "user",
        ),
        content=data.get(
            "content",
            "",
        ),
        metadata=metadata,
        created_at=parse_datetime(
            data.get("created_at")
        ),
    )


def work_card_from_dict(
    data: dict[str, Any],
) -> WorkCard:
    metadata = data.get(
        "metadata",
        data.get("payload", {}),
    )

    if not isinstance(metadata, dict):
        metadata = {}

    return WorkCard(
        id=data.get("id"),
        project_id=data.get(
            "project_id"
        ),
        title=data.get(
            "title",
            "",
        ),
        description=data.get(
            "description",
            "",
        ),
        workflow_type=data.get(
            "workflow_type",
            data.get(
                "task_type",
                "assistant",
            ),
        ),
        status=data.get(
            "status",
            "queued",
        ),
        error_message=data.get(
            "error_message",
            "",
        ) or "",
        metadata=metadata,
        created_at=parse_datetime(
            data.get("created_at")
        ),
        updated_at=parse_datetime(
            data.get("updated_at")
        ),
    )


def approval_from_dict(
    data: dict[str, Any],
) -> Approval:
    return Approval(
        id=data.get("id"),
        work_card_id=data.get(
            "work_card_id"
        ),
        action=data.get(
            "action",
            "",
        ),
        note=data.get(
            "note",
            "",
        ),
        created_at=parse_datetime(
            data.get("created_at")
        ),
    )


def browser_session_from_dict(
    data: dict[str, Any],
) -> BrowserSession:
    return BrowserSession(
        id=data.get("id"),
        project_id=data.get(
            "project_id"
        ),
        site=data.get(
            "site",
            "",
        ),
        status=data.get(
            "status",
            "active",
        ),
        storage_path=data.get(
            "storage_path",
            "",
        ),
        last_url=data.get(
            "last_url",
            data.get(
                "current_url",
                "",
            ),
        ) or "",
        session_expired=bool(
            data.get(
                "session_expired",
                False,
            )
        ),
        created_at=parse_datetime(
            data.get("created_at")
        ),
        updated_at=parse_datetime(
            data.get("updated_at")
        ),
    )


def secret_from_dict(
    data: dict[str, Any],
) -> Secret:
    return Secret(
        id=data.get("id"),
        name=data.get(
            "name",
            "",
        ),
        encrypted_value=data.get(
            "encrypted_value",
            "",
        ),
        description=data.get(
            "description",
            "",
        ),
        created_at=parse_datetime(
            data.get("created_at")
        ),
        updated_at=parse_datetime(
            data.get("updated_at")
        ),
    )


def event_from_dict(
    data: dict[str, Any],
) -> Event:
    metadata = data.get(
        "metadata",
        {},
    )

    if not isinstance(metadata, dict):
        metadata = {}

    return Event(
        id=data.get("id"),
        project_id=data.get(
            "project_id"
        ),
        event_type=data.get(
            "event_type",
            "",
        ),
        message=data.get(
            "message",
            "",
        ),
        metadata=metadata,
        created_at=parse_datetime(
            data.get("created_at")
        ),
    )


def uploaded_file_from_dict(
    data: dict[str, Any],
) -> UploadedFile:
    analysis = data.get(
        "analysis",
        {},
    )

    if not isinstance(analysis, dict):
        analysis = {}

    return UploadedFile(
        id=data.get("id"),
        project_id=data.get(
            "project_id"
        ),
        filename=data.get(
            "filename",
            "",
        ),
        path=data.get(
            "path",
            data.get(
                "stored_path",
                "",
            ),
        ) or "",
        content_size=int(
            data.get(
                "content_size",
                data.get(
                    "size",
                    0,
                ),
            )
            or 0
        ),
        analysis=analysis,
        created_at=parse_datetime(
            data.get("created_at")
        ),
        updated_at=parse_datetime(
            data.get("updated_at")
        ),
    )


# =========================================================
# Generic Dataclass → Dictionary
# =========================================================

def model_to_dict(
    model: Any,
) -> dict[str, Any]:
    """
    تحويل أي Dataclass من النماذج أعلاه
    إلى Dictionary مناسب للـ JSON.
    """

    if not hasattr(
        model,
        "__dataclass_fields__",
    ):
        raise TypeError(
            "model_to_dict expects a dataclass instance."
        )

    result: dict[str, Any] = {}

    for field_name in model.__dataclass_fields__:
        value = getattr(
            model,
            field_name,
        )

        if isinstance(
            value,
            datetime,
        ):
            result[field_name] = (
                value.isoformat()
            )
        else:
            result[field_name] = value

    return result
