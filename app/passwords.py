from __future__ import annotations

from typing import Optional

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
except ImportError:  # pragma: no cover
    PasswordHasher = None  # type: ignore[assignment]
    InvalidHashError = VerificationError = VerifyMismatchError = Exception


class PasswordService:
    """Argon2id password hashing and verification."""

    def __init__(self) -> None:
        if PasswordHasher is None:
            raise RuntimeError("argon2-cffi is required for password hashing")
        self._hasher = PasswordHasher()

    def hash(self, password: str) -> str:
        if not password:
            raise ValueError("password must not be empty")
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        if not password or not password_hash:
            return False
        try:
            return bool(self._hasher.verify(password_hash, password))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: Optional[str]) -> bool:
        if not password_hash:
            return True
        try:
            return bool(self._hasher.check_needs_rehash(password_hash))
        except (VerificationError, InvalidHashError):
            return True
