import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.passwords import PasswordService


def _production_security_kwargs():
    return {
        "csrf_secret": "c" * 32,
        "encryption_key": Fernet.generate_key().decode("ascii"),
        "session_secret": "s" * 32,
    }


def test_production_requires_argon2_admin_password_hash():
    with pytest.raises(ValueError, match="ADMIN_PASSWORD_HASH"):
        Settings(
            app_env="production",
            admin_password_hash="",
            admin_password="legacy",
            **_production_security_kwargs(),
        )


def test_production_maps_argon2_hash_to_legacy_login_setting():
    password_hash = PasswordService().hash("strong-admin-password")
    settings = Settings(
        app_env="production",
        admin_password_hash=password_hash,
        **_production_security_kwargs(),
    )

    assert settings.admin_password == password_hash


def test_development_can_use_legacy_password_during_migration():
    settings = Settings(app_env="development", admin_password="legacy")

    assert settings.admin_password == "legacy"
