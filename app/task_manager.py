from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .approval import ApprovalManager


logger = logging.getLogger(__name__)


class TaskManager:
    """
    Central task/work-card manager.

    Responsibilities:
    - Queue approved work.
    - Start and stop work safely.
    - Pause work when connectivity is lost.
    - Resume queued/paused work after connectivity returns.
    - Prevent duplicate execution of the same work card.
    - Persist state in SQLite.
    """

    def __init__(
        self,
        database,
        browser,
        agent,
        notifications,
        settings,
        connectivity=None,
    ) -> None:
        self.db = database
        self.browser = browser
        self.agent = agent
        self.notifications = notifications
        self.settings = settings
        self.connectivity = connectivity

        self.approval = ApprovalManager(database)

        self._running_tasks: dict[int, asyncio.Task] = {}
        self._stop_requested: set[int] = set()
        self._paused_by_connection: set[int] = set()

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _get_id(card: Any) -> int:
        if isinstance(card, dict):
            return int(card["id"])

        return int(card.id)

    @staticmethod
    def _get_value(
        card: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        if isinstance(card, dict):
            return card.get(key, default)

        return getattr(card, key, default)

    def _is_running(self, work_card_id: int) -> bool:
        task = self._running_tasks.get(work_card_id)

        return (
            task is not None
            and not task.done()
        )

    async def _event(
        self,
        event_type: str,
        message: str,
        project_id: Optional[int] = None,
        work_card_id: Optional[int] = None,
    ) -> None:
        try:
            self.db.create_event(
                event_type=event_type,
                message=message,
                project_id=project_id,
                work_card_id=work_card_id,
            )
        except TypeError:
            # Compatibility with database implementations that use
            # a different argument ordering.
            try:
                self.db.create_event(
                    event_type,
                    message,
                    project_id,
                    work_card_id,
                )
            except Exception:
                logger.exception(
                    "Unable to save task event."
                )

        except Exception:
            logger.exception(
                "Unable to save task event."
            )

    # ------------------------------------------------------------------
    # Work-card creation
    # ------------------------------------------------------------------

    async def create_task(
        self,
        project_id: int,
        title: str,
        description: str = "",
        task_type: str = "general",
        payload: Optional[dict] = None,
        requires_approval: bool = True,
    ):
        """
        Create a persistent work card.

        New tasks normally require approval before execution.
        """

        status = (
            "needs_approval"
            if requires_approval
            else "queued"
        )

        try:
            work_card_id = self.db.create_work_card(
                project_id=project_id,
                title=title,
                description=description,
                task_type=task_type,
                status=status,
                payload=payload or {},
            )
        except TypeError:
            # Fallback for simpler database signatures.
            work_card_id = self.db.create_work_card(
                project_id,
                title,
                description,
                task_type,
                status,
                payload or {},
            )

        await self._event(
            "task_created",
            f"تم إنشاء مهمة جديدة: {title}",
            project_id=project_id,
            work_card_id=work_card_id,
        )

        if requires_approval:
            await self._event(
                "approval_required",
                f"المهمة تحتاج موافقة قبل التنفيذ: {title}",
                project_id=project_id,
                work_card_id=work_card_id,
            )

        return self.db.get_work_card(work_card_id)

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    async def approve(
        self,
        work_card_id: int,
    ) -> bool:
        result = self.approval.approve(work_card_id)

        if asyncio.iscoroutine(result):
            result = await result

        if not result:
            return False

        card = self.db.get_work_card(work_card_id)

        if card is not None:
            await self._event(
                "task_approved",
                "تمت الموافقة على المهمة.",
                project_id=self._get_value(
                    card,
                    "project_id",
                ),
                work_card_id=work_card_id,
            )

        return True

    async def reject(
        self,
        work_card_id: int,
        reason: str = "",
    ) -> bool:
        result = self.approval.reject(
            work_card_id,
            reason,
        )

        if asyncio.iscoroutine(result):
            result = await result

        if not result:
            return False

        card = self.db.get_work_card(work_card_id)

        if card is not None:
            await self._event(
                "task_rejected",
                reason or "تم رفض المهمة.",
                project_id=self._get_value(
                    card,
                    "project_id",
                ),
                work_card_id=work_card_id,
            )

        return True

    # ------------------------------------------------------------------
    # Queue / execution
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        work_card_id: int,
    ) -> bool:
        card = self.db.get_work_card(work_card_id)

        if card is None:
            return False

        status = self._get_value(
            card,
            "status",
            "",
        )

        if status == "needs_approval":
            return False

        if status in {
            "completed",
            "stopped",
            "error",
        }:
            return False

        if self._is_running(work_card_id):
            return True

        try:
            self.db.update_work_card(
                work_card_id,
                status="queued",
            )
        except TypeError:
            self.db.update_work_card(
                work_card_id,
                {"status": "queued"},
            )

        await self._event(
            "task_queued",
            "تم وضع المهمة في قائمة الانتظار.",
            project_id=self._get_value(
                card,
                "project_id",
            ),
            work_card_id=work_card_id,
        )

        return True

    async def run(
        self,
        work_card_id: int,
    ) -> bool:
        """
        Start a work card.

        Actual execution is intentionally conservative:
        browser actions must come from the structured task payload.
        Arbitrary code is never executed.
        """

        async with self._lock:
            if self._is_running(work_card_id):
                return True

            card = self.db.get_work_card(work_card_id)

            if card is None:
                return False

            status = self._get_value(
                card,
                "status",
                "",
            )

            if status == "needs_approval":
                return False

            if status in {
                "completed",
                "stopped",
                "error",
            }:
                return False

            if (
                self.connectivity is not None
                and not self.connectivity.is_online
            ):
                self._paused_by_connection.add(
                    work_card_id
                )

                await self._set_status(
                    work_card_id,
                    "paused",
                    error_message="connection_lost",
                )

                return False

            self._stop_requested.discard(
                work_card_id
            )

            task = asyncio.create_task(
                self._execute(
                    work_card_id
                ),
                name=f"work-card-{work_card_id}",
            )

            self._running_tasks[
                work_card_id
            ] = task

        return True

    async def _execute(
        self,
        work_card_id: int,
    ) -> None:
        card = self.db.get_work_card(work_card_id)

        if card is None:
            self._running_tasks.pop(
                work_card_id,
                None,
            )
            return

        project_id = self._get_value(
            card,
            "project_id",
        )

        try:
            await self._set_status(
                work_card_id,
                "running",
            )

            await self._event(
                "task_started",
                "بدأ تنفيذ المهمة.",
                project_id=project_id,
                work_card_id=work_card_id,
            )

            payload = self._get_value(
                card,
                "payload",
                {},
            )

            if not isinstance(payload, dict):
                payload = {}

            result = await self._execute_payload(
                work_card_id,
                project_id,
                payload,
            )

            if work_card_id in self._stop_requested:
                await self._set_status(
                    work_card_id,
                    "stopped",
                )

                return

            if (
                self.connectivity is not None
                and not self.connectivity.is_online
            ):
                self._paused_by_connection.add(
                    work_card_id
                )

                await self._set_status(
                    work_card_id,
                    "paused",
                    error_message="connection_lost",
                )

                return

            await self._set_status(
                work_card_id,
                "completed",
            )

            await self._event(
                "task_completed",
                f"اكتملت المهمة. النتيجة: {result}",
                project_id=project_id,
                work_card_id=work_card_id,
            )

        except asyncio.CancelledError:
            if work_card_id in self._stop_requested:
                await self._set_status(
                    work_card_id,
                    "stopped",
                )
            else:
                await self._set_status(
                    work_card_id,
                    "paused",
                )

            raise

        except Exception as exc:
            logger.exception(
                "Work card %s failed.",
                work_card_id,
            )

            await self._set_status(
                work_card_id,
                "error",
                error_message=str(exc),
            )

            await self._event(
                "task_error",
                f"حدث خطأ أثناء تنفيذ المهمة: {exc}",
                project_id=project_id,
                work_card_id=work_card_id,
            )

        finally:
            self._running_tasks.pop(
                work_card_id,
                None,
            )

    # ------------------------------------------------------------------
    # Structured execution
    # ------------------------------------------------------------------

    async def _execute_payload(
        self,
        work_card_id: int,
        project_id: int,
        payload: dict,
    ) -> str:
        """
        Execute only explicitly supported structured operations.

        Supported:
            browser_open
            browser_navigate
            browser_click
            browser_fill
            browser_text
            wait

        Unknown operations are rejected.
        """

        operations = payload.get("operations")

        if operations is None:
            # No executable operation means the card can be treated as
            # a planning/administrative task.
            return "لا توجد عمليات تنفيذية محددة."

        if not isinstance(operations, list):
            raise ValueError(
                "operations must be a list."
            )

        results: list[str] = []

        for operation in operations:
            if work_card_id in self._stop_requested:
                break

            if (
                self.connectivity is not None
                and not self.connectivity.is_online
            ):
                self._paused_by_connection.add(
                    work_card_id
                )

                await self._set_status(
                    work_card_id,
                    "paused",
                    error_message="
