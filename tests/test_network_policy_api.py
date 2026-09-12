from fastapi.testclient import TestClient

from app.main import app


def test_network_policy_routes_are_mounted():
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/network-policy/{project_id}" in paths
    assert "/api/network-policy/{project_id}/verify" in paths
