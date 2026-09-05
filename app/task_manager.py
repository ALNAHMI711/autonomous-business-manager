from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .approval import ApprovalManager


logger = logging.getLogger(__name__)


class TaskManager:
    """
    مدير مركزي لمهام النظام.

    الحالات:
        needs_approval
        queued
        running
        paused
        completed
        stopped
        error

    التنفيذ محدود بالعمليات المنظمة فقط.
    لا يتم تنفيذ كود Python أو Shell أو JavaScript
    قادم من المستخدم بشكل مباشر.
    """

    ALLOWED_OPERATIONS = {
        "browser_open",
        "browser_navigate",
        "browser_click",
        "browser_fill",
        "browser_text",
        "wait",
    }

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

    # ================================================================
    # Helpers
    # ================================================================

    @staticmethod
    def _get_value(
        card: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        if isinstance(card, dict):
            return card.get(key, default)

        return getattr(card, key, default)

    def _is_running(
        self,
        work_card_id: int,
    ) -> bool:
        task = self._running_tasks.get(
            work_card_id
        )

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
        metadata: Optional[dict] = None,
    ) -> None:
        try:
            self.db.create_event(
                event_type=event_type,
                message=message,
                project_id=project_id,
                work_card_id=work_card_id,
                metadata=metadata or {},
            )
        except TypeError:
            try:
                self.db.create_event(
                    event_type,
                    message,
                    project_id,
                    work_card_id,
                    metadata or {},
                )
            except Exception:
                logger.exception(
                    "Unable to save task event."
                )
        except Exception:
            logger.exception(
                "Unable to save task event."
            )

    async def _set_status(
        self,
        work_card_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[dict]:
        try:
            return self.db.update_work_card(
                card_id=work_card_id,
                status=status,
                error_message=error_message,
            )
        except TypeError:
            return self.db.update_work_card(
                work_card_id,
                status,
                error_message,
            )

    # ================================================================
    # Create task
    # ================================================================

    async def create_task(
        self,
        project_id: int,
        title: str,
        description: str = "",
        task_type: str = "general",
        payload: Optional[dict] = None,
        requires_approval: bool = True,
    ) -> Optional[dict]:
        """
        إنشاء بطاقة عمل.

        يتم تحويل:
            task_type -> workflow_type
            payload   -> metadata

        حتى تتوافق طبقة التنفيذ مع قاعدة البيانات.
        """

        status = (
            "needs_approval"
            if requires_approval
            else "queued"
        )

        card = self.db.create_work_card(
            project_id=project_id,
            title=title,
            description=description,
            workflow_type=task_type,
            status=status,
            metadata=payload or {},
        )

        card_id = int(card["id"])

        await self._event(
            event_type="task_created",
            message=f"تم إنشاء مهمة جديدة: {title}",
            project_id=project_id,
            work_card_id=card_id,
        )

        if requires_approval:
            await self._event(
                event_type="approval_required",
                message=(
                    f"المهمة تحتاج موافقة قبل التنفيذ: {title}"
                ),
                project_id=project_id,
                work_card_id=card_id,
            )

        return self.db.get_work_card(card_id)

    # ================================================================
    # Approval
    # ================================================================

    async def approve(
        self,
        work_card_id: int,
    ) -> bool:
        try:
            result = self.approval.approve(
                work_card_id
            )

            if asyncio.iscoroutine(result):
                result = await result

            if not result:
                return False

            card = self.db.get_work_card(
                work_card_id
            )

            if card:
                await self._event(
                    event_type="task_approved",
                    message="تمت الموافقة على المهمة.",
                    project_id=card.get(
                        "project_id"
                    ),
                    work_card_id=work_card_id,
                )

            return True

        except Exception:
            logger.exception(
                "Unable to approve work card."
            )
            return False

    async def reject(
        self,
        work_card_id: int,
        reason: str = "",
    ) -> bool:
        try:
            result = self.approval.reject(
                work_card_id,
                reason,
            )

            if asyncio.iscoroutine(result):
                result = await result

            if not result:
                return False

            return True

        except Exception:
            logger.exception(
                "Unable to reject work card."
            )
            return False

    # ================================================================
    # Queue
    # ================================================================

    async def enqueue(
        self,
        work_card_id: int,
    ) -> bool:
        card = self.db.get_work_card(
            work_card_id
        )

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

        if self._is_running(
            work_card_id
        ):
            return True

        await self._set_status(
            work_card_id,
            "queued",
            error_message=None,
        )

        await self._event(
            event_type="task_queued",
            message="تم وضع المهمة في قائمة الانتظار.",
            project_id=card.get(
                "project_id"
            ),
            work_card_id=work_card_id,
        )

        return True

    # ================================================================
    # Run
    # ================================================================

    async def run(
        self,
        work_card_id: int,
    ) -> bool:
        async with self._lock:

            if self._is_running(
                work_card_id
            ):
                return True

            card = self.db.get_work_card(
                work_card_id
            )

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

                await self._event(
                    event_type="task_paused",
                    message=(
                        "تم إيقاف المهمة بسبب انقطاع الإنترنت."
                    ),
                    project_id=card.get(
                        "project_id"
                    ),
                    work_card_id=work_card_id,
                )

                return False

            self._stop_requested.discard(
                work_card_id
            )

            task = asyncio.create_task(
                self._execute(
                    work_card_id
                ),
                name=(
                    f"work-card-{work_card_id}"
                ),
            )

            self._running_tasks[
                work_card_id
            ] = task

            return True

    # ================================================================
    # Execute
    # ================================================================

    async def _execute(
        self,
        work_card_id: int,
    ) -> None:

        card = self.db.get_work_card(
            work_card_id
        )

        if card is None:
            self._running_tasks.pop(
                work_card_id,
                None,
            )
            return

        project_id = card.get(
            "project_id"
        )

        try:
            await self._set_status(
                work_card_id,
                "running",
                error_message=None,
            )

            await self._event(
                event_type="task_started",
                message="بدأ تنفيذ المهمة.",
                project_id=project_id,
                work_card_id=work_card_id,
            )

            payload = card.get(
                "metadata",
                {},
            )

            if isinstance(payload, str):
                try:
                    import json

                    payload = json.loads(
                        payload
                    )
                except Exception:
                    payload = {}

            if not isinstance(
                payload,
                dict,
            ):
                payload = {}

            result = await self._execute_payload(
                work_card_id=work_card_id,
                project_id=project_id,
                payload=payload,
            )

            if work_card_id in self._stop_requested:
                await self._set_status(
                    work_card_id,
                    "stopped",
                    error_message=(
                        "stopped_by_user"
                    ),
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
                    error_message=(
                        "connection_lost"
                    ),
                )

                return

            await self._set_status(
                work_card_id,
                "completed",
                error_message=None,
            )

            await self._event(
                event_type="task_completed",
                message=(
                    f"اكتملت المهمة. النتيجة: {result}"
                ),
                project_id=project_id,
                work_card_id=work_card_id,
                metadata={
                    "result": result
                },
            )

        except asyncio.CancelledError:

            if work_card_id in self._stop_requested:
                await self._set_status(
                    work_card_id,
                    "stopped",
                    error_message=(
                        "stopped_by_user"
                    ),
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
                event_type="task_error",
                message=(
                    f"حدث خطأ أثناء تنفيذ المهمة: {exc}"
                ),
                project_id=project_id,
                work_card_id=work_card_id,
            )

        finally:
            self._running_tasks.pop(
                work_card_id,
                None,
            )

    # ================================================================
    # Structured operations
    # ================================================================

    async def _execute_payload(
        self,
        work_card_id: int,
        project_id: int,
        payload: dict,
    ) -> str:

        operations = payload.get(
            "operations"
        )

        if operations is None:
            return "لا توجد عمليات تنفيذية محددة."

        if not isinstance(
            operations,
            list,
        ):
            raise ValueError(
                "operations يجب أن تكون قائمة."
            )

        results: list[str] = []

        for operation in operations:

            if not isinstance(
                operation,
                dict,
            ):
                raise ValueError(
                    "كل عملية يجب أن تكون كائناً."
                )

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
                    error_message=(
                        "connection_lost"
                    ),
                )

                return "تم إيقاف المهمة مؤقتاً بسبب انقطاع الإنترنت."

            operation_type = str(
                operation.get(
                    "type",
                    ""
                )
            ).strip().lower()

            if operation_type not in self.ALLOWED_OPERATIONS:
                raise ValueError(
                    "العملية غير مسموحة: "
                    f"{operation_type}"
                )

            result = await self._execute_operation(
                operation_type,
                project_id,
                operation,
            )

            results.append(
                str(result)
            )

        return "\n".join(
            results
        ) if results else "تم التنفيذ."

    async def _execute_operation(
        self,
        operation_type: str,
        project_id: int,
        operation: dict,
    ) -> Any:

        if operation_type == "browser_open":

            url = operation.get(
                "url"
            )

            if not url:
                raise ValueError(
                    "browser_open يحتاج إلى url."
                )

            return await self.browser.open_project(
                project_id=project_id,
                site=url,
            )

        if operation_type == "browser_navigate":

            url = operation.get(
                "url"
            )

            if not url:
                raise ValueError(
                    "browser_navigate يحتاج إلى url."
                )

            return await self.browser.navigate(
                project_id=project_id,
                url=url,
            )

        if operation_type == "browser_click":

            selector = operation.get(
                "selector"
            )

            if not selector:
                raise ValueError(
                    "browser_click يحتاج إلى selector."
                )

            return await self.browser.click(
                project_id=project_id,
                selector=selector,
            )

        if operation_type == "browser_fill":

            selector = operation.get(
                "selector"
            )

            value = operation.get(
                "value",
                "",
            )

            if not selector:
                raise ValueError(
                    "browser_fill يحتاج إلى selector."
                )

            return await self.browser.fill(
                project_id=project_id,
                selector=selector,
                value=str(value),
            )

        if operation_type == "browser_text":

            selector = operation.get(
                "selector"
            )

            if not selector:
                raise ValueError(
                    "browser_text يحتاج إلى selector."
                )

            return await self.browser.get_text(
                project_id=project_id,
                selector=selector,
            )

        if operation_type == "wait":

            seconds = operation.get(
                "seconds",
                1,
            )

            try:
                seconds = float(
                    seconds
                )
            except (
                TypeError,
                ValueError,
            ):
                raise ValueError(
                    "قيمة الانتظار غير صحيحة."
                )

            seconds = max(
                0.1,
                min(seconds, 300),
            )

            await asyncio.sleep(
                seconds
            )

            return (
                f"تم الانتظار {seconds:g} ثانية."
            )

        raise ValueError(
            f"عملية غير مدعومة: {operation_type}"
        )

    # ================================================================
    # Pause / Stop / Resume
    # ================================================================

    async def pause(
        self,
        work_card_id: int,
        reason: str = "",
    ) -> bool:

        card = self.db.get_work_card(
            work_card_id
        )

        if not card:
            return False

        self._paused_by_connection.discard(
            work_card_id
        )

        if self._is_running(
            work_card_id
        ):
            task = self._running_tasks.get(
                work_card_id
            )

            if task:
                task.cancel()

        await self._set_status(
            work_card_id,
            "paused",
            error_message=(
                reason or "paused_by_user"
            ),
        )

        await self._event(
            event_type="task_paused",
            message=(
                reason
                or "تم إيقاف المهمة مؤقتاً."
            ),
            project_id=card.get(
                "project_id"
            ),
            work_card_id=work_card_id,
        )

        return True

    async def stop(
        self,
        work_card_id: int,
    ) -> bool:

        card = self.db.get_work_card(
            work_card_id
        )

        if not card:
            return False

        self._stop_requested.add(
            work_card_id
        )

        task = self._running_tasks.get(
            work_card_id
        )

        if task and not task.done():
            task.cancel()

        await self._set_status(
            work_card_id,
            "stopped",
            error_message="stopped_by_user",
        )

        await self._event(
            event_type="task_stopped",
            message="تم إيقاف المهمة نهائياً.",
            project_id=card.get(
                "project_id"
            ),
            work_card_id=work_card_id,
        )

        return True

    async def resume(
        self,
        work_card_id: int,
    ) -> bool:

        card = self.db.get_work_card(
            work_card_id
        )

        if not card:
            return False

        if card.get(
            "status"
        ) != "paused":
            return False

        if (
            self.connectivity is not None
            and not self.connectivity.is_online
        ):
            return False

        self._paused_by_connection.discard(
            work_card_id
        )

        self._stop_requested.discard(
            work_card_id
        )

        await self._set_status(
            work_card_id,
            "queued",
            error_message=None,
        )

        await self._event(
            event_type="task_resumed",
            message="تم استئناف المهمة.",
            project_id=card.get(
                "project_id"
            ),
            work_card_id=work_card_id,
        )

        return await self.run(
            work_card_id
        )

    # ================================================================
    # Connectivity
    # ================================================================

    async def handle_offline(self) -> None:

        cards = self.db.list_all_work_cards()

        for card in cards:

            card_id = int(
                card["id"]
            )

            if card.get(
                "status"
            ) != "running":
                continue

            self._paused_by_connection.add(
                card_id
            )

            task = self._running_tasks.get(
                card_id
            )

            if task and not task.done():
                task.cancel()

            await self._set_status(
                card_id,
                "paused",
                error_message=(
                    "connection_lost"
                ),
            )

            await self._event(
                event_type="connection_lost",
                message=(
                    "تم إيقاف المهمة مؤقتاً بسبب انقطاع الإنترنت."
                ),
                project_id=card.get(
                    "project_id"
                ),
                work_card_id=card_id,
            )

    async def handle_online(self) -> None:

        cards = self.db.list_all_work_cards()

        for card in cards:

            card_id = int(
                card["id"]
            )

            if card_id not in self._paused_by_connection:
                continue

            if card.get(
                "status"
            ) != "paused":
                self._paused_by_connection.discard(
                    card_id
                )
                continue

            await self._set_status(
                card_id,
                "queued",
                error_message=None,
            )

            self._paused_by_connection.discard(
                card_id
            )

            await self._event(
                event_type="connection_restored",
                message=(
                    "عاد الاتصال وتمت إعادة المهمة إلى قائمة التنفيذ."
                ),
                project_id=card.get(
                    "project_id"
                ),
                work_card_id=card_id,
            )

            await self.run(
                card_id
            )

    # ================================================================
    # Shutdown / status
    # ================================================================

    async def shutdown(self) -> None:

        tasks = list(
            self._running_tasks.values()
        )

        for task in tasks:
            if not task.done():
                task.cancel()

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        self._running_tasks.clear()

    def get_running_ids(
        self,
    ) -> list[int]:
        return [
            work_card_id
            for work_card_id, task
            in self._running_tasks.items()
            if not task.done()
        ]

    def is_running(
        self,
        work_card_id: int,
    ) -> bool:
        return self._is_running(
            work_card_id
        )
