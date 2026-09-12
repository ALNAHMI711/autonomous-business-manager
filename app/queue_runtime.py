from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

from app.main import app, db, task_manager, settings
from app.csrf_middleware import CSRFSecurityMiddleware
from app.project_access import ProjectAccessMiddleware
from app.persistent_queue import PersistentTaskQueue
from app.queue_worker import PersistentQueueWorker
from app.kill_switch import KillSwitch


queue = PersistentTaskQueue(settings.database_path)
kill_switch = KillSwitch(settings.database_path)
_original_run = task_manager.run
_original_enqueue = task_manager.enqueue


async def _queue_run(work_card_id: int) -> bool:
    """Public execution entrypoint: persist first, execute via the worker."""
    if kill_switch.is_active():
        return False
    card = db.get_work_card(work_card_id)
    if not card:
        return False
    status = str(card.get("status", "")).lower()
    if status in {"needs_approval", "completed", "stopped", "error"}:
        return False
    return bool(queue.enqueue(work_card_id, {"work_card_id": work_card_id}))


async def _queue_enqueue(work_card_id: int) -> bool:
    if kill_switch.is_active():
        return False
    accepted = await _original_enqueue(work_card_id)
    if not accepted:
        return False
    return bool(queue.enqueue(work_card_id, {"work_card_id": work_card_id}))


class _ExecutionGate:
    """Keep the durable worker behind the same fail-safe gate."""

    def __init__(self, manager, gate: KillSwitch) -> None:
        self._manager = manager
        self._gate = gate
        self.db = manager.db

    async def run(self, work_card_id: int) -> bool:
        if self._gate.is_active():
            return False
        return bool(await self._manager.run(work_card_id))


task_manager.run = _queue_run  # type: ignore[method-assign]
task_manager.enqueue = _queue_enqueue  # type: ignore[method-assign]
execution_manager = _ExecutionGate(SimpleNamespace(run=_original_run, db=db), kill_switch)
worker = PersistentQueueWorker(queue, execution_manager)


async def _sync_queued_cards() -> None:
    for card in db.list_all_work_cards():
        if str(card.get("status", "")).lower() != "queued":
            continue
        card_id = int(card["id"])
        item = queue.get(card_id)
        if item is None or item.get("status") in {"failed", "cancelled"}:
            queue.enqueue(card_id, {"work_card_id": card_id})


_original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan(application):
    async with _original_lifespan(application):
        await _sync_queued_cards()
        await worker.start()
        try:
            yield
        finally:
            await worker.stop()


app.add_middleware(ProjectAccessMiddleware, database=db)

if settings.app_env.lower() == "production" and not settings.csrf_secret:
    raise RuntimeError("CSRF_SECRET must be configured in production")
if settings.csrf_secret:
    app.add_middleware(CSRFSecurityMiddleware, secret=settings.csrf_secret)
