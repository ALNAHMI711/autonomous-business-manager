from pathlib import Path
import sqlite3

import pytest

from deploy import restore_database


def _create_backup(root: Path) -> Path:
    backup = root / "backup.db"
    with sqlite3.connect(backup) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sample(value) VALUES ('restored')")
        connection.commit()
    return backup


def test_restore_database_creates_verified_copy(tmp_path: Path, monkeypatch):
    source = _create_backup(tmp_path)
    destination = tmp_path / "data" / "business_manager.db"

    monkeypatch.setattr(
        "sys.argv",
        ["restore_database.py", str(source), str(destination)],
    )

    assert restore_database.main() == 0
    assert destination.exists()

    with sqlite3.connect(destination) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT value FROM sample").fetchone() == ("restored",)


def test_restore_database_refuses_overwrite_without_force(tmp_path: Path, monkeypatch):
    source = _create_backup(tmp_path)
    destination = tmp_path / "existing.db"
    destination.write_text("keep-me")

    monkeypatch.setattr(
        "sys.argv",
        ["restore_database.py", str(source), str(destination)],
    )

    with pytest.raises(SystemExit, match="refusing to overwrite"):
        restore_database.main()

    assert destination.read_text() == "keep-me"


def test_restore_database_force_replaces_existing_file(tmp_path: Path, monkeypatch):
    source = _create_backup(tmp_path)
    destination = tmp_path / "existing.db"
    destination.write_text("old")

    monkeypatch.setattr(
        "sys.argv",
        ["restore_database.py", str(source), str(destination), "--force"],
    )

    assert restore_database.main() == 0

    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("restored",)
