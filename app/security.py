from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.passwords import PasswordService


class SecurityManager:
    """Security utilities for authentication, sessions, and secret encryption."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self._fernet = self._build_fernet()
        self._passwords = PasswordService()

    def _build_fernet(self) -> Optional[Fernet]:
        key = getattr(self.settings, "encryption_key", "")
        if not key:
            return None
        try:
            return Fernet(key.encode("utf-8"))
        except Exception:
            return None

    @property
    def encryption_available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if not self._fernet:
            raise RuntimeError("Encryption is not configured. Set ENCRYPTION_KEY to a valid Fernet key.")
        if value is None:
            raise ValueError("Cannot encrypt None.")
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_value: str) -> str:
        if not self._fernet:
            raise RuntimeError("Encryption is not configured. Set ENCRYPTION_KEY to a valid Fernet key.")
        if not encrypted_value:
            return ""
        try:
            return self._fernet.decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt the stored secret.") from exc

    @staticmethod
    def hash_password(password: str, salt: Optional[bytes] = None) -> str:
        if not isinstance(password, str):
            raise TypeError("Password must be a string.")
        if not password:
            raise ValueError("Password cannot be empty.")
        iterations = 310_000
        salt = secrets.token_bytes(32) if salt is None else salt
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
        digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
        return f"pbkdf2_sha256${iterations}${salt_b64}${digest_b64}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        if not password or not stored_hash:
            return False
        try:
            algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
            expected_digest = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
            actual_digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, int(iterations)
            )
            return hmac.compare_digest(actual_digest, expected_digest)
        except (ValueError, TypeError, UnicodeError):
            return False

    @staticmethod
    def generate_session_token() -> str:
        return secrets.token_urlsafe(48)

    @staticmethod
    def hash_session_token(token: str) -> str:
        if not token:
            raise ValueError("Session token cannot be empty.")
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_secret_id() -> str:
        return secrets.token_urlsafe(24)

    @staticmethod
    def generate_event_id() -> str:
        return secrets.token_urlsafe(24)

    @staticmethod
    def generate_approval_id() -> str:
        return secrets.token_urlsafe(24)

    @staticmethod
    def mask_secret(value: Optional[str], visible_start: int = 2, visible_end: int = 2) -> str:
        if not value:
            return ""
        if len(value) <= visible_start + visible_end:
            return "*" * len(value)
        return f"{value[:visible_start]}{'*' * max(4, len(value) - visible_start - visible_end)}{value[-visible_end:]}"

    def secure_compare(self, first: str, second: str) -> bool:
        if not isinstance(first, str) or not isinstance(second, str):
            return False
        # Backward-compatible login path: accept Argon2id hashes as the stored value.
        if second.startswith("$argon2"):
            return self._passwords.verify(first, second)
        return hmac.compare_digest(first.encode("utf-8"), second.encode("utf-8"))

    @staticmethod
    def generate_encryption_key() -> str:
        return Fernet.generate_key().decode("utf-8")


# Backward-compatible module-level API used by auth_compat.py and older callers.
def hash_session_token(token: str) -> str:
    return SecurityManager.hash_session_token(token)


security_manager = SecurityManager