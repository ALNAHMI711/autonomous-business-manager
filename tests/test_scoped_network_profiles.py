import sqlite3

import pytest
from fastapi import HTTPException

from app import main
from app.database import Database
from app.network import NetworkManager, NetworkProfile
from app.ownership import OwnershipStore


class FakeSecurity:
    def encrypt(self, value: str) -> str:
        return "enc:" + value

    def decrypt(self, value: str) -> str:
        assert value.startswith("enc:")
        return value[4:]


def proxy(name: str, password: str = "pw") -> NetworkProfile:
    return NetworkProfile(
        name=name,
        mode="proxy",
        proxy_server="http://proxy.local:8080",
        username="u",
        password=password,
    )


@pytest.fixture
def env(tmp_path):
    path = str(tmp_path / "test.db")
    database = Database(path)
    database.initialize()
    ownership = OwnershipStore(path)
    ownership.initialize()
    user2 = ownership.create_user("user2")
    user3 = ownership.create_user("user3")
    with sqlite3.connect(path) as connection:
        for name, owner in (("admin-project", 1), ("user2-project", user2), ("user3-project", user3)):
            connection.execute(
                "INSERT INTO projects(name, description, status, workflow_type, created_at, updated_at, owner_id) "
                "VALUES (?, '', 'active', 'assistant', datetime('now'), datetime('now'), ?)",
                (name, owner),
            )
        connection.commit()
    manager = NetworkManager(database, FakeSecurity())
    return manager, user2, user3


def test_user_profiles_are_invisible_to_other_users_and_admin_listing(env):
    manager, user2, user3 = env
    manager.save_profile(proxy("shared-name"), owner_id=1)
    manager.save_profile(proxy("shared-name", "other"), owner_id=user2)

    assert [p["name"] for p in manager.list_profiles(owner_id=1)] == ["shared-name"]
    assert [p["name"] for p in manager.list_profiles(owner_id=user2)] == ["shared-name"]
    assert manager.list_profiles(owner_id=user3) == []

    assert manager.get_profile("shared-name", owner_id=user3) is None
    assert manager.get_profile("shared-name", owner_id=user2).password == "other"
    assert manager.get_profile("shared-name", owner_id=1).password == "pw"


def test_user_cannot_delete_another_users_profile(env):
    manager, user2, user3 = env
    manager.save_profile(proxy("mine"), owner_id=user2)
    assert manager.delete_profile("mine", owner_id=user3) is False
    assert manager.get_profile("mine", owner_id=user2) is not None
    assert manager.delete_profile("mine", owner_id=user2) is True


def test_profile_name_cannot_spoof_another_namespace(env):
    manager, user2, _ = env
    with pytest.raises(ValueError):
        manager.save_profile(proxy("u2:admin-proxy"), owner_id=1)
    with pytest.raises(ValueError):
        NetworkProfile(name=f"u{user2}:x").validate()


def test_project_can_only_bind_its_owners_profiles(env):
    manager, user2, user3 = env
    manager.save_profile(proxy("admin-proxy"), owner_id=1)
    manager.save_profile(proxy("user2-proxy"), owner_id=user2)

    # projects: 1 = admin, 2 = user2, 3 = user3
    with pytest.raises(ValueError):
        manager.bind_project(2, "admin-proxy")  # user2 cannot borrow admin proxy
    with pytest.raises(ValueError):
        manager.bind_project(3, "user2-proxy")  # user3 cannot borrow user2 proxy

    manager.bind_project(2, "user2-proxy")
    assert manager.get_project_profile(2).name == "user2-proxy"
    manager.bind_project(1, "admin-proxy")
    assert manager.get_project_profile(1).name == "admin-proxy"


def test_get_profile_for_project_uses_project_owner_namespace(env):
    manager, user2, _ = env
    manager.save_profile(proxy("admin-proxy"), owner_id=1)
    assert manager.get_profile_for_project("admin-proxy", 2) is None
    assert manager.get_profile_for_project("admin-proxy", 1) is not None
    assert manager.get_profile_for_project("admin-proxy", 999) is None


def test_my_profile_routes_require_a_user_not_admin():
    names = {}
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/network/my-profiles"):
            names[(path, tuple(sorted(route.methods)))] = {
                getattr(d.call, "__name__", "") for d in route.dependant.dependencies
            }
    assert names, "per-user profile routes are missing"
    for deps in names.values():
        assert "_require_user_id" in deps
        assert "_require_admin_session" not in deps


@pytest.mark.asyncio
async def test_my_profile_handlers_are_scoped_to_the_caller(env, monkeypatch):
    manager, user2, user3 = env
    monkeypatch.setattr(main, "network_manager", manager)

    request = main.NetworkProfileRequest(
        name="mine", mode="proxy", proxy_server="http://proxy.local:8080", username="u", password="secret",
    )
    created = await main.create_my_network_profile(request, user_id=user2)
    assert created["success"] is True
    assert "secret" not in str(created)

    listed = await main.my_network_profiles(user_id=user2)
    assert [p["name"] for p in listed["profiles"]] == ["mine"]
    assert "secret" not in str(listed)
    assert (await main.my_network_profiles(user_id=user3))["profiles"] == []

    with pytest.raises(HTTPException) as exc:
        await main.delete_my_network_profile("mine", user_id=user3)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_bind_route_rejects_foreign_profile(env, monkeypatch):
    manager, user2, _ = env
    monkeypatch.setattr(main, "network_manager", manager)
    manager.save_profile(proxy("admin-proxy"), owner_id=1)

    with pytest.raises(HTTPException) as exc:
        await main.bind_project_network_profile(
            2, main.ProjectNetworkBindingRequest(profile_name="admin-proxy"), user2
        )
    assert exc.value.status_code == 400
