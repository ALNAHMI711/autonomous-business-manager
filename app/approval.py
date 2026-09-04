from __future__ import annotations

from typing import Any

from .database import Database
from .models import ApprovalAction, WorkStatus


class ApprovalManager:
    def __init__(self, database: Database):
        self.database = database

    def execute_action(
        self,
        card_id: int,
        action: str,
    ) -> dict[str, Any]:

        card = self.database.get_work_card(card_id)

        if not card:
            raise ValueError("Work Card غير موجود.")

        try:
            requested_action = ApprovalAction(action)
        except ValueError as exc:
            raise ValueError(
                "الإجراء غير صالح."
            ) from exc

        current_status = card["status"]

        if requested_action == ApprovalAction.APPROVE:
            if current_status not in {
                WorkStatus.NEEDS_APPROVAL.value,
                WorkStatus.PAUSED.value,
            }:
                raise ValueError(
                    "لا يمكن اعتماد هذه البطاقة في حالتها الحالية."
                )

            new_status = WorkStatus.QUEUED.value
            decision = "approved"

        elif requested_action == ApprovalAction.REJECT:
            if current_status not in {
                WorkStatus.NEEDS_APPROVAL.value,
                WorkStatus.QUEUED.value,
            }:
                raise ValueError(
                    "لا يمكن رفض هذه البطاقة في حالتها الحالية."
                )

            new_status = WorkStatus.STOPPED.value
            decision = "rejected"

        elif requested_action == ApprovalAction.PAUSE:
            if current_status in {
                WorkStatus.STOPPED.value,
                WorkStatus.COMPLETED.value,
            }:
                raise ValueError(
                    "لا يمكن إيقاف بطاقة مكتملة أو متوقفة."
                )

            new_status = WorkStatus.PAUSED.value
            decision = "paused"

        elif requested_action == ApprovalAction.STOP:
            if current_status == WorkStatus.COMPLETED.value:
                raise ValueError(
                    "المهمة مكتملة بالفعل."
                )

            new_status = WorkStatus.STOPPED.value
            decision = "stopped"

        elif requested_action == ApprovalAction.RESUME:
            if current_status != WorkStatus.PAUSED.value:
                raise ValueError(
                    "الاستئناف متاح للمهام المتوقفة مؤقتاً فقط."
                )

            new_status = WorkStatus.QUEUED.value
            decision = "resumed"

        else:
            raise ValueError("إجراء غير مدعوم.")

        self.database.update_work_card(
            card_id=card_id,
            status=new_status,
        )

        self.database.add_approval(
            work_card_id=card_id,
            action=requested_action.value,
            decision=decision,
        )

        return {
            "success": True,
            "card_id": card_id,
            "previous_status": current_status,
            "new_status": new_status,
            "decision": decision,
}
