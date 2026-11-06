from app.main import app


def _route(path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route
    raise AssertionError(f"route not found: {method} {path}")


def _dependency_names(route):
    return {
        getattr(dependency.call, "__name__", "")
        for dependency in route.dependant.dependencies
    }


def test_per_user_secret_routes_require_an_authenticated_user():
    for path, method in [
        ("/api/my-secrets", "GET"),
        ("/api/my-secrets/{name}", "PUT"),
        ("/api/my-secrets/{name}", "DELETE"),
    ]:
        assert "_require_user_id" in _dependency_names(_route(path, method))


def test_no_route_returns_a_secret_value():
    # Values are only decryptable server-side through UserSecretStore.reveal;
    # no HTTP route may expose a per-user secret value.
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/my-secrets"):
            assert "GET" not in getattr(route, "methods", set()) or path == "/api/my-secrets"
