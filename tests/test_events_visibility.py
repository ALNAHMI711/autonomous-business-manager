import pytest

from app.ownership import OwnershipStore
from app.queue_runtime import events


class FakeRequest:
    def __init__(self, user_id: int):
        self.user_id = user_id


@pytest.mark.asyncio
async def test_events_filters_foreign_and_global_events(monkeypatch):
    import app.queue_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "_require_control_session",
        lambda _request: 2,
    )
    monkeypatch.setattr(
        runtime.ownership,
        "list_project_ids",
        lambda _user_id: [10],
    )
    monkeypatch.setattr(
        runtime.db,
        "list_events",
        lambda limit=200: [
            {"id": 1, "project_id": 10, "message": "owned"},
            {"id": 2, "project_id": 20, "message": "foreign"},
            {"id": 3, "project_id": None, "message": "global"},
        ],
    )

    response = await events(FakeRequest(2))

    assert response.status_code == 200
    assert b"owned" in response.body
    assert b"foreign" not in response.body
    assert b"global" not in response.body


@pytest.mark.asyncio
async def test_admin_can_see_global_events(monkeypatch):
    import app.queue_runtime as runtime

    admin_id = OwnershipStore.BOOTSTRAP_USER_ID
    monkeypatch.setattr(
        runtime,
        "_require_control_session",
        lambda _request: admin_id,
    )
    monkeypatch.setattr(
        runtime.ownership,
        "list_project_ids",
        lambda _user_id: [10],
    )
    monkeypatch.setattr(
        runtime.db,
        "list_events",
        lambda limit=200: [
            {"id": 1, "project_id": 10, "message": "owned"},
            {"id": 2, "project_id": None, "message": "global"},
        ],
    )

    response = await events(FakeRequest(admin_id))

    assert response.status_code == 200
    assert b"owned" in response.body
    assert b"global" in response.body
