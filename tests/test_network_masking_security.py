from app.network import NetworkProfile


def test_masked_network_profile_does_not_expose_password():
    profile = NetworkProfile(
        name="proxy",
        mode="proxy",
        proxy_server="http://127.0.0.1:8080",
        username="user",
        password="super-secret",
    )

    masked = profile.masked()

    assert masked["has_password"] is True
    assert "password" not in masked
    assert "super-secret" not in str(masked)
