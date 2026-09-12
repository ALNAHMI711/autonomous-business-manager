from app.auth_store import AuthStore
from app.security import hash_session_token
from app.session_identity import SessionIdentity


def test_session_identity_resolves_user_id(tmp_path):
    path = tmp_path / "app.db"
    store = AuthStore(str(path))
    store.create(hash_session_token("token-a"), user_id=42)
    identity = SessionIdentity(str(path))
    assert identity.user_id_from_token("token-a") == 42


def test_session_identity_rejects_unknown_or_expired_session(tmp_path):
    identity = SessionIdentity(str(tmp_path / "app.db"))
    assert identity.user_id_from_token("missing") is None
