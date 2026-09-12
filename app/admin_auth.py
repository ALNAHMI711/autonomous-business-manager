from __future__ import annotations

from app.passwords import PasswordService


class AdminPasswordVerifier:
    """Verify the admin password with Argon2id, with a development-only legacy fallback."""

    def __init__(self, *, password_hash: str, legacy_password: str, production: bool) -> None:
        self.password_hash = password_hash.strip()
        self.legacy_password = legacy_password
        self.production = production
        self.passwords = PasswordService()

    def verify(self, password: str) -> bool:
        if self.password_hash:
            return self.passwords.verify(password, self.password_hash)

        # Never permit plaintext admin credentials as the production mechanism.
        if self.production:
            return False

        if not self.legacy_password:
            return False

        return password == self.legacy_password

    @property
    def configured(self) -> bool:
        return bool(self.password_hash or (self.legacy_password and not self.production))

    @property
    def using_legacy_password(self) -> bool:
        return bool(not self.password_hash and self.legacy_password and not self.production)
