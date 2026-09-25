import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main
from app.ownership import OwnershipStore


def make_request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/network/profiles",
        "headers": [(b"cookie", b"session=test-session")],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    })


@pytest.mark.asyncio
async def test_global_controls_reject_non_admin(monkeypatch):
    monkeypatch.setattr(main, "_require_session", lambda _request: "user-session")
    monkeypatch.setattr(main._active_sessions, "user_id", lambda _token: 2)

    with pytest.raises(HTTPException) as exc:
        main._require_admin_session(make_request())

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_global_controls_allow_admin(monkeypatch):
    monkeypatch.setattr(main, "_require_session", lambda _request: "admin-session")
    monkeypatch.setattr(
        main._active_sessions,
        "user_id",
        lambda _token: OwnershipStore.BOOTSTRAP_USER_ID,
    )

    assert main._require_admin_session(make_request()) == "admin-session"


def test_global_routes_use_admin_dependency():
    routes = {
        route.path: route
        for route in main.app.routes
        if getattr(route, "path", None) in {
            "/api/network/profiles",
            "/api/network/test",
            "/api/secrets/unlock",
        }
    }

    assert set(routes) == {
        "/api/network/profiles",
        "/api/network/test",
        "/api/secrets/unlock",
    }

    for route in routes.values():
        assert any(
            dependency.call is main._require_admin_session
            for dependency in route.dependant.dependencies
        )
