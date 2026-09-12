import pytest

from app.passwords import PasswordService


def test_argon2id_hash_verifies_and_is_salted():
    service = PasswordService()
    first = service.hash("correct horse battery staple")
    second = service.hash("correct horse battery staple")

    assert first.startswith("$argon2id$")
    assert first != second
    assert service.verify("correct horse battery staple", first)
    assert not service.verify("wrong", first)


def test_empty_password_is_rejected():
    service = PasswordService()
    with pytest.raises(ValueError):
        service.hash("")


def test_invalid_hash_fails_closed():
    service = PasswordService()
    assert not service.verify("password", "not-a-password-hash")
    assert service.needs_rehash("not-a-password-hash")
