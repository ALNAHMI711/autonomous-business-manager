from __future__ import annotations

from app.auth_store import AuthStore
from app.config import settings
from app.security import hash_session_token
from app.user_credentials import UserCredentialStore


class PersistentSessionSet:
    """Set-compatible adapter backed by AuthStore for restart-safe sessions."""

    def __init__(self) -> None:
        self._store = AuthStore(settings.database_path)
        self._credentials = UserCredentialStore(settings.database_path)
        self._credentials.initialize()

    def add(self, token: str, user_id: int = 1) -> None:
        if not token:
            return
        self._store.create(hash_session_token(token), user_id=user_id)

    def discard(self, token: str) -> None:
        if not token:
            return
        self._store.revoke(hash_session_token(token))

    def __contains__(self, token: object) -> bool:
        if not isinstance(token, str) or not token:
            return False
        return self._store.valid(hash_session_token(token))

    def user_id(self, token: str) -> int | None:
        if not token:
            return None
        return self._store.user_id(hash_session_token(token))

    def purge(self) -> None:
        self._store.purge_expired()

    @property
    def credentials(self) -> UserCredentialStore:
        return self._credentials
