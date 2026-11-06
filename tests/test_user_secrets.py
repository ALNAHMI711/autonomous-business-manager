import sqlite3

import pytest

from app.database import Database
from app.network import NetworkManager, NetworkProfile
from app.user_secrets import UserSecretStore


class FakeSecurity:
    def encrypt(self, value):
        return "enc:" + value

    def decrypt(self, value):
        return value[4:]


@pytest.fixture
def env(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.initialize()
    return db, UserSecretStore(db, FakeSecurity())


def test_secrets_are_isolated_per_user(env):
    _, store = env
    store.set(2, "api-key", "two-secret")
    store.set(3, "api-key", "three-secret")
    assert store.reveal(2, "api-key") == "two-secret"
    assert store.reveal(3, "api-key") == "three-secret"
    assert [s["name"] for s in store.list(2)] == ["api-key"]
    assert store.list(4) == []
    assert store.reveal(4, "api-key") is None


def test_user_cannot_delete_or_overwrite_foreign_secret(env):
    _, store = env
    store.set(2, "k", "v2")
    assert store.delete(3, "k") is False
    store.set(3, "k", "v3")
    assert store.reveal(2, "k") == "v2"
    assert store.delete(2, "k") is True
    assert store.reveal(3, "k") == "v3"


def test_listing_never_exposes_values_or_ciphertext(env):
    _, store = env
    store.set(2, "k", "super-secret", "desc")
    dumped = repr(store.list(2))
    assert "super-secret" not in dumped and "enc:" not in dumped


@pytest.mark.parametrize("name", ["", "../x", "a b", "u2:k", "x" * 81, ":"])
def test_invalid_names_rejected(env, name):
    _, store = env
    with pytest.raises(ValueError):
        store.set(2, name, "v")


def test_name_cannot_spoof_other_user_namespace(env):
    _, store = env
    store.set(3, "k", "victim")
    with pytest.raises(ValueError):
        store.set(2, "user_secret:u3:k", "x")
    assert store.reveal(3, "k") == "victim"


def test_owner_id_persisted_and_listing_filter(env):
    db, store = env
    store.set(2, "k", "v")
    store.set(3, "k", "v")
    assert {s["owner_id"] for s in db.list_secrets(owner_id=2)} == {2}
    assert len(db.list_secrets()) == 2


def test_migration_backfills_owner_for_legacy_secrets(tmp_path):
    path = str(tmp_path / "legacy.db")
    with sqlite3.connect(path) as c:
        c.execute(
            "CREATE TABLE secrets (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, "
            "encrypted_value TEXT NOT NULL, description TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        for n in ("network_profile:admin-p", "network_profile:u7:mine", "network_binding:5"):
            c.execute("INSERT INTO secrets(name,encrypted_value,created_at,updated_at) VALUES (?, 'x','t','t')", (n,))
    db = Database(path)
    db.initialize()
    db.initialize()  # idempotent
    owners = {s["name"]: s["owner_id"] for s in db.list_secrets()}
    assert owners == {"network_profile:admin-p": 1, "network_profile:u7:mine": 7, "network_binding:5": None}


def test_network_profiles_record_owner(env):
    db, _ = env
    mgr = NetworkManager(db, FakeSecurity())
    mgr.save_profile(NetworkProfile(name="p"), owner_id=5)
    assert db.get_secret_by_name("network_profile:u5:p")["owner_id"] == 5
