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
async def test_global_network_admin_gate_rejects_non_admin(monkeypatch):
    monkeypatch.setattr(main, "_require_session", lambda _request: "test-session")
    monkeypatch.setattr(main._active_sessions, "user_id", lambda _token: 2)

    with pytest.raises(HTTPException) as exc:
        main._require_admin_session(make_request())

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_global_network_admin_gate_allows_bootstrap_admin(monkeypatch):
    monkeypatch.setattr(main, "_require_session", lambda _request: "test-session")
    monkeypatch.setattr(
        main._active_sessions,
        "user_id",
        lambda _token: OwnershipStore.BOOTSTRAP_USER_ID,
    )

    assert await main._require_admin_session(make_request()) == "test-session"
