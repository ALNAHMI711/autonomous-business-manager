from pathlib import Path
import sqlite3

import pytest

from deploy import backup_database


def test_backup_database_creates_verified_copy(tmp_path: Path, monkeypatch):
    database = tmp_path / "business_manager.db"
    destination = tmp_path / "backups" / "snapshot.db"

    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sample(value) VALUES ('ok')")
        connection.commit()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["backup_database.py", str(destination)])

    assert backup_database.main() == 0
    assert destination.exists()

    with sqlite3.connect(destination) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT value FROM sample").fetchone() == ("ok",)


def test_backup_database_refuses_overwrite(tmp_path: Path, monkeypatch):
    database = tmp_path / "business_manager.db"
    destination = tmp_path / "snapshot.db"
    database.touch()
    destination.write_text("existing")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["backup_database.py", str(destination)])

    with pytest.raises(SystemExit, match="refusing to overwrite"):
        backup_database.main()

    assert destination.read_text() == "existing"
