from __future__ import annotations

from dataclasses import dataclass

from app.auth_compat import PersistentSessionSet
from app.security import SecurityManager
from app.user_credentials import UserCredentialStore


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: int
    username: str


class LoginAuthenticator:
    """Authenticate named users with durable Argon2id credentials."""

    ADMIN_USER_ID = 1
    ADMIN_USERNAME = "admin"

    def __init__(
        self,
        sessions: PersistentSessionSet,
        security: SecurityManager,
        credentials: UserCredentialStore | None = None,
    ) -> None:
        self.sessions = sessions
        self.security = security
        self.credentials = credentials or sessions.credentials
        self.credentials.initialize()

    def authenticate(self, username: str, password: str) -> AuthenticatedUser | None:
        username = username.strip()
        if not username or not password:
            return None

        user_id = self.credentials.authenticate(username, password)
        if user_id is not None:
            return AuthenticatedUser(user_id=user_id, username=username)

        # Migration compatibility for an existing deployment that still has
        # only the configured bootstrap admin credential.
        if username == self.ADMIN_USERNAME:
            configured_hash = getattr(self.security.settings, "admin_password_hash", "")
            if configured_hash and self.security.secure_compare(password, configured_hash):
                return AuthenticatedUser(
                    user_id=self.ADMIN_USER_ID,
                    username=self.ADMIN_USERNAME,
                )

            configured_legacy = getattr(self.security.settings, "admin_password", "")
            if configured_legacy and self.security.secure_compare(password, configured_legacy):
                return AuthenticatedUser(
                    user_id=self.ADMIN_USER_ID,
                    username=self.ADMIN_USERNAME,
                )

        return None

    def issue_session(self, user: AuthenticatedUser) -> str:
        token = self.security.generate_session_token()
        self.sessions.add(token, user_id=user.user_id)
        return token
