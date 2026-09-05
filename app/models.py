from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Project:
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    status: str = "active"
    workflow_type: str = "general"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class ChatMessage:
    id: Optional[int] = None
    project_id: Optional[int] = None
    role: str = "user"
    content: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class WorkCard:
    id: Optional[int] = None
    project_id: Optional[int] = None
    title: str = ""
    description: str = ""
    task_type: str = "general"
    status: str = "needs_approval"
    payload: dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class Approval:
    id: Optional[int] = None
    work_card_id: Optional[int] = None
    status: str = "pending"
    reason: str = ""
    created_at: datetime = field(default_factory=utc_now)
    resolved_at: Optional[datetime] = None


@dataclass
class BrowserSession:
    id: Optional[int] = None
    project_id: Optional[int] = None
    site: str = ""
    status: str = "closed"
    current_url: Optional[str] = None
    session_expired: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class Secret:
    id: Optional[int] = None
    name: str = ""
    encrypted_value: str = ""
    secret_type: str = "generic"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class Event:
    id: Optional[int] = None
    event_type: str = ""
    message: str = ""
    project_id: Optional[int] = None
    work_card_id: Optional[int] = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class UploadedFile:
    id: Optional[int] = None
    project_id: Optional[int] = None
    filename: str = ""
    stored_path: str = ""
    mime_type: Optional[str] = None
    size: int = 0
    analysis_status: str = "pending"
    created_at: datetime = field(default_factory=utc_now)


# ----------------------------------------------------------------------
# Conversion helpers
# ----------------------------------------------------------------------

def _parse_datetime(value: Any) -> datetime:
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


def project_from_dict(data: dict[str, Any]) -> Project:
    return Project(
        id=data.get("id"),
        name=data.get("name", ""),
        description=data.get("description", ""),
        status=data.get("status", "active"),
        workflow_type=data.get(
            "workflow_type",
            "general",
        ),
        created_at=_parse_datetime(
            data.get("created_at")
        ),
        updated_at=_parse_datetime(
            data.get("updated_at")
        ),
    )


def chat_message_from_dict(
    data: dict[str, Any],
) -> ChatMessage:
    return ChatMessage(
        id=data.get("id"),
        project_id=data.get("project_id"),
        role=data.get("role", "user"),
        content=data.get("content", ""),
        created_at=_parse_datetime(
            data.get("created_at")
        ),
    )


def work_card_from_dict(
    data: dict[str, Any],
) -> WorkCard:
    return WorkCard(
        id=data.get("id"),
        project_id=data.get("project_id"),
        title=data.get("title", ""),
        description=data.get("description", ""),
        task_type=data.get(
            "task_type",
            "general",
        ),
        status=data.get(
            "status",
            "needs_approval",
        ),
        payload=data.get(
            "payload",
            {},
        ) or {},
        error_message=data.get(
            "error_message"
        ),
        created_at=_parse_datetime(
            data.get("created_at")
        ),
        updated_at=_parse_datetime(
            data.get("updated_at")
        ),
    )


def approval_from_dict(
    data: dict[str, Any],
) -> Approval:
    resolved = data.get("resolved_at")

    return Approval(
        id=data.get("id"),
        work_card_id=data.get(
            "work_card_id"
        ),
        status=data.get(
            "status",
            "pending",
        ),
        reason=data.get(
            "reason",
            "",
        ),
        created_at=_parse_datetime(
            data.get("created_at")
        ),
        resolved_at=(
            _parse_datetime(resolved)
            if resolved
            else None
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
        site=data.get("site", ""),
        status=data.get(
            "status",
            "closed",
        ),
        current_url=data.get(
            "current_url"
        ),
        session_expired=bool(
            data.get(
                "session_expired",
                False,
            )
        ),
        created_at=_parse_datetime(
            data.get("created_at")
        ),
        updated_at=_parse_datetime(
            data.get("updated_at")
        ),
    )


def secret_from_dict(
    data: dict[str, Any],
) -> Secret:
    return Secret(
        id=data.get("id"),
        name=data.get("name", ""),
        encrypted_value=data.get(
            "encrypted_value",
            "",
        ),
        secret_type=data.get(
            "secret_type",
            "generic",
        ),
        created_at=_parse_datetime(
            data.get("created_at")
        ),
        updated_at=_parse_datetime(
            data.get("updated_at")
        ),
    )


def event_from_dict(
    data: dict[str, Any],
) -> Event:
    return Event(
        id=data.get("id"),
        event_type=data.get(
            "event_type",
            "",
        ),
        message=data.get(
            "message",
            "",
        ),
        project_id=data.get(
            "project_id"
        ),
        work_card_id=data.get(
            "work_card_id"
        ),
        created_at=_parse_datetime(
            data.get("created_at")
        ),
    )


def uploaded_file_from_dict(
    data: dict[str, Any],
) -> UploadedFile:
    return UploadedFile(
        id=data.get("id"),
        project_id=data.get(
            "project_id"
        ),
        filename=data.get(
            "filename",
            "",
        ),
        stored_path=data.get(
            "stored_path",
            "",
        ),
        mime_type=data.get(
            "mime_type"
        ),
        size=int(
            data.get(
                "size",
                0,
            )
            or 0
        ),
        analysis_status=data.get(
            "analysis_status",
            "pending",
        ),
        created_at=_parse_datetime(
            data.get("created_at")
        ),
    )


def model_to_dict(model: Any) -> dict[str, Any]:
    """
    Convert one of the dataclasses above to a JSON-friendly dictionary.

    Sensitive fields are intentionally not removed here because this helper
    is not used for exposing secret values. Secret values should always be
    handled through SecurityManager and explicit metadata endpoints.
    """

    if not hasattr(model, "__dataclass_fields__"):
        raise TypeError(
            "model_to_dict expects a dataclass instance."
        )

    result: dict[str, Any] = {}

    for name in model.__dataclass_fields__:
        value = getattr(model, name)

        if isinstance(value, datetime):
            result[name] = value.isoformat()
        else:
            result[name] = value

    return result
