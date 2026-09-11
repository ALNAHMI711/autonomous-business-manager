from __future__ import annotations

import sqlite3

from app.auth_store import AuthStore


def test_session_lifecycle(tmp_path):
    store = AuthStore(str(tmp_path / "app.db"), ttl_seconds=300)
    store.initialize()

    token_hash = "a" * 64
    store.create(token_hash)
    assert store.valid(token_hash) is True

    store.revoke(token_hash)
    assert store.valid(token_hash) is False


def test_unknown_session_is_invalid(tmp_path):
    store = AuthStore(str(tmp_path / "app.db"))
    store.initialize()
    assert store.valid("missing") is False


def test_session_survives_store_recreation(tmp_path):
    database_path = tmp_path / "app.db"
    token_hash = "b" * 64

    first = AuthStore(str(database_path), ttl_seconds=300)
    first.initialize()
    first.create(token_hash)

    restarted = AuthStore(str(database_path), ttl_seconds=300)
    restarted.initialize()
    assert restarted.valid(token_hash) is True


def test_expired_session_is_invalid_and_purgeable(tmp_path):
    database_path = tmp_path / "app.db"
    token_hash = "c" * 64
    store = AuthStore(str(database_path), ttl_seconds=300)
    store.initialize()
    store.create(token_hash)

    expired = "2000-01-01T00:00:00+00:00"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE token_hash = ?",
            (expired, token_hash),
        )

    assert store.valid(token_hash) is False
    assert store.purge_expired() == 1
    assert store.valid(token_hash) is False


def test_raw_token_is_never_persisted(tmp_path):
    database_path = tmp_path / "app.db"
    raw_token = "raw-session-token-value"
    token_hash = "d" * 64
    store = AuthStore(str(database_path))
    store.initialize()
    store.create(token_hash)

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT token_hash FROM auth_sessions"
        ).fetchall()

    assert raw_token not in {row[0] for row in rows}
    assert token_hash in {row[0] for row in rows}
