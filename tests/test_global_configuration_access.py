from app import main
from app.network import NetworkProfile


def test_global_network_and_secret_routes_require_admin():
    protected_paths = {
        ("GET", "/api/network/profiles"),
        ("POST", "/api/network/profiles"),
        ("POST", "/api/network/test"),
        ("POST", "/api/secrets/unlock"),
    }

    routes = {
        (method, route.path): route
        for route in main.app.routes
        if hasattr(route, "dependant")
        for method in (route.methods or set())
    }

    for key in protected_paths:
        route = routes[key]
        dependencies = [dependency.call for dependency in route.dependant.dependencies]
        assert main._require_admin_session in dependencies, key


def test_masked_network_profile_never_exposes_password():
    profile = NetworkProfile(
        name="test-proxy",
        mode="proxy",
        proxy_server="http://127.0.0.1:8080",
        username="proxy-user",
        password="highly-sensitive-password",
    )

    masked = profile.masked()

    assert masked["has_password"] is True
    assert "password" not in masked
    assert "highly-sensitive-password" not in repr(masked)
