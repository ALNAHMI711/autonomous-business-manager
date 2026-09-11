from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional


class CSRFProtector:
    """Session-bound CSRF token helper.

    The token is derived from the authenticated session token and a server-side
    secret. The raw session cookie remains HttpOnly; only the CSRF token may be
    exposed to browser JavaScript.
    """

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("CSRF secret must not be empty")
        self._secret = secret.encode("utf-8")

    @staticmethod
    def generate_nonce() -> str:
        return secrets.token_urlsafe(32)

    def issue(self, session_token: str) -> str:
        if not session_token:
            raise ValueError("Session token must not be empty")
        digest = hmac.new(
            self._secret,
            session_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest

    def verify(self, session_token: str, supplied_token: Optional[str]) -> bool:
        if not session_token or not supplied_token:
            return False
        expected = self.issue(session_token)
        return hmac.compare_digest(expected, supplied_token)
