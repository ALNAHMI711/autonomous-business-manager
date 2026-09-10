from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .persistent_queue import PersistentTaskQueue


logger = logging.getLogger(__name__)


class PersistentQueueWorker:
    """Bridge durable queue records to the existing TaskManager.

    The worker deliberately keeps TaskManager as the execution authority.
    SQLite is used only for durable scheduling/claiming, so a process restart
    does not lose queued work.
    """

    def __init__(
        self,
        database,
        task_manager,
        database_path: str,
        poll_interval: float = 1.0,
        stale_after_seconds: int = 300,
    ) -> None:
        self.db = database
        self.task_manager = task_manager
        self.queue = PersistentTaskQueue(database_path)
        self.poll_interval = max(0.2, poll_interval)
        self.stale_after_seconds = max(30, stale_after_seconds)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(
                self.run(),
                name="persistent-queue-worker",
            )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def run(self) -> None:
        self._recover_stale_claims()
        while not self._stop.is_set():
            try:
                self._sync_database_queue()
                await self._process_one()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Persistent queue worker iteration failed.")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.poll_interval,
                )
            except asyncio.TimeoutError:
                pass

    def _sync_database_queue(self) -> None:
        """Materialize queued work cards into the durable queue."""
        connection = self.db._connect()
        try:
            rows = connection.execute(
                """
                SELECT id, project_id, workflow_type, metadata
                FROM work_cards
                WHERE status = 'queued'
                ORDER BY id ASC
                LIMIT 100
                """
            ).fetchall()
        finally:
            connection.close()

        for row in rows:
            payload = self._decode_metadata(row["metadata"])
            self.queue.enqueue(
                task_id=int(row["id"]),
                payload={
                    "project_id": row["project_id"],
                    "workflow_type": row["workflow_type"],
                    "metadata": payload,
                },
            )

    async def _process_one(self) -> None:
        item = self.queue.claim_next()
        if item is None:
            return

        task_id = int(item["task_id"])
        try:
            started = await self.task_manager.run(task_id)
            if not started:
                card = self.db.get_work_card(task_id)
                status = self._status(card)
                if status == "paused":
                    self.queue.fail(
                        task_id,
                        "task_paused",
                        retry_at=self._retry_time(5),
                    )
                elif status in {"completed", "stopped", "error"}:
                    self.queue.complete(task_id)
                else:
                    self.queue.fail(
                        task_id,
                        "task_manager_refused_to_start",
                        retry_at=self._retry_time(5),
                    )
                return

            await self._wait_for_execution(task_id)
        except asyncio.CancelledError:
            self.queue.fail(
                task_id,
                "worker_cancelled",
                retry_at=self._retry_time(5),
            )
            raise
        except Exception as exc:
            logger.exception("Durable task %s failed.", task_id)
            self.queue.fail(
                task_id,
                str(exc),
                retry_at=self._retry_time(5),
            )

    async def _wait_for_execution(self, task_id: int) -> None:
        while not self._stop.is_set():
            card = self.db.get_work_card(task_id)
            status = self._status(card)
            if status == "completed":
                self.queue.complete(task_id)
                return
            if status == "error":
                self.queue.fail(task_id, self._error(card))
                return
            if status == "stopped":
                self.queue.cancel(task_id)
                return
            if status == "paused":
                self.queue.fail(
                    task_id,
                    self._error(card) or "task_paused",
                    retry_at=self._retry_time(5),
                )
                return
            await asyncio.sleep(self.poll_interval)

    def _recover_stale_claims(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self.stale_after_seconds
        )
        cutoff_iso = cutoff.isoformat()
        connection = self.queue._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                UPDATE task_queue
                SET status='queued', available_at=?,
                    error_message='recovered_after_restart', updated_at=?
                WHERE status='running'
                  AND claimed_at IS NOT NULL
                  AND claimed_at < ?
                """,
                (now, now, cutoff_iso),
            )
        finally:
            connection.close()

    @staticmethod
    def _decode_metadata(value: Any) -> dict:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            import json
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _status(card: Any) -> str:
        if isinstance(card, dict):
            return str(card.get("status", ""))
        return str(getattr(card, "status", ""))

    @staticmethod
    def _error(card: Any) -> str:
        if isinstance(card, dict):
            return str(card.get("error_message", ""))
        return str(getattr(card, "error_message", ""))

    @staticmethod
    def _retry_time(seconds: int) -> str:
        return (
            datetime.now(timezone.utc) + timedelta(seconds=seconds)
        ).isoformat()
