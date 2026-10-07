import pytest
from fastapi import HTTPException

from app import main


@pytest.mark.asyncio
async def test_browser_open_rejects_unbound_network_profile(monkeypatch):
    class FakeProfile:
        name = "approved-proxy"

    monkeypatch.setattr(main.network_manager, "get_project_profile", lambda _project_id: FakeProfile())

    async def fail_if_called(**_kwargs):
        raise AssertionError("browser.open must not run for an unbound profile")

    monkeypatch.setattr(main.browser, "open", fail_if_called)

    request = main.BrowserOpenRequest(
        project_id=10,
        site="https://example.com",
        network_profile="other-proxy",
    )

    with pytest.raises(HTTPException) as exc:
        await main.browser_open(request, "session")

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_browser_open_uses_project_bound_profile(monkeypatch):
    class FakeProfile:
        name = "approved-proxy"

    monkeypatch.setattr(main.network_manager, "get_project_profile", lambda _project_id: FakeProfile())

    captured = {}

    async def fake_open(**kwargs):
        captured.update(kwargs)
        return {"status": "connected"}

    monkeypatch.setattr(main.browser, "open", fake_open)

    request = main.BrowserOpenRequest(
        project_id=10,
        site="https://example.com",
    )

    response = await main.browser_open(request, "session")

    assert response["success"] is True
    assert captured["network_profile"] == "approved-proxy"
