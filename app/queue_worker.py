from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .persistent_queue import PersistentTaskQueue

logger = logging.getLogger(__name__)


class PersistentQueueWorker:
    """Durable dispatcher; TaskManager remains the execution boundary."""

    def __init__(
        self,
        queue: PersistentTaskQueue,
        task_manager: Any,
        poll_interval: float = 1.0,
        execution_timeout: float = 3600.0,
    ) -> None:
        self.queue = queue
        self.task_manager = task_manager
        self.poll_interval = max(0.1, poll_interval)
        self.execution_timeout = max(1.0, execution_timeout)
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self.queue.recover_stale()
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="persistent-queue-worker")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def dispatch_once(self) -> Optional[dict[str, Any]]:
        claimed = self.queue.claim_next()
        if claimed is None:
            return None
        task_id = int(claimed["task_id"])
        try:
            accepted = await self.task_manager.run(task_id)
            if not accepted:
                self.queue.fail(task_id, "TaskManager rejected execution")
                return claimed

            database = getattr(self.task_manager, "db", None)
            if database is None:
                self.queue.complete(task_id)
                return claimed

            await asyncio.wait_for(
                self._wait_for_terminal(database, task_id),
                timeout=self.execution_timeout,
            )
        except asyncio.TimeoutError:
            logger.error("Persistent task %s exceeded execution timeout", task_id)
            self.queue.fail(task_id, "execution_timeout")
        except asyncio.CancelledError:
            # Worker shutdown must not lose an in-flight claim. The queue
            # remains durable and will be picked up again after restart.
            self.queue.requeue(task_id, "worker_cancelled", delay_seconds=1)
            raise
        except Exception as exc:
            logger.exception("Persistent task %s failed", task_id)
            self.queue.fail(task_id, str(exc))
        return claimed

    async def _wait_for_terminal(self, database: Any, task_id: int) -> None:
        while not self._stop.is_set():
            card = database.get_work_card(task_id)
            status = str(card.get("status", "")) if card else "error"
            if status == "completed":
                self.queue.complete(task_id)
                return
            if status in {"error", "stopped"}:
                message = str(card.get("error_message", "execution_failed")) if card else "task_missing"
                self.queue.fail(task_id, message)
                return
            if status == "paused":
                self.queue.requeue(task_id, "task_paused", delay_seconds=5)
                return
            await asyncio.sleep(0.1)

        if not self._stop.is_set():
            self.queue.fail(task_id, "worker_stopped")
        else:
            self.queue.requeue(task_id, "worker_stopped", delay_seconds=1)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                claimed = await self.dispatch_once()
                if claimed is None:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Persistent queue worker iteration failed")
                await asyncio.sleep(self.poll_interval)
