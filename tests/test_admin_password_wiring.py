from app import main
from app.passwords import PasswordService


def test_secret_panel_admin_password_accepts_argon2id_hash(monkeypatch):
    password = "correct-admin-password"
    password_hash = PasswordService().hash(password)

    verifier = main.AdminPasswordVerifier(
        password_hash=password_hash,
        legacy_password="",
        production=True,
    )
    monkeypatch.setattr(main, "_admin_password_verifier", verifier)

    assert main._verify_admin_password(password) is True
    assert main._verify_admin_password("wrong-password") is False
