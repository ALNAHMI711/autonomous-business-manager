import pytest
from starlette.requests import Request

from app import queue_runtime
from app.ownership import OwnershipStore


def make_request(token: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/control/kill-switch",
        "headers": [(b"cookie", f"session={token}".encode())],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    })


@pytest.mark.asyncio
async def test_global_control_rejects_non_admin(monkeypatch):
    async def require_session(_request):
        return 2

    monkeypatch.setattr(queue_runtime, "_require_control_session", require_session)

    with pytest.raises(Exception) as exc:
        await queue_runtime._require_admin_control(make_request("user-two-session"))

    assert exc.value.status_code == 403
    assert OwnershipStore.BOOTSTRAP_USER_ID == 1


@pytest.mark.asyncio
async def test_global_control_allows_bootstrap_admin(monkeypatch):
    async def require_session(_request):
        return OwnershipStore.BOOTSTRAP_USER_ID

    monkeypatch.setattr(queue_runtime, "_require_control_session", require_session)

    assert await queue_runtime._require_admin_control(make_request("admin-session")) == 1
