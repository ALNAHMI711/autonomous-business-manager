import sqlite3
from pathlib import Path

from deploy import restore_drill, verify_deployment


def _make_db(path: Path, rows: int = 3) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE a (id INTEGER PRIMARY KEY, v TEXT)")
        connection.execute("CREATE TABLE b (id INTEGER PRIMARY KEY)")
        connection.executemany("INSERT INTO a(v) VALUES (?)", [(str(i),) for i in range(rows)])
        connection.commit()


def test_restore_drill_passes_on_healthy_database(tmp_path, capsys):
    database = tmp_path / "live.db"
    _make_db(database)
    assert restore_drill.main(["--db", str(database)]) == 0
    assert "PASS" in capsys.readouterr().out
    # the live database is untouched
    assert restore_drill.table_counts(database) == {"a": 3, "b": 0}


def test_restore_drill_fails_when_database_is_missing(tmp_path, capsys):
    assert restore_drill.main(["--db", str(tmp_path / "nope.db")]) == 1
    assert "database not found" in capsys.readouterr().err


def test_evaluate_headers_flags_missing_and_weak_hsts():
    good = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'self'",
        "Referrer-Policy": "no-referrer",
    }
    assert verify_deployment.evaluate_headers(good) == []
    weak = dict(good, **{"Strict-Transport-Security": "max-age=60"})
    assert any("HSTS" in p for p in verify_deployment.evaluate_headers(weak))
    missing = {k: v for k, v in good.items() if k != "X-Frame-Options"}
    assert "missing header: x-frame-options" in verify_deployment.evaluate_headers(missing)


def test_evaluate_cookie_requires_secure_httponly_samesite():
    ok = "session=abc; HttpOnly; Max-Age=86400; Path=/; SameSite=lax; Secure"
    assert verify_deployment.evaluate_cookie(ok) == []
    bad = "session=abc; Path=/"
    assert len(verify_deployment.evaluate_cookie(bad)) == 3


def test_verify_deployment_rejects_non_https_target():
    assert verify_deployment.run("http://example.com", None) == ["base URL must be https://<domain>"]
