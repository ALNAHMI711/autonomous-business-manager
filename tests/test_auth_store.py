from __future__ import annotations

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
