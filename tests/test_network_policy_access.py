import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main
import app.network_policy_api as network_policy_api
from app.auth_store import AuthStore
from app.database import Database
from app.network_policy import NetworkPolicyManager
from app.ownership import OwnershipStore
from app.security import hash_session_token


def make_app(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    ownership = OwnershipStore(str(tmp_path / "test.db"))
    ownership.initialize()
    second_user = ownership.create_user("user2")

    with sqlite3.connect(str(tmp_path / "test.db")) as connection:
        connection.execute(
            "INSERT INTO projects(name, description, status, workflow_type, created_at, updated_at, owner_id) VALUES (?, '', 'active', 'assistant', datetime('now'), datetime('now'), ?)",
            ("owner-one", 1),
        )
        connection.execute(
            "INSERT INTO projects(name, description, status, workflow_type, created_at, updated_at, owner_id) VALUES (?, '', 'active', 'assistant', datetime('now'), datetime('now'), ?)",
            ("owner-two", second_user),
        )
        connection.commit()

    auth = AuthStore(str(tmp_path / "test.db"))
    auth.initialize()
    auth.create(hash_session_token("user-one-session"), user_id=1)
    auth.create(hash_session_token("user-two-session"), user_id=second_user)

    # The router module is imported once by the application, so point its
    # durable dependencies at this isolated test database.
    monkeypatch.setattr(network_policy_api, "db", database)
    monkeypatch.setattr(network_policy_api, "ownership", ownership)
    monkeypatch.setattr(network_policy_api, "auth_store", auth)
    monkeypatch.setattr(
        network_policy_api,
        "manager",
        NetworkPolicyManager(database, main.security, main.network_manager),
    )
    monkeypatch.setattr(
        network_policy_api,
        "_require_session",
        lambda request: request.cookies.get("session") or "",
    )

    app = FastAPI()
    app.include_router(network_policy_api.router)
    return app


def test_network_policy_foreign_project_is_hidden(tmp_path, monkeypatch):
    client = TestClient(make_app(tmp_path, monkeypatch))
    response = client.get(
        "/api/network-policy/2",
        cookies={"session": "user-one-session"},
    )
    assert response.status_code == 404


def test_network_policy_owner_can_read_and_write(tmp_path, monkeypatch):
    client = TestClient(make_app(tmp_path, monkeypatch))
    response = client.put(
        "/api/network-policy/1",
        json={"expected_country": "YE", "fail_closed": True},
        cookies={"session": "user-one-session"},
    )
    assert response.status_code == 200

    response = client.get(
        "/api/network-policy/1",
        cookies={"session": "user-one-session"},
    )
    assert response.status_code == 200
    assert response.json()["configured"] is True


def test_second_user_cannot_modify_first_users_policy(tmp_path, monkeypatch):
    client = TestClient(make_app(tmp_path, monkeypatch))
    response = client.put(
        "/api/network-policy/1",
        json={"expected_country": "US", "fail_closed": False},
        cookies={"session": "user-two-session"},
    )
    assert response.status_code == 404
