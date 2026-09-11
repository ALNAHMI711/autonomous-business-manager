from __future__ import annotations

from app.auth_store import AuthStore
from app.config import settings
from app.security import hash_session_token


class PersistentSessionSet:
    """Set-compatible adapter backed by AuthStore for restart-safe sessions."""

    def __init__(self) -> None:
        self._store = AuthStore(settings.database_path)

    def add(self, token: str) -> None:
        if not token:
            return
        self._store.create(hash_session_token(token))

    def discard(self, token: str) -> None:
        if not token:
            return
        self._store.revoke(hash_session_token(token))

    def __contains__(self, token: object) -> bool:
        if not isinstance(token, str) or not token:
            return False
        return self._store.valid(hash_session_token(token))

    def purge(self) -> None:
        self._store.purge_expired()
