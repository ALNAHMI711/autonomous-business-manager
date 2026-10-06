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

    with sqlite3.connect(path) as db:
        db.execute("UPDATE projects SET owner_id = ? WHERE id = 2", (user2,))

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


def test_delete_user_revokes_durable_sessions(tmp_path):
    import sqlite3

    path = tmp_path / "app.db"
    store = OwnershipStore(str(path))
    store.initialize()
    user2 = store.create_user("user2")

    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            )
            """
        )
        db.execute(
            """
            INSERT INTO auth_sessions(token_hash, user_id, created_at, expires_at)
            VALUES ('session-user2', ?, '2026-01-01', '2099-01-01')
            """,
            (user2,),
        )

    assert store.delete_user(user2) is True
    assert store.get_user(user2) is None

    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT 1 FROM auth_sessions WHERE user_id = ?",
            (user2,),
        ).fetchone() is None


def test_delete_user_cannot_remove_bootstrap_admin(tmp_path):
    store = OwnershipStore(str(tmp_path / "app.db"))
    store.initialize()

    assert store.delete_user(OwnershipStore.BOOTSTRAP_USER_ID) is False
    assert store.get_user(OwnershipStore.BOOTSTRAP_USER_ID) is not None
