from types import SimpleNamespace

import pytest

from app.task_manager import TaskManager


class FakeDatabase:
    def __init__(self):
        self.card = {
            "id": 7,
            "project_id": 3,
            "status": "queued",
            "metadata": {
                "operations": [{"type": "not_allowed", "secret": "TOP-SECRET"}],
            },
        }
        self.updates = []
        self.events = []

    def get_work_card(self, card_id):
        return self.card if card_id == 7 else None

    def update_work_card(self, card_id, status, error_message=None):
        self.card["status"] = status
        self.card["error_message"] = error_message
        self.updates.append((card_id, status, error_message))
        return dict(self.card)

    def create_event(self, **kwargs):
        self.events.append(kwargs)


class FakeBrowser:
    pass


@pytest.mark.asyncio
async def test_execution_error_is_redacted_from_persistent_state():
    database = FakeDatabase()
    manager = TaskManager(
        database=database,
        browser=FakeBrowser(),
        agent=SimpleNamespace(),
        notifications=SimpleNamespace(),
        settings=SimpleNamespace(),
    )

    await manager._execute(7)

    assert database.card["status"] == "error"
    assert database.card["error_message"] == "execution_failed"
    assert "TOP-SECRET" not in str(database.card)
    error_events = [event for event in database.events if event["event_type"] == "task_error"]
    assert error_events
    assert "TOP-SECRET" not in str(error_events[-1])
    assert error_events[-1]["message"] == "حدث خطأ أثناء تنفيذ المهمة. راجع سجل النظام للتفاصيل."
