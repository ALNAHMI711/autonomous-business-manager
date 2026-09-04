from __future__ import annotations

from typing import Any

from .agent import Agent
from .approval import ApprovalManager
from .browser import BrowserManager
from .database import Database
from .models import EventType, WorkStatus
from .notifications import NotificationManager


class TaskManager:
    def __init__(
        self,
        database: Database,
        agent: Agent,
        browser: BrowserManager,
        notifications: NotificationManager,
    ):
        self.database = database
        self.agent = agent
        self.browser = browser
        self.notifications = notifications
        self.approvals = ApprovalManager(database)

    async def create_task_from_chat(
        self,
        message: str,
        workflow_type: str,
        project_id: int | None = None,
    ) -> dict[str, Any]:

        result = await self.agent.chat(
            message=message,
            project_id=project_id,
            workflow_type=workflow_type,
        )

        return result

    def create_approval_task(
        self,
        title: str,
        workflow_type: str,
        description: str,
        project_id: int | None = None,
        next_step: str | None = None,
    ) -> int:

        card_id = self.agent.create_work_card(
            title=title,
            workflow_type=workflow_type,
            description=description,
            project_id=project_id,
            next_step=next_step,
            requires_approval=True,
        )

        return card_id

    async def approve(
        self,
        card_id: int,
    ) -> dict[str, Any]:

        result = self.approvals.execute_action(
            card_id=card_id,
            action="approve",
        )

        card = self.database.get_work_card(
            card_id
        )

        if card:
            self.database.add_event(
                event_type=EventType.INFO.value,
                message=(
                    f"Work Card #{card_id} approved."
                ),
                project_id=card.get(
                    "project_id"
                ),
            )

        return result

    async def reject(
        self,
        card_id: int,
    ) -> dict[str, Any]:

        result = self.approvals.execute_action(
            card_id=card_id,
            action="reject",
        )

        return result

    async def pause(
        self,
        card_id: int,
    ) -> dict[str, Any]:

        return self.approvals.execute_action(
            card_id=card_id,
            action="pause",
        )

    async def stop(
        self,
        card_id: int,
    ) -> dict[str, Any]:

        return self.approvals.execute_action(
            card_id=card_id,
            action="stop",
        )

    async def resume(
        self,
        card_id: int,
    ) -> dict[str, Any]:

        return self.approvals.execute_action(
            card_id=card_id,
            action="resume",
        )

    async def mark_running(
        self,
        card_id: int,
    ) -> None:

        card = self.database.get_work_card(
            card_id
        )

        if not card:
            raise ValueError(
                "Work Card غير موجود."
            )

        if card["requires_approval"]:
            if card["status"] != WorkStatus.QUEUED.value:
                raise ValueError(
                    "المهمة ليست في حالة انتظار التنفيذ."
                )

        self.database.update_work_card(
            card_id=card_id,
            status=WorkStatus.RUNNING.value,
        )

    async def mark_completed(
        self,
        card_id: int,
    ) -> None:

        self.database.update_work_card(
            card_id=card_id,
            status=WorkStatus.COMPLETED.value,
        )

    async def mark_error(
        self,
        card_id: int,
        error: str,
    ) -> None:

        self.database.update_work_card(
            card_id=card_id,
            status=WorkStatus.ERROR.value,
            error_message=error,
        )

    async def mark_reauth(
        self,
        project_id: int,
    ) -> None:

        self.database.update_project_status(
            project_id,
            WorkStatus.NEEDS_REAUTH.value,
        )

        self.database.execute_script(
            f"""
            UPDATE work_cards
            SET status = 'needs_reauth',
                updated_at = CURRENT_TIMESTAMP
            WHERE project_id = {int(project_id)}
              AND status IN ('running', 'queued')
            """
        )

        await self.notifications.reauth_required(
            project_id
      )
