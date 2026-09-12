import importlib


def test_network_policy_routes_are_mounted():
    runtime = importlib.import_module("app.queue_runtime")
    import app.network_policy_api as network_policy_api

    runtime_paths = {getattr(route, "path", "") for route in runtime.app.routes}
    router_paths = {getattr(route, "path", "") for route in network_policy_api.router.routes}
    assert "/api/network-policy/{project_id}" in router_paths
    assert "/api/network-policy/{project_id}/verify" in router_paths
    assert "/api/network-policy/{project_id}" in runtime_paths
    assert "/api/network-policy/{project_id}/verify" in runtime_paths
