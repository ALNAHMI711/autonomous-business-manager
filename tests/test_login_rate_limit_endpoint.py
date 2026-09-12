import importlib

from fastapi.testclient import TestClient


def _configure_login_test(monkeypatch, tmp_path):
    main = importlib.import_module("app.main")
    db_path = tmp_path / "app.db"
    limiter = main.LoginRateLimiter(db_path, max_failures=5, window_seconds=300)
    monkeypatch.setattr(main, "_login_rate_limiter", limiter)
    monkeypatch.setattr(main.settings, "database_path", db_path)
    monkeypatch.setattr(main.settings, "admin_password", "correct-password")

    # Named-user authentication now initializes a durable users table.
    # Keep this endpoint test isolated from the application's real database.
    main.OwnershipStore(str(db_path)).initialize()

    sessions = main.PersistentSessionSet()
    sessions._store.initialize()
    monkeypatch.setattr(main, "_active_sessions", sessions)
    return main


def test_login_endpoint_rate_limits_failed_attempts(monkeypatch, tmp_path):
    main = _configure_login_test(monkeypatch, tmp_path)

    client = TestClient(main.app)
    for _ in range(4):
        response = client.post("/api/login", json={"password": "wrong-password"})
        assert response.status_code == 401

    response = client.post("/api/login", json={"password": "wrong-password"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "300"


def test_login_success_clears_failed_attempts(monkeypatch, tmp_path):
    main = _configure_login_test(monkeypatch, tmp_path)

    client = TestClient(main.app)
    for _ in range(4):
        assert client.post("/api/login", json={"password": "wrong-password"}).status_code == 401

    response = client.post("/api/login", json={"password": "correct-password"})
    assert response.status_code == 200

    assert client.post("/api/login", json={"password": "wrong-password"}).status_code == 401
