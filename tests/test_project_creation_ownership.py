import sqlite3

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
    auth.create(hash_session_token("user-one-session"), user_id=1)
    auth.create(hash_session_token("user-two-session"), user_id=second_user)

    app = FastAPI()
    app.add_middleware(ProjectAccessMiddleware, database=database)

    @app.post("/api/projects")
    async def create_project(payload: dict):
        return {"project": database.create_project(payload["name"])}

    return app, ownership, second_user


def test_new_project_is_bound_to_authenticated_owner(tmp_path):
    app, ownership, _ = make_app(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/projects",
        json={"name": "user-two-project"},
        cookies={"session": "user-two-session"},
    )
    assert response.status_code == 200
    project_id = response.json()["project"]["id"]
    assert ownership.project_owner(project_id) == 2


def test_new_project_cannot_leak_to_other_owner_listing(tmp_path):
    app, ownership, second_user = make_app(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/projects",
        json={"name": "user-two-project"},
        cookies={"session": "user-two-session"},
    )
    project_id = response.json()["project"]["id"]
    assert ownership.project_owner(project_id) == second_user

    response = client.get(
        "/api/projects",
        cookies={"session": "user-one-session"},
    )
    assert response.status_code == 200
    assert project_id not in [project["id"] for project in response.json()["projects"]]
