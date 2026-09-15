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
