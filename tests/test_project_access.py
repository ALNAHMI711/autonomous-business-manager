import sqlite3

from fastapi import FastAPI, Request
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
        for name, owner_id in (("owner-one", 1), ("owner-two", second_user)):
            connection.execute(
                "INSERT INTO projects(name, description, status, workflow_type, created_at, updated_at, owner_id) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?)",
                (name, "", "active", "assistant", owner_id),
            )
        connection.execute(
            "INSERT INTO work_cards(title, description, project_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("card-one", "", 1, "draft"),
        )
        connection.execute(
            "INSERT INTO work_cards(title, description, project_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("card-two", "", 2, "draft"),
        )
        connection.commit()

    auth = AuthStore(str(tmp_path / "test.db"))
    auth.initialize()
    auth.create(hash_session_token("user-one-session"), user_id=1)
    auth.create(hash_session_token("user-two-session"), user_id=second_user)

    app = FastAPI()
    app.add_middleware(ProjectAccessMiddleware, database=database)

    @app.get("/api/projects")
    async def projects():
        return {"projects": database.list_projects()}

    @app.get("/api/work-cards")
    async def work_cards(request: Request):
        project_id = request.query_params.get("project_id")
        cards = database.list_all_work_cards()
        if project_id is not None:
            cards = [card for card in cards if str(card["project_id"]) == project_id]
        return {"work_cards": cards}

    @app.get("/api/projects/{project_id}")
    async def project(project_id: int):
        return {"project_id": project_id}

    @app.get("/api/work-cards/{card_id}")
    async def card(card_id: int):
        return {"card_id": card_id}

    @app.post("/api/work-cards/{card_id}/action")
    async def card_action(card_id: int, payload: dict):
        return {"card_id": card_id, **payload}

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


def test_project_listing_is_owner_filtered(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.get("/api/projects", cookies={"session": "user-one-session"})
    assert response.status_code == 200
    assert [project["id"] for project in response.json()["projects"]] == [1]


def test_work_card_listing_is_owner_filtered(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.get("/api/work-cards", cookies={"session": "user-one-session"})
    assert response.status_code == 200
    assert [card["project_id"] for card in response.json()["work_cards"]] == [1]


def test_work_card_query_project_must_be_owned(tmp_path):
    client = TestClient(make_app(tmp_path))
    own = client.get(
        "/api/work-cards?project_id=1",
        cookies={"session": "user-one-session"},
    )
    foreign = client.get(
        "/api/work-cards?project_id=2",
        cookies={"session": "user-one-session"},
    )
    assert own.status_code == 200
    assert [card["id"] for card in own.json()["work_cards"]] == [1]
    assert foreign.status_code == 404


def test_work_card_owner_can_access_action_endpoint(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.post(
        "/api/work-cards/1/action",
        json={"action": "approve"},
        cookies={"session": "user-one-session"},
    )
    assert response.status_code == 200
    assert response.json()["card_id"] == 1


def test_work_card_action_cannot_cross_project_boundary(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.post(
        "/api/work-cards/2/action",
        json={"action": "approve"},
        cookies={"session": "user-one-session"},
    )
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
