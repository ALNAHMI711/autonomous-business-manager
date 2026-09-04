from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class WorkStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_APPROVAL = "needs_approval"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ERROR = "error"
    NEEDS_REAUTH = "needs_reauth"


class WorkflowType(str, Enum):
    ASSISTANT = "assistant"
    API_ACCOUNT = "api_account"
    UPLOAD_DESIGN = "upload_design"
    CODE_API = "code_api"
    DUAL = "dual"


class ApprovalAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    PAUSE = "pause"
    STOP = "stop"
    RESUME = "resume"


class EventType(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    APPROVAL_REQUIRED = "approval_required"
    SESSION_EXPIRED = "session_expired"
    CONNECTION_LOST = "connection_lost"
    CONNECTION_RESTORED = "connection_restored"
    SECURITY = "security"


class NotificationCode(str, Enum):
    OFFLINE = "ن؟"
    RESTORED = ">س✓<"
    QUESTION = ">م?"
    REAUTH = "<|>"


@dataclass
class WorkCard:
    id: int
    project_id: int | None
    title: str
    workflow_type: str
    status: WorkStatus
    description: str
    next_step: str | None = None
    error_message: str | None = None
    requires_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "workflow_type": self.workflow_type,
            "status": self.status.value,
            "description": self.description,
            "next_step": self.next_step,
            "error_message": self.error_message,
            "requires_approval": self.requires_approval,
        }
