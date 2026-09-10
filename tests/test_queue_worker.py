import asyncio

import pytest

from app.persistent_queue import PersistentTaskQueue
from app.queue_worker import PersistentQueueWorker


class FakeTaskManager:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.calls = []

    async def run(self, task_id):
        self.calls.append(task_id)
        return self.accepted


@pytest.mark.asyncio
async def test_dispatch_once_completes_task(tmp_path):
    queue = PersistentTaskQueue(tmp_path / "queue.db")
    manager = FakeTaskManager()
    queue.enqueue(42, {"hello": "world"})

    worker = PersistentQueueWorker(queue, manager)
    claimed = await worker.dispatch_once()

    assert claimed["task_id"] == 42
    assert manager.calls == [42]
    assert queue.get(42)["status"] == "completed"


@pytest.mark.asyncio
async def test_dispatch_once_records_rejection(tmp_path):
    queue = PersistentTaskQueue(tmp_path / "queue.db")
    manager = FakeTaskManager(accepted=False)
    queue.enqueue(7)

    worker = PersistentQueueWorker(queue, manager)
    await worker.dispatch_once()

    item = queue.get(7)
    assert item["status"] == "failed"
    assert "rejected" in item["error_message"]


@pytest.mark.asyncio
async def test_worker_start_stop_is_idempotent(tmp_path):
    queue = PersistentTaskQueue(tmp_path / "queue.db")
    worker = PersistentQueueWorker(queue, FakeTaskManager())

    await worker.start()
    first = worker._task
    await worker.start()
    assert worker._task is first

    await worker.stop()
    assert worker._task is None

    # No leaked asyncio task should remain after shutdown.
    await asyncio.sleep(0)
