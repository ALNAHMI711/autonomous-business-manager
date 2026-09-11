from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

from app.main import app, db, task_manager, settings
from app.csrf_middleware import CSRFSecurityMiddleware
from app.persistent_queue import PersistentTaskQueue
from app.queue_worker import PersistentQueueWorker


queue = PersistentTaskQueue(settings.database_path)
_original_run = task_manager.run
_original_enqueue = task_manager.enqueue


async def _queue_run(work_card_id: int) -> bool:
    """Public execution entrypoint: persist first, execute via the worker."""
    card = db.get_work_card(work_card_id)
    if not card:
        return False
    status = str(card.get("status", "")).lower()
    if status in {"needs_approval", "completed", "stopped", "error"}:
        return False
    return bool(queue.enqueue(work_card_id, {"work_card_id": work_card_id}))


async def _queue_enqueue(work_card_id: int) -> bool:
    accepted = await _original_enqueue(work_card_id)
    if not accepted:
        return False
    return bool(queue.enqueue(work_card_id, {"work_card_id": work_card_id}))


# Main application routes and TaskManager resume/online paths call run().
# Redirect that boundary to the durable queue. The worker uses a separate
# execution proxy so it still calls the original in-process executor.
task_manager.run = _queue_run  # type: ignore[method-assign]
task_manager.enqueue = _queue_enqueue  # type: ignore[method-assign]
execution_manager = SimpleNamespace(
    run=_original_run,
    db=db,
)
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


# Production runs through this module, so install CSRF protection here
# without rewriting the large route module in app.main.
if settings.csrf_secret:
    app.add_middleware(CSRFSecurityMiddleware, secret=settings.csrf_secret)

app.router.lifespan_context = _lifespan
