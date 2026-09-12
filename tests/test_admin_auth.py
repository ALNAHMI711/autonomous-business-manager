import pytest

from app.admin_auth import AdminPasswordVerifier
from app.passwords import PasswordService


def test_argon2id_admin_hash_verifies():
    password = "strong-admin-password"
    password_hash = PasswordService().hash(password)
    verifier = AdminPasswordVerifier(
        password_hash=password_hash,
        legacy_password="",
        production=True,
    )

    assert verifier.configured
    assert verifier.verify(password)
    assert not verifier.verify("wrong")
    assert not verifier.using_legacy_password


def test_production_rejects_legacy_plaintext():
    verifier = AdminPasswordVerifier(
        password_hash="",
        legacy_password="legacy",
        production=True,
    )

    assert not verifier.configured
    assert not verifier.verify("legacy")


def test_development_legacy_fallback_is_explicit():
    verifier = AdminPasswordVerifier(
        password_hash="",
        legacy_password="legacy",
        production=False,
    )

    assert verifier.configured
    assert verifier.using_legacy_password
    assert verifier.verify("legacy")
    assert not verifier.verify("wrong")


def test_empty_password_hash_is_not_accepted():
    verifier = AdminPasswordVerifier(
        password_hash="",
        legacy_password="",
        production=False,
    )
    assert not verifier.configured
    assert not verifier.verify("anything")
