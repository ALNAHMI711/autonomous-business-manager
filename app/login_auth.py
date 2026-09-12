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
    """Authenticate named users while preserving the legacy bootstrap admin login."""

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

        # The configured bootstrap admin remains available until a durable
        # per-user credential is provisioned. This avoids locking out an
        # existing deployment while moving ordinary users to user credentials.
        if username == self.ADMIN_USERNAME:
            configured = self.security.settings.admin_password
            if configured and self.security.secure_compare(password, configured):
                return AuthenticatedUser(
                    user_id=self.ADMIN_USER_ID,
                    username=self.ADMIN_USERNAME,
                )

        user_id = self.credentials.authenticate(username, password)
        if user_id is None:
            return None

        return AuthenticatedUser(user_id=user_id, username=username)

    def issue_session(self, user: AuthenticatedUser) -> str:
        token = self.security.generate_session_token()
        self.sessions.add(token, user_id=user.user_id)
        return token
