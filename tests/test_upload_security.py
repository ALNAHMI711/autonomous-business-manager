import json
import sqlite3

from fastapi import FastAPI, File, UploadFile
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
        connection.commit()

    auth = AuthStore(str(tmp_path / "test.db"))
    auth.initialize()
    auth.create(hash_session_token("user-one-session"), user_id=1)
    auth.create(hash_session_token("user-two-session"), user_id=second_user)

    upload_dir = tmp_path / "uploads"

    app = FastAPI()
    app.add_middleware(ProjectAccessMiddleware, database=database)

    @app.post("/api/uploads")
    async def upload(file: UploadFile = File(...)):
        content = await file.read()
        upload_dir.mkdir(parents=True, exist_ok=True)
        path = upload_dir / (file.filename or "upload.bin")
        path.write_bytes(content)
        record = database.save_uploaded_file(
            filename=file.filename or "upload.bin",
            path=str(path),
            size=len(content),
            content_type=file.content_type or "application/octet-stream",
        )
        return {"file": record}

    return app, upload_dir


def test_upload_requires_owned_project(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/uploads?project_id=2",
        files={"file": ("safe.txt", b"secret", "text/plain")},
        cookies={"session": "user-one-session"},
    )

    assert response.status_code == 404


def test_upload_is_project_bound_and_filename_is_unique(tmp_path):
    app, upload_dir = make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/uploads?project_id=1",
        files={"file": ("report.txt", b"hello", "text/plain")},
        cookies={"session": "user-one-session"},
    )

    assert response.status_code == 200
    record = response.json()["file"]
    assert record["project_id"] == 1
    assert record["content_size"] == 5
    metadata = json.loads(record["analysis"])
    assert metadata["original_filename"] == "report.txt"
    assert record["filename"].endswith("_report.txt")
    assert (upload_dir / record["filename"]).read_bytes() == b"hello"


def test_upload_rejects_path_traversal_filename(tmp_path):
    app, upload_dir = make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/uploads?project_id=1",
        files={"file": ("../../escape.txt", b"blocked", "text/plain")},
        cookies={"session": "user-one-session"},
    )

    assert response.status_code == 400
    assert not (tmp_path / "escape.txt").exists()
    assert not upload_dir.exists()
