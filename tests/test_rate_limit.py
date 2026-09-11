from pathlib import Path

from app.rate_limit import LoginRateLimiter


def test_failed_logins_lock_and_success_clears(tmp_path: Path):
    limiter = LoginRateLimiter(tmp_path / "security.db", max_failures=3, window_seconds=60)
    assert limiter.check("198.51.100.10", now=100)[0]
    assert limiter.record_failure("198.51.100.10", now=100) == (True, 2)
    assert limiter.record_failure("198.51.100.10", now=101) == (True, 1)
    allowed, retry_after = limiter.record_failure("198.51.100.10", now=102)
    assert allowed is False
    assert retry_after == 60
    allowed, _ = limiter.check("198.51.100.10", now=120)
    assert allowed is False
    limiter.record_success("198.51.100.10")
    assert limiter.check("198.51.100.10", now=120)[0] is True


def test_window_expires_and_state_is_durable(tmp_path: Path):
    db = tmp_path / "security.db"
    first = LoginRateLimiter(db, max_failures=2, window_seconds=30)
    first.record_failure("203.0.113.7", now=100)
    second = LoginRateLimiter(db, max_failures=2, window_seconds=30)
    assert second.check("203.0.113.7", now=101) == (True, 1)
    assert second.record_failure("203.0.113.7", now=102) == (False, 30)
    assert second.check("203.0.113.7", now=131)[0] is True


def test_clients_are_isolated(tmp_path: Path):
    limiter = LoginRateLimiter(tmp_path / "security.db", max_failures=2, window_seconds=60)
    limiter.record_failure("10.0.0.1", now=1)
    limiter.record_failure("10.0.0.1", now=2)
    assert limiter.check("10.0.0.1", now=2)[0] is False
    assert limiter.check("10.0.0.2", now=2)[0] is True
