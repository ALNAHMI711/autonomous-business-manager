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
        for name, owner_id in (("owner-one", 1), ("owner-two", second_user)):
            connection.execute(
                "INSERT INTO projects(name, description, status, workflow_type, created_at, updated_at, owner_id) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?)",
                (name, "", "active", "assistant", owner_id),
            )
        connection.execute(
            "INSERT INTO work_cards(title, description, project_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("card-one", "", 1, "needs_approval"),
        )
        connection.execute(
            "INSERT INTO work_cards(title, description, project_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("card-two", "", 2, "needs_approval"),
        )
        connection.commit()

    auth = AuthStore(str(tmp_path / "test.db"))
    auth.initialize()
    auth.create(hash_session_token("user-one-session"), user_id=1)
    auth.create(hash_session_token("user-two-session"), user_id=second_user)

    app = FastAPI()
    app.add_middleware(ProjectAccessMiddleware, database=database)

    @app.get("/api/approvals")
    async def approvals():
        return {
            "approvals": [
                {"id": 1, "work_card_id": 1, "action": "approve"},
                {"id": 2, "work_card_id": 2, "action": "approve"},
            ]
        }

    return app


def test_approval_listing_is_owner_filtered(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.get(
        "/api/approvals",
        cookies={"session": "user-one-session"},
    )
    assert response.status_code == 200
    assert [item["work_card_id"] for item in response.json()["approvals"]] == [1]


def test_second_user_sees_only_own_approval_listing(tmp_path):
    client = TestClient(make_app(tmp_path))
    response = client.get(
        "/api/approvals",
        cookies={"session": "user-two-session"},
    )
    assert response.status_code == 200
    assert [item["work_card_id"] for item in response.json()["approvals"]] == [2]
