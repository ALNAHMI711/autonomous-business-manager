from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_store import AuthStore
from app.database import Database
from app.ownership import OwnershipStore
from app.project_access import ProjectAccessMiddleware
from app.security import hash_session_token


def make_app(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()

    ownership = OwnershipStore(str(tmp_path / "test.db"))
    ownership.initialize()
    second_user = ownership.create_user("user2")

    auth = AuthStore(str(tmp_path / "test.db"))
    auth.initialize()
    auth.create(hash_session_token("admin-session"), user_id=1)
    auth.create(hash_session_token("user-session"), user_id=second_user)

    app = FastAPI()
    app.add_middleware(ProjectAccessMiddleware, database=database)

    @app.get("/api/network/profiles")
    async def network_profiles():
        return {"ok": True}

    @app.post("/api/network/profiles")
    async def create_network_profile():
        return {"ok": True}

    @app.post("/api/network/test")
    async def network_test():
        return {"ok": True}

    @app.post("/api/secrets/unlock")
    async def unlock_secrets():
        return {"ok": True}

    return app


def test_non_admin_cannot_read_global_network_profiles(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.get(
        "/api/network/profiles",
        cookies={"session": "user-session"},
    )
    assert response.status_code == 403


def test_non_admin_cannot_modify_global_network_controls(tmp_path):
    client = TestClient(make_app(tmp_path))
    for method, path in (
        ("post", "/api/network/profiles"),
        ("post", "/api/network/test"),
        ("post", "/api/secrets/unlock"),
    ):
        response = getattr(client, method)(
            path,
            cookies={"session": "user-session"},
        )
        assert response.status_code == 403


def test_admin_can_access_global_network_and_secret_controls(tmp_path):
    client = TestClient(make_app(tmp_path))
    assert client.get(
        "/api/network/profiles",
        cookies={"session": "admin-session"},
    ).status_code == 200
    assert client.post(
        "/api/network/profiles",
        cookies={"session": "admin-session"},
    ).status_code == 200
    assert client.post(
        "/api/network/test",
        cookies={"session": "admin-session"},
    ).status_code == 200
    assert client.post(
        "/api/secrets/unlock",
        cookies={"session": "admin-session"},
    ).status_code == 200
