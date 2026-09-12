from app.main import app


def test_network_policy_routes_are_mounted():
    import app.network_policy_api as network_policy_api

    app_paths = {getattr(route, "path", "") for route in app.routes}
    router_paths = {getattr(route, "path", "") for route in network_policy_api.router.routes}
    assert "/api/network-policy/{project_id}" in router_paths
    assert "/api/network-policy/{project_id}/verify" in router_paths
    assert any(path.endswith("/api/network-policy/{project_id}") for path in app_paths)
    assert any(path.endswith("/api/network-policy/{project_id}/verify") for path in app_paths)
