import importlib


def test_network_policy_routes_are_mounted():
    runtime = importlib.import_module("app.queue_runtime")
    import app.network_policy_api as network_policy_api

    router_endpoints = {
        getattr(route, "endpoint", None)
        for route in network_policy_api.router.routes
        if getattr(route, "endpoint", None) is not None
    }
    runtime_endpoints = {
        getattr(route, "endpoint", None)
        for route in runtime.app.routes
        if getattr(route, "endpoint", None) is not None
    }

    assert router_endpoints
    assert router_endpoints <= runtime_endpoints
