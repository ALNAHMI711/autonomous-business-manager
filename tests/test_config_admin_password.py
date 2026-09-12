import pytest

from app.config import Settings
from app.passwords import PasswordService


def test_production_requires_argon2_admin_password_hash():
    with pytest.raises(ValueError, match="ADMIN_PASSWORD_HASH"):
        Settings(app_env="production", admin_password_hash="", admin_password="legacy")


def test_production_maps_argon2_hash_to_legacy_login_setting():
    password_hash = PasswordService().hash("strong-admin-password")
    settings = Settings(app_env="production", admin_password_hash=password_hash)

    assert settings.admin_password == password_hash


def test_development_can_use_legacy_password_during_migration():
    settings = Settings(app_env="development", admin_password="legacy")

    assert settings.admin_password == "legacy"
