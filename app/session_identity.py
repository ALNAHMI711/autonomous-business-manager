from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

from app.auth_store import AuthStore
from app.config import settings
from app.security import hash_session_token

_current_user_id: ContextVar[Optional[int]] = ContextVar("current_user_id", default=None)


def set_current_user(user_id: int):
    return _current_user_id.set(int(user_id))


def reset_current_user(token) -> None:
    _current_user_id.reset(token)


def current_user_id() -> Optional[int]:
    return _current_user_id.get()


class SessionIdentity:
    """Resolves a durable session token to its user id."""

    def __init__(self, database_path: str | None = None) -> None:
        self.store = AuthStore(database_path or settings.database_path)
        self.store.initialize()

    def user_id_from_token(self, token: str | None) -> Optional[int]:
        if not token:
            return None
        return self.store.user_id(hash_session_token(token))
