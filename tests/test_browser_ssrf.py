import pytest

from app.browser import BrowserManager


def manager(tmp_path):
    class Settings:
        browser_profile_directory = tmp_path / "profiles"
        browser_headless = True
        browser_timeout = 1000

    return BrowserManager(Settings(), None)


def test_http_is_limited_to_localhost_hostname(tmp_path):
    browser = manager(tmp_path)
    assert browser._validate_url("http://localhost:8000") == "http://localhost:8000"
    with pytest.raises(ValueError):
        browser._validate_url("http://127.0.0.1:8000")
    with pytest.raises(ValueError):
        browser._validate_url("http://example.com")


def test_private_https_ip_is_blocked(tmp_path):
    browser = manager(tmp_path)
    with pytest.raises(ValueError):
        browser._validate_url("https://127.0.0.1:443")
    with pytest.raises(ValueError):
        browser._validate_url("https://10.0.0.10")
    with pytest.raises(ValueError):
        browser._validate_url("https://192.168.1.10")


def test_embedded_credentials_are_blocked(tmp_path):
    browser = manager(tmp_path)
    with pytest.raises(ValueError):
        browser._validate_url("https://user:password@example.com")


from types import SimpleNamespace


@pytest.mark.asyncio
async def test_guard_request_rechecks_redirect_target(tmp_path):
    browser = manager(tmp_path)

    class FakeRoute:
        def __init__(self, url):
            self.request = SimpleNamespace(url=url)
            self.aborted = None
            self.continued = False

        async def abort(self, reason):
            self.aborted = reason

        async def continue_(self):
            self.continued = True

    blocked = FakeRoute("https://127.0.0.1/private")
    await browser._guard_request(blocked)
    assert blocked.aborted == "blockedbyclient"
    assert blocked.continued is False

    allowed = FakeRoute("https://example.com/")
    browser._resolve_public_hostname = lambda hostname: None
    await browser._guard_request(allowed)
    assert allowed.aborted is None
    assert allowed.continued is True
