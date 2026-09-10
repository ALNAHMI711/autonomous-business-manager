from pathlib import Path

from app.persistent_queue import PersistentTaskQueue


def test_queue_survives_new_instance(tmp_path: Path):
    db_path = tmp_path / "queue.sqlite3"
    queue = PersistentTaskQueue(db_path)

    created = queue.enqueue(101, {"operation": "browser_open", "project_id": 7})
    assert created["status"] == "queued"
    assert created["payload"]["operation"] == "browser_open"

    claimed = queue.claim_next()
    assert claimed is not None
    assert claimed["task_id"] == 101
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1

    restarted = PersistentTaskQueue(db_path)
    persisted = restarted.get(101)
    assert persisted is not None
    assert persisted["status"] == "running"
    assert persisted["attempts"] == 1


def test_queue_failure_can_be_retried(tmp_path: Path):
    queue = PersistentTaskQueue(tmp_path / "queue.sqlite3")
    queue.enqueue(202, {"kind": "test"})
    assert queue.claim_next() is not None

    retried = queue.fail(
        202,
        "temporary failure",
        retry_at="2999-01-01T00:00:00+00:00",
    )
    assert retried is not None
    assert retried["status"] == "queued"
    assert retried["error_message"] == "temporary failure"


def test_completed_task_is_terminal(tmp_path: Path):
    queue = PersistentTaskQueue(tmp_path / "queue.sqlite3")
    queue.enqueue(303)
    assert queue.claim_next() is not None
    completed = queue.complete(303)
    assert completed is not None
    assert completed["status"] == "completed"

    # Re-enqueue must not silently resurrect a terminal task.
    persisted = queue.enqueue(303, {"new": True})
    assert persisted["status"] == "completed"
