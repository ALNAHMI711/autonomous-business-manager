import asyncio

import pytest

from app.persistent_queue import PersistentTaskQueue
from app.queue_worker import PersistentQueueWorker


class FakeTaskManager:
    def __init__(self, accepted=True, db=None):
        self.accepted = accepted
        self.calls = []
        self.db = db

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
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_shutdown_requeues_inflight_task(tmp_path):
    queue = PersistentTaskQueue(tmp_path / "queue.db")
    queue.enqueue(123)

    class SlowManager:
        async def run(self, task_id):
            await asyncio.sleep(60)
            return True

    worker = PersistentQueueWorker(queue, SlowManager())
    task = asyncio.create_task(worker.dispatch_once())
    await asyncio.sleep(0.01)
    assert queue.get(123)["status"] == "running"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    item = queue.get(123)
    assert item["status"] == "queued"
    assert item["error_message"] == "worker_cancelled"


def test_recover_stale_requeues_abandoned_claim(tmp_path):
    queue = PersistentTaskQueue(tmp_path / "queue.db")
    queue.enqueue(99)
    claimed = queue.claim_next()
    assert claimed["status"] == "running"

    with queue._connect() as connection:
        connection.execute(
            "UPDATE task_queue SET claimed_at=?, updated_at=? WHERE task_id=?",
            ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", 99),
        )

    assert queue.recover_stale(max_age_seconds=60) == 1
    assert queue.get(99)["status"] == "queued"
    assert queue.get(99)["error_message"] == "recovered_after_restart"


def test_requeue_preserves_attempt_count(tmp_path):
    queue = PersistentTaskQueue(tmp_path / "queue.db")
    queue.enqueue(55)
    queue.claim_next()
    before = queue.get(55)["attempts"]

    item = queue.requeue(55, "manual_shutdown", delay_seconds=0)

    assert item["status"] == "queued"
    assert item["attempts"] == before
    assert item["claimed_at"] is None
