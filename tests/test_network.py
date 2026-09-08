from app.network import NetworkProfile


def test_direct_profile_has_no_proxy():
    profile = NetworkProfile(name="phone-direct")
    assert profile.to_playwright_proxy() is None


def test_http_proxy_profile_is_translated_for_playwright():
    profile = NetworkProfile(
        name="proxy",
        mode="proxy",
        proxy_server="http://127.0.0.1:8080",
        username="user",
        password="secret",
        bypass="localhost",
    )
    assert profile.to_playwright_proxy() == {
        "server": "http://127.0.0.1:8080",
        "username": "user",
        "password": "secret",
        "bypass": "localhost",
    }


def test_proxy_scheme_must_be_supported():
    profile = NetworkProfile(
        name="bad",
        mode="proxy",
        proxy_server="ftp://127.0.0.1:21",
    )
    try:
        profile.validate()
    except ValueError as exc:
        assert "http" in str(exc)
    else:
        raise AssertionError("unsupported proxy scheme was accepted")
