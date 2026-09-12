from app.ownership import OwnershipStore


def test_legacy_projects_are_migrated_to_bootstrap_owner(tmp_path):
    import sqlite3

    path = tmp_path / "app.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        db.execute("INSERT INTO projects(id, name, created_at) VALUES (7, 'legacy', '2026-01-01')")

    store = OwnershipStore(str(path))
    store.initialize()

    assert store.project_owner(7) == 1
    assert store.user_can_access_project(1, 7)
    assert not store.user_can_access_project(2, 7)


def test_two_users_cannot_cross_access_projects(tmp_path):
    import sqlite3

    path = tmp_path / "app.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        db.execute("INSERT INTO projects(id, name, created_at) VALUES (1, 'a', '2026-01-01')")
        db.execute("INSERT INTO projects(id, name, created_at) VALUES (2, 'b', '2026-01-01')")

    store = OwnershipStore(str(path))
    store.initialize()
    user2 = store.create_user("user2")
    store.assign_project(2, user2)

    assert store.user_can_access_project(1, 1)
    assert not store.user_can_access_project(1, 2)
    assert store.user_can_access_project(user2, 2)
    assert not store.user_can_access_project(user2, 1)
    assert store.list_project_ids(1) == [1]
    assert store.list_project_ids(user2) == [2]


def test_assign_project_rejects_unknown_owner(tmp_path):
    store = OwnershipStore(str(tmp_path / "app.db"))
    store.initialize()
    try:
        store.assign_project(999, 123)
    except ValueError as exc:
        assert "owner user" in str(exc)
    else:
        raise AssertionError("unknown owner must be rejected")


def test_assign_project_cannot_take_over_existing_project(tmp_path):
    import sqlite3

    path = tmp_path / "app.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        db.execute("INSERT INTO projects(id, name, created_at) VALUES (1, 'owned', '2026-01-01')")

    store = OwnershipStore(str(path))
    store.initialize()
    user2 = store.create_user("user2")

    assert store.project_owner(1) == 1
    assert store.assign_project(1, user2) is False
    assert store.project_owner(1) == 1
    assert store.user_can_access_project(1, 1)
    assert not store.user_can_access_project(user2, 1)
