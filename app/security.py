from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class SecurityManager:
    """
    Security utilities for authentication, sessions, and secret encryption.

    Important:
    - Passwords are never stored in plaintext.
    - Application secrets are encrypted using Fernet.
    - Session tokens are random and are only kept server-side.
    - Sensitive values are never intentionally returned by metadata methods.
    """

    def __init__(self, settings) -> None:
        self.settings = settings
        self._fernet = self._build_fernet()

    # ------------------------------------------------------------------
    # Fernet encryption
    # ------------------------------------------------------------------

    def _build_fernet(self) -> Optional[Fernet]:
        key = getattr(
            self.settings,
            "encryption_key",
            "",
        )

        if not key:
            return None

        try:
            return Fernet(key.encode("utf-8"))
        except Exception:
            # Do not silently create a replacement key.
            # A replacement key would make previously encrypted data
            # impossible to decrypt after restart.
            return None

    @property
    def encryption_available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if not self._fernet:
            raise RuntimeError(
                "Encryption is not configured. "
                "Set ENCRYPTION_KEY to a valid Fernet key."
            )

        if value is None:
            raise ValueError("Cannot encrypt None.")

        encrypted = self._fernet.encrypt(
            value.encode("utf-8")
        )

        return encrypted.decode("utf-8")

    def decrypt(self, encrypted_value: str) -> str:
        if not self._fernet:
            raise RuntimeError(
                "Encryption is not configured. "
                "Set ENCRYPTION_KEY to a valid Fernet key."
            )

        if not encrypted_value:
            return ""

        try:
            decrypted = self._fernet.decrypt(
                encrypted_value.encode("utf-8")
            )

            return decrypted.decode("utf-8")

        except InvalidToken as exc:
            raise ValueError(
                "Unable to decrypt the stored secret."
            ) from exc

    # ------------------------------------------------------------------
    # Password hashing
    # ------------------------------------------------------------------

    @staticmethod
    def hash_password(
        password: str,
        salt: Optional[bytes] = None,
    ) -> str:
        """
        Hash a password using PBKDF2-HMAC-SHA256.

        Stored format:
            pbkdf2_sha256$iterations$salt$digest
        """

        if not isinstance(password, str):
            raise TypeError("Password must be a string.")

        if not password:
            raise ValueError("Password cannot be empty.")

        iterations = 310_000

        if salt is None:
            salt = secrets.token_bytes(32)

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )

        salt_b64 = base64.urlsafe_b64encode(
            salt
        ).decode("ascii")

        digest_b64 = base64.urlsafe_b64encode(
            digest
        ).decode("ascii")

        return (
            f"pbkdf2_sha256$"
            f"{iterations}$"
            f"{salt_b64}$"
            f"{digest_b64}"
        )

    @staticmethod
    def verify_password(
        password: str,
        stored_hash: str,
    ) -> bool:
        if not password or not stored_hash:
            return False

        try:
            algorithm, iterations, salt_b64, digest_b64 = (
                stored_hash.split("$", 3)
            )

            if algorithm != "pbkdf2_sha256":
                return False

            iterations_int = int(iterations)

            salt = base64.urlsafe_b64decode(
                salt_b64.encode("ascii")
            )

            expected_digest = base64.urlsafe_b64decode(
                digest_b64.encode("ascii")
            )

            actual_digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                iterations_int,
            )

            return hmac.compare_digest(
                actual_digest,
                expected_digest,
            )

        except (
            ValueError,
            TypeError,
            UnicodeError,
        ):
            return False

    # ------------------------------------------------------------------
    # Session tokens
    # ------------------------------------------------------------------

    @staticmethod
    def generate_session_token() -> str:
        """
        Generate a high-entropy opaque session identifier.
        """
        return secrets.token_urlsafe(48)

    @staticmethod
    def hash_session_token(token: str) -> str:
        """
        Hash a session token before using it as a persistent lookup key.
        """
        if not token:
            raise ValueError("Session token cannot be empty.")

        return hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

    # ------------------------------------------------------------------
    # Generic secure identifiers
    # ------------------------------------------------------------------

    @staticmethod
    def generate_secret_id() -> str:
        return secrets.token_urlsafe(24)

    @staticmethod
    def generate_event_id() -> str:
        return secrets.token_urlsafe(24)

    @staticmethod
    def generate_approval_id() -> str:
        return secrets.token_urlsafe(24)

    # ------------------------------------------------------------------
    # Secret metadata protection
    # ------------------------------------------------------------------

    @staticmethod
    def mask_secret(
        value: Optional[str],
        visible_start: int = 2,
        visible_end: int = 2,
    ) -> str:
        """
        Return a safe representation for UI/logging.

        Example:
            abcdefgh -> ab****gh
        """

        if value is None:
            return ""

        if not value:
            return ""

        if len(value) <= visible_start + visible_end:
            return "*" * len(value)

        start = value[:visible_start]
        end = value[-visible_end:]

        masked_length = max(
            4,
            len(value) - visible_start - visible_end,
        )

        return (
            f"{start}"
            f"{'*' * masked_length}"
            f"{end}"
        )

    # ------------------------------------------------------------------
    # Constant-time comparison
    # ------------------------------------------------------------------

    @staticmethod
    def secure_compare(
        first: str,
        second: str,
    ) -> bool:
        if not isinstance(first, str):
            return False

        if not isinstance(second, str):
            return False

        return hmac.compare_digest(
            first.encode("utf-8"),
            second.encode("utf-8"),
        )

    # ------------------------------------------------------------------
    # Encryption key helper
    # ------------------------------------------------------------------

    @staticmethod
    def generate_encryption_key() -> str:
        """
        Generate a valid Fernet key.

        The generated key should be placed in .env and must never
        be committed to Git.
        """
        return Fernet.generate_key().decode("utf-8")


security_manager = SecurityManager
