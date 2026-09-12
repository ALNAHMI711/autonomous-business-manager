from pathlib import Path

from app.login_auth import LoginAuthenticator
from app.ownership import OwnershipStore
from app.passwords import PasswordService
from app.user_credentials import UserCredentialStore


class FakeSettings:
    admin_password = "legacy-admin-password"


class FakeSecurity:
    settings = FakeSettings()

    def secure_compare(self, supplied: str, configured: str) -> bool:
        return supplied == configured

    def generate_session_token(self) -> str:
        return "session-token"


class FakeSessions:
    def __init__(self, credentials: UserCredentialStore):
        self.credentials = credentials
        self.issued = []

    def add(self, token: str, user_id: int = 1) -> None:
        self.issued.append((token, user_id))


def test_named_users_authenticate_to_distinct_user_ids(tmp_path: Path):
    database_path = tmp_path / "app.db"
    ownership = OwnershipStore(str(database_path))
    ownership.initialize()
    alice_id = ownership.create_user("alice")
    bob_id = ownership.create_user("bob")

    credentials = UserCredentialStore(str(database_path), PasswordService())
    credentials.initialize()
    credentials.set_password(alice_id, "alice password 123")
    credentials.set_password(bob_id, "bob password 123")

    sessions = FakeSessions(credentials)
    authenticator = LoginAuthenticator(sessions, FakeSecurity())

    alice = authenticator.authenticate("alice", "alice password 123")
    bob = authenticator.authenticate("bob", "bob password 123")

    assert alice is not None and alice.user_id == alice_id
    assert bob is not None and bob.user_id == bob_id
    assert alice.user_id != bob.user_id

    token = authenticator.issue_session(alice)
    assert token == "session-token"
    assert sessions.issued == [("session-token", alice_id)]


def test_bootstrap_admin_legacy_login_remains_available(tmp_path: Path):
    database_path = tmp_path / "app.db"
    ownership = OwnershipStore(str(database_path))
    ownership.initialize()
    credentials = UserCredentialStore(str(database_path))
    sessions = FakeSessions(credentials)
    authenticator = LoginAuthenticator(sessions, FakeSecurity())

    admin = authenticator.authenticate("admin", "legacy-admin-password")

    assert admin is not None
    assert admin.user_id == 1
    assert admin.username == "admin"


def test_invalid_named_user_is_rejected(tmp_path: Path):
    database_path = tmp_path / "app.db"
    ownership = OwnershipStore(str(database_path))
    ownership.initialize()
    credentials = UserCredentialStore(str(database_path))
    sessions = FakeSessions(credentials)
    authenticator = LoginAuthenticator(sessions, FakeSecurity())

    assert authenticator.authenticate("alice", "wrong") is None
