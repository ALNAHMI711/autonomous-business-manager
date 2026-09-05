from __future__ import annotations

from typing import Any

from app.database import Database


class ApprovalManager:
    """
    Controls human approval for operational work cards.

    State flow:

        needs_approval -> queued
        needs_approval -> stopped

        queued -> paused
        queued -> stopped

        running -> paused
        running -> stopped

        paused -> queued
        paused -> stopped

        completed/error/stopped -> terminal
    """

    ALLOWED_ACTIONS = {
        "approve",
        "reject",
        "pause",
        "stop",
        "resume",
    }

    def __init__(self, database: Database):
        self.database = database

    def _get_card(self, card_id: int) -> dict[str, Any]:
        card = self.database.get_work_card(card_id)

        if not card:
            raise ValueError(
                "بطاقة العمل غير موجودة."
            )

        return card

    def _record(
        self,
        card_id: int,
        action: str,
        note: str = "",
    ) -> None:
        self.database.create_approval(
            work_card_id=card_id,
            action=action,
            note=note,
        )

    def _event(
        self,
        card: dict[str, Any],
        message: str,
        event_type: str = "info",
    ) -> None:
        self.database.create_event(
            event_type=event_type,
            message=message,
            project_id=card.get("project_id"),
            work_card_id=card.get("id"),
        )

    async def handle_action(
        self,
        card_id: int,
        action: str,
        note: str = "",
    ) -> dict[str, Any]:
        action = action.strip().lower()

        if action not in self.ALLOWED_ACTIONS:
            raise ValueError(
                "إجراء غير صالح."
            )

        card = self._get_card(card_id)
        status = card.get("status")

        if action == "approve":
            return self.approve(
                card_id=card_id,
                note=note,
            )

        if action == "reject":
            return self.reject(
                card_id=card_id,
                note=note,
            )

        if action == "pause":
            return self.pause(
                card_id=card_id,
                note=note,
            )

        if action == "stop":
            return self.stop(
                card_id=card_id,
                note=note,
            )

        if action == "resume":
            return self.resume(
                card_id=card_id,
                note=note,
            )

        raise ValueError(
            f"الإجراء غير مدعوم للحالة الحالية: {status}"
        )

    def approve(
        self,
        card_id: int,
        note: str = "",
    ) -> dict[str, Any]:
        card = self._get_card(card_id)
        status = card.get("status")

        if status not in {
            "needs_approval",
            "paused",
        }:
            raise ValueError(
                "لا يمكن اعتماد هذه البطاقة في حالتها الحالية."
            )

        updated = self.database.update_work_card(
            card_id=card_id,
            status="queued",
            error_message=None,
        )

        self._record(
            card_id=card_id,
            action="approve",
            note=note,
        )

        self._event(
            card=card,
            message="تم اعتماد بطاقة العمل وإدراجها في قائمة التنفيذ.",
            event_type="info",
        )

        return updated or {}

    def reject(
        self,
        card_id: int,
        note: str = "",
    ) -> dict[str, Any]:
        card = self._get_card(card_id)
        status = card.get("status")

        if status not in {
            "needs_approval",
            "paused",
            "queued",
        }:
            raise ValueError(
                "لا يمكن رفض هذه البطاقة في حالتها الحالية."
            )

        updated = self.database.update_work_card(
            card_id=card_id,
            status="stopped",
            error_message="rejected_by_user",
        )

        self._record(
            card_id=card_id,
            action="reject",
            note=note,
        )

        self._event(
            card=card,
            message="تم رفض بطاقة العمل من المستخدم.",
            event_type="warning",
        )

        return updated or {}

    def pause(
        self,
        card_id: int,
        note: str = "",
    ) -> dict[str, Any]:
        card = self._get_card(card_id)
        status = card.get("status")

        if status not in {
            "queued",
            "running",
        }:
            raise ValueError(
                "لا يمكن إيقاف هذه البطاقة مؤقتاً في حالتها الحالية."
            )

        updated = self.database.update_work_card(
            card_id=card_id,
            status="paused",
        )

        self._record(
            card_id=card_id,
            action="pause",
            note=note,
        )

        self._event(
            card=card,
            message="تم إيقاف بطاقة العمل مؤقتاً.",
            event_type="warning",
        )

        return updated or {}

    def stop(
        self,
        card_id: int,
        note: str = "",
    ) -> dict[str, Any]:
        card = self._get_card(card_id)
        status = card.get("status")

        if status in {
            "completed",
            "stopped",
        }:
            raise ValueError(
                "بطاقة العمل متوقفة أو مكتملة بالفعل."
            )

        updated = self.database.update_work_card(
            card_id=card_id,
            status="stopped",
            error_message="stopped_by_user",
        )

        self._record(
            card_id=card_id,
            action="stop",
            note=note,
        )

        self._event(
            card=card,
            message="تم إيقاف بطاقة العمل نهائياً من المستخدم.",
            event_type="warning",
        )

        return updated or {}

    def resume(
        self,
        card_id: int,
        note: str = "",
    ) -> dict[str, Any]:
        card = self._get_card(card_id)
        status = card.get("status")

        if status != "paused":
            raise ValueError(
                "يمكن استئناف البطاقة فقط عندما تكون متوقفة مؤقتاً."
            )

        updated = self.database.update_work_card(
            card_id=card_id,
            status="queued",
            error_message=None,
        )

        self._record(
            card_id=card_id,
            action="resume",
            note=note,
        )

        self._event(
            card=card,
            message="تم استئناف بطاقة العمل وإعادتها إلى قائمة التنفيذ.",
            event_type="info",
        )

        return updated or {}

    def requires_approval(
        self,
        card: dict[str, Any],
    ) -> bool:
        return card.get("status") == "needs_approval"

    def can_execute(
        self,
        card: dict[str, Any],
    ) -> bool:
        return card.get("status") == "queued"

    def is_terminal(
        self,
        card: dict[str, Any],
    ) -> bool:
        return card.get("status") in {
            "completed",
            "stopped",
            "error",
        }
