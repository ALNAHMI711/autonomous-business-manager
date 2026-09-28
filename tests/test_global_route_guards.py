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


def test_global_secret_and_network_routes_are_admin_only():
    guarded = [
        ("/api/secrets/unlock", "POST"),
        ("/api/network/profiles", "GET"),
        ("/api/network/profiles", "POST"),
        ("/api/network/test", "POST"),
    ]

    for path, method in guarded:
        assert "_require_admin_session" in _dependency_names(_route(path, method))
