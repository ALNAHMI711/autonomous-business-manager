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


def make_scope(path: str) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [(b"cookie", b"session=test-session")],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    }


async def collect_response(app, scope):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


@pytest.mark.asyncio
@pytest.mark.parametrize("path", sorted(ProjectAccessMiddleware.GLOBAL_ADMIN_PATHS))
async def test_non_admin_is_blocked_from_global_admin_paths(tmp_path, path):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    middleware = ProjectAccessMiddleware(_ok_app, database)
    middleware._user_id = lambda _headers: 2

    messages = await collect_response(middleware, make_scope(path))

    assert messages[0]["status"] == 403
    payload = json.loads(messages[1]["body"].decode("utf-8"))
    assert payload["detail"] == "هذه العملية متاحة للمدير فقط."


@pytest.mark.asyncio
async def test_bootstrap_admin_reaches_global_admin_endpoint(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    middleware = ProjectAccessMiddleware(_ok_app, database)
    middleware._user_id = lambda _headers: OwnershipStore.BOOTSTRAP_USER_ID

    messages = await collect_response(
        middleware,
        make_scope("/api/network/profiles"),
    )

    assert messages[0]["status"] == 200
