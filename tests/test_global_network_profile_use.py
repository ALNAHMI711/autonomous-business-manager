import json

import pytest

from app.database import Database
from app.ownership import OwnershipStore
from app.project_access import ProjectAccessMiddleware


async def _ok_app(scope, receive, send):
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({
        "type": "http.response.body",
        "body": b"{}",
    })


def make_scope(body: bytes) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/browser/open",
        "headers": [
            (b"cookie", b"session=test-session"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    }


async def collect_response(app, scope, body: bytes):
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

    await app(scope, receive, send)
    return messages


@pytest.mark.asyncio
async def test_non_admin_cannot_use_global_network_profile(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    middleware = ProjectAccessMiddleware(_ok_app, database)
    middleware._user_id = lambda _headers: 2
    middleware._validate_project = lambda _project_id, _user_id: True

    body = json.dumps({
        "project_id": 1,
        "site": "example",
        "network_profile": "admin-proxy",
    }).encode("utf-8")
    messages = await collect_response(middleware, make_scope(body), body)

    assert messages[0]["status"] == 403
    payload = json.loads(messages[1]["body"].decode("utf-8"))
    assert payload["detail"] == "استخدام ملفات الشبكة العامة متاح للمدير فقط."


@pytest.mark.asyncio
async def test_admin_can_use_global_network_profile(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    middleware = ProjectAccessMiddleware(_ok_app, database)
    middleware._user_id = lambda _headers: OwnershipStore.BOOTSTRAP_USER_ID
    middleware._validate_project = lambda _project_id, _user_id: True

    body = json.dumps({
        "project_id": 1,
        "site": "example",
        "network_profile": "admin-proxy",
    }).encode("utf-8")
    messages = await collect_response(middleware, make_scope(body), body)

    assert messages[0]["status"] == 200
