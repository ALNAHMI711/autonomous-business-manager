from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.project_access import ProjectAccessMiddleware


class FakeDatabase:
    def __init__(self):
        self.projects = {1: {"id": 1}}
        self.cards = {7: {"id": 7, "project_id": 1}}

    def get_project(self, project_id):
        return self.projects.get(project_id)

    def get_work_card(self, card_id):
        return self.cards.get(card_id)


def make_app():
    app = FastAPI()
    app.add_middleware(ProjectAccessMiddleware, database=FakeDatabase())

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


def test_invalid_project_path_is_rejected():
    client = TestClient(make_app())
    response = client.get("/api/projects/999", cookies={"session": "valid"})
    assert response.status_code == 404


def test_existing_project_path_is_allowed():
    client = TestClient(make_app())
    response = client.get("/api/projects/1", cookies={"session": "valid"})
    assert response.status_code == 200
    assert response.json() == {"project_id": 1}


def test_invalid_work_card_is_rejected():
    client = TestClient(make_app())
    response = client.get("/api/work-cards/999", cookies={"session": "valid"})
    assert response.status_code == 404


def test_project_id_in_json_body_is_validated_and_body_is_replayed():
    client = TestClient(make_app())
    response = client.post(
        "/api/chat",
        json={"message": "hello", "project_id": 1},
        cookies={"session": "valid"},
    )
    assert response.status_code == 200
    assert response.json()["project_id"] == 1


def test_invalid_project_id_in_json_body_is_rejected():
    client = TestClient(make_app())
    response = client.post(
        "/api/chat",
        json={"message": "hello", "project_id": 999},
        cookies={"session": "valid"},
    )
    assert response.status_code == 404
