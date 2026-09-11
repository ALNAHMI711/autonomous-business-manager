from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.csrf import CSRFProtector
from app.csrf_middleware import CSRFSecurityMiddleware


SECRET = "test-csrf-secret"
SESSION = "test-session-token"


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CSRFSecurityMiddleware, secret=SECRET)

    @app.get("/api/read")
    async def read():
        return {"ok": True}

    @app.post("/api/write")
    async def write():
        return {"ok": True}

    @app.post("/api/login")
    async def login():
        return JSONResponse({"ok": True})

    return app


def test_same_origin_unsafe_request_is_allowed():
    client = TestClient(make_app())
    response = client.post(
        "/api/write",
        cookies={"session": SESSION},
        headers={"Origin": "http://testserver", "Host": "testserver"},
    )
    assert response.status_code == 200
    assert response.headers["x-csrf-token"] == CSRFProtector(SECRET).issue(SESSION)


def test_cross_origin_unsafe_request_is_blocked_without_token():
    client = TestClient(make_app())
    response = client.post(
        "/api/write",
        cookies={"session": SESSION},
        headers={"Origin": "https://attacker.example", "Host": "testserver"},
    )
    assert response.status_code == 403


def test_valid_session_bound_token_allows_cross_origin_header_case():
    client = TestClient(make_app())
    token = CSRFProtector(SECRET).issue(SESSION)
    response = client.post(
        "/api/write",
        cookies={"session": SESSION},
        headers={
            "Origin": "https://attacker.example",
            "Host": "testserver",
            "X-CSRF-Token": token,
        },
    )
    assert response.status_code == 200


def test_token_for_other_session_is_rejected_cross_origin():
    client = TestClient(make_app())
    token = CSRFProtector(SECRET).issue("other-session")
    response = client.post(
        "/api/write",
        cookies={"session": SESSION},
        headers={
            "Origin": "https://attacker.example",
            "Host": "testserver",
            "X-CSRF-Token": token,
        },
    )
    assert response.status_code == 403


def test_login_is_exempt_for_initial_authentication():
    client = TestClient(make_app())
    response = client.post(
        "/api/login",
        headers={"Origin": "https://attacker.example", "Host": "testserver"},
    )
    assert response.status_code == 200
