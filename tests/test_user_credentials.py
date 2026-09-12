from pathlib import Path

import pytest

from app.ownership import OwnershipStore
from app.passwords import PasswordService
from app.user_credentials import UserCredentialStore


def test_user_credentials_are_argon2id_and_authenticate(tmp_path: Path):
    database_path = tmp_path / "app.db"
    ownership = OwnershipStore(str(database_path))
    ownership.initialize()
    user_id = ownership.create_user("operator")

    credentials = UserCredentialStore(str(database_path), PasswordService())
    credentials.initialize()
    credentials.set_password(user_id, "correct horse battery")

    assert credentials.authenticate("operator", "correct horse battery") == user_id
    assert credentials.authenticate("operator", "wrong password") is None
    assert credentials.authenticate("missing", "correct horse battery") is None

    with credentials._connect() as connection:
        stored = connection.execute(
            "SELECT password_hash FROM user_credentials WHERE user_id = ?",
            (user_id,),
        ).fetchone()["password_hash"]
    assert stored.startswith("$argon2id$")
    assert "correct horse battery" not in stored


def test_user_credentials_require_strong_minimum_password(tmp_path: Path):
    database_path = tmp_path / "app.db"
    ownership = OwnershipStore(str(database_path))
    ownership.initialize()
    user_id = ownership.create_user("operator")

    credentials = UserCredentialStore(str(database_path))
    credentials.initialize()

    with pytest.raises(ValueError):
        credentials.set_password(user_id, "short")
