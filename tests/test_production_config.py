import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings


def production_settings(**overrides):
    values = {
        "app_env": "production",
        "admin_password_hash": "$argon2id$v=19$m=65536,t=3,p=4$placeholder",
        "csrf_secret": "c" * 32,
        "encryption_key": Fernet.generate_key().decode("utf-8"),
        "session_secret": "s" * 48,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_accepts_complete_security_configuration():
    settings = production_settings()
    assert settings.app_env == "production"


@pytest.mark.parametrize(
    "field,value",
    [
        ("admin_password_hash", ""),
        ("csrf_secret", "short"),
        ("encryption_key", ""),
        ("encryption_key", "not-a-fernet-key"),
        ("session_secret", "change-this-session-secret"),
    ],
)
def test_production_rejects_insecure_security_configuration(field, value):
    with pytest.raises(ValidationError):
        production_settings(**{field: value})


def test_development_keeps_bootstrap_defaults_available():
    settings = Settings(app_env="development")
    assert settings.app_env == "development"
