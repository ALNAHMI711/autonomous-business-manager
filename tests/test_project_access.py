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

    with sqlite3.connect(str(tmp_path / "test.db")) as connection:
        connection.execute(
            "INSERT INTO projects(name, description, status, workflow_type, created_at, updated_at, owner_id) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?)",
            ("owner-one", "", "active", "assistant", 1),
        )
        connection.execute(
            "INSERT INTO projects(name, description, status, workflow_type, created_at, updated_at, owner_id) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?)",
            ("owner-two", "", "active", "assistant", second_user),
        )
        connection.commit()

    auth = AuthStore(str(tmp_path / "test.db"))
    auth.initialize()
    auth.create(hash_session_token("user-one-session"), user_id=1)
    auth.create(hash_session_token("user-two-session"), user_id=second_user)

    app = FastAPI()
    app.add_middleware(ProjectAccessMiddleware, database=database)

    @app.get("/api/projects/{project_id}")
    async def project(project_id: int):
        return {"project_id": project_id}

    @app.get("/api/work-cards/{card_id}")
    async def card(card_id: int):
        return {"card_id": card_id}

    @app.post("/api/chat")
    async def chat(payload: dict):
        return payload

    return app


def test_project_owner_can_access_own_project(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.get("/api/projects/1", cookies={"session": "user-one-session"})
    assert response.status_code == 200
    assert response.json() == {"project_id": 1}


def test_project_owner_cannot_access_foreign_project(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.get("/api/projects/2", cookies={"session": "user-one-session"})
    assert response.status_code == 404


def test_second_user_cannot_access_first_users_project(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.get("/api/projects/1", cookies={"session": "user-two-session"})
    assert response.status_code == 404


def test_project_id_in_json_body_is_owner_checked_and_body_is_replayed(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.post(
        "/api/chat",
        json={"message": "hello", "project_id": 1},
        cookies={"session": "user-one-session"},
    )
    assert response.status_code == 200
    assert response.json()["project_id"] == 1


def test_foreign_project_id_in_json_body_is_rejected(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.post(
        "/api/chat",
        json={"message": "hello", "project_id": 2},
        cookies={"session": "user-one-session"},
    )
    assert response.status_code == 404
