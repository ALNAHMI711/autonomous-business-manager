import json

import pytest

from app.database import Database
from app.project_access import ProjectAccessMiddleware


class Downstream:
    def __init__(self):
        self.called = False
        self.body = b""

    async def __call__(self, scope, receive, send):
        self.called = True
        message = await receive()
        self.body = message.get("body", b"")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


def make_scope(method: str, path: str, query: bytes = b""):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(b"cookie", b"session=t"), (b"content-type", b"application/json")],
        "query_string": query,
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    }


async def call(middleware, scope, body: bytes = b""):
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware(scope, receive, send)
    return messages


def build(tmp_path, owned):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    downstream = Downstream()
    middleware = ProjectAccessMiddleware(downstream, database)
    middleware._user_id = lambda _headers: 2
    middleware._validate_project = lambda project_id, _user: int(project_id) in owned
    return middleware, downstream


@pytest.mark.asyncio
async def test_body_project_is_checked_even_when_query_project_is_owned(tmp_path):
    middleware, downstream = build(tmp_path, owned={5})
    body = json.dumps({"project_id": 9, "selector": "#x"}).encode()
    messages = await call(middleware, make_scope("POST", "/api/browser/click", b"project_id=5"), body)
    assert messages[0]["status"] == 404
    assert downstream.called is False


@pytest.mark.asyncio
async def test_body_project_is_checked_when_path_project_is_owned(tmp_path):
    middleware, downstream = build(tmp_path, owned={5})
    body = json.dumps({"project_id": 9}).encode()
    messages = await call(middleware, make_scope("POST", "/api/browser/close/5"), body)
    assert messages[0]["status"] == 404
    assert downstream.called is False


@pytest.mark.asyncio
async def test_matching_owned_ids_pass_and_body_is_replayed(tmp_path):
    middleware, downstream = build(tmp_path, owned={5})
    body = json.dumps({"project_id": 5, "selector": "#x"}).encode()
    messages = await call(middleware, make_scope("POST", "/api/browser/click", b"project_id=5"), body)
    assert messages[0]["status"] == 200
    assert downstream.body == body


@pytest.mark.asyncio
async def test_non_object_json_body_does_not_crash_and_chat_still_needs_project(tmp_path):
    middleware, downstream = build(tmp_path, owned={5})
    messages = await call(middleware, make_scope("POST", "/api/chat"), b"[1, 2]")
    assert messages[0]["status"] == 400
    assert downstream.called is False
