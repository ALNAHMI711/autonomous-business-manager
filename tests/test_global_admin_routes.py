import pytest
from starlette.requests import Request

from app.project_access import ProjectAccessMiddleware
from app.database import Database


class CaptureApp:
    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send({
            "type": "http.response.body",
            "body": b"ok",
        })


def make_scope(path: str, token: str = "session-token"):
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [(b"cookie", f"session={token}".encode())],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    }


@pytest.mark.asyncio
async def test_non_admin_is_blocked_from_global_admin_routes(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    downstream = CaptureApp()
    middleware = ProjectAccessMiddleware(downstream, database)
    monkeypatch.setattr(middleware, "_user_id", lambda _headers: 2)

    responses = []

    async def send(message):
        responses.append(message)

    await middleware(make_scope("/api/network/profiles"), lambda: None, send)

    assert responses[0]["status"] == 403
    assert downstream.called is False


@pytest.mark.asyncio
async def test_bootstrap_admin_can_reach_global_admin_routes(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    downstream = CaptureApp()
    middleware = ProjectAccessMiddleware(downstream, database)
    monkeypatch.setattr(middleware, "_user_id", lambda _headers: 1)

    responses = []

    async def send(message):
        responses.append(message)

    await middleware(make_scope("/api/network/profiles"), lambda: None, send)

    assert responses[0]["status"] == 200
    assert downstream.called is True


@pytest.mark.asyncio
async def test_non_admin_is_blocked_from_secret_unlock(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    downstream = CaptureApp()
    middleware = ProjectAccessMiddleware(downstream, database)
    monkeypatch.setattr(middleware, "_user_id", lambda _headers: 2)

    responses = []

    async def send(message):
        responses.append(message)

    await middleware(make_scope("/api/secrets/unlock"), lambda: None, send)

    assert responses[0]["status"] == 403
    assert downstream.called is False
