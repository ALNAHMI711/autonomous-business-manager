import json

import pytest
from starlette.requests import Request

from app import queue_runtime
from app.ownership import OwnershipStore


def make_request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/events",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    })


def response_payload(response):
    return json.loads(response.body.decode("utf-8"))


@pytest.mark.asyncio
async def test_events_hide_foreign_project_and_global_events_from_regular_user(monkeypatch):
    monkeypatch.setattr(queue_runtime, "_require_control_session", lambda _request: 2)
    monkeypatch.setattr(queue_runtime.ownership, "list_project_ids", lambda _user_id: [10])
    monkeypatch.setattr(
        queue_runtime.db,
        "list_events",
        lambda limit=200: [
            {"id": 1, "project_id": 10, "message": "own"},
            {"id": 2, "project_id": 20, "message": "foreign"},
            {"id": 3, "project_id": None, "message": "global"},
        ],
    )

    response = await queue_runtime.events(make_request())

    assert response.status_code == 200
    assert response_payload(response) == [
        {"id": 1, "project_id": 10, "message": "own"},
    ]


@pytest.mark.asyncio
async def test_events_allow_global_events_for_bootstrap_admin(monkeypatch):
    admin_id = OwnershipStore.BOOTSTRAP_USER_ID
    monkeypatch.setattr(queue_runtime, "_require_control_session", lambda _request: admin_id)
    monkeypatch.setattr(queue_runtime.ownership, "list_project_ids", lambda _user_id: [10])
    monkeypatch.setattr(
        queue_runtime.db,
        "list_events",
        lambda limit=200: [
            {"id": 1, "project_id": 10, "message": "own"},
            {"id": 2, "project_id": None, "message": "global"},
        ],
    )

    response = await queue_runtime.events(make_request())

    assert response.status_code == 200
    assert response_payload(response) == [
        {"id": 1, "project_id": 10, "message": "own"},
        {"id": 2, "project_id": None, "message": "global"},
    ]
