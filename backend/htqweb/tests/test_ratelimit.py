"""Блокировка входа — ``htqweb/ratelimit.py`` (D-S7-3)."""
import time

import pytest
from django.core.cache import cache

from htqweb import ratelimit
from htqweb.fallback import FallbackNotAllowed


@pytest.fixture
def lockout(settings):
    settings.AUTH_LOCKOUT_THRESHOLD = 5
    settings.AUTH_LOCKOUT_SECONDS = 900
    return settings


@pytest.fixture
def clock(monkeypatch):
    """Закреплённое время; LocMemCache и модуль читают один ``time.time``."""
    state = {"now": 1_800_000_000.0}
    monkeypatch.setattr(time, "time", lambda: state["now"])
    return state


def _fail(login, n):
    for _ in range(n):
        ratelimit.register_login_failure(login)


def test_five_failures_lock_for_the_window(lockout, clock):
    _fail("alice", 4)
    assert ratelimit.login_locked("alice") is None
    _fail("alice", 1)
    assert ratelimit.login_locked("alice") == 900


def test_lock_expires_after_window(lockout, clock):
    _fail("alice", 5)
    clock["now"] += 899
    assert ratelimit.login_locked("alice") == 1
    clock["now"] += 2
    assert ratelimit.login_locked("alice") is None


def test_failures_outside_window_do_not_add_up(lockout, clock):
    _fail("alice", 4)
    clock["now"] += 901
    _fail("alice", 4)
    assert ratelimit.login_locked("alice") is None


def test_username_is_case_sensitive_email_is_not(lockout, clock):
    _fail("Admin", 5)
    assert ratelimit.login_locked("Admin") == 900
    assert ratelimit.login_locked("admin") is None
    _fail("Bob@HTQ.test", 5)
    assert ratelimit.login_locked("  bob@htq.TEST ") == 900


def test_reset_clears_counter_and_lock(lockout, clock):
    _fail("alice", 5)
    ratelimit.reset_login("alice")
    assert ratelimit.login_locked("alice") is None
    _fail("alice", 4)
    assert ratelimit.login_locked("alice") is None


def test_threshold_zero_disables(settings, clock):
    settings.AUTH_LOCKOUT_THRESHOLD = 0
    _fail("alice", 50)
    assert ratelimit.login_locked("alice") is None
    assert cache.get(f"ratelimit:login:{ratelimit.login_digest('alice')}:n") is None


def test_key_holds_no_login_and_is_bounded(lockout, clock):
    _fail("alice", 5)
    assert "alice" not in ratelimit.login_digest("alice")
    assert len(ratelimit.login_digest("x" * 1000)) == 64
    assert ratelimit.login_digest("a" * 300) == ratelimit.login_digest("a" * 254)


def test_expired_key_between_add_and_incr_restarts_window(monkeypatch):
    """``add`` отказал (ключ был), а к ``incr`` он истёк — окно заводится заново."""
    sequence = iter([False, True])
    monkeypatch.setattr(cache, "add", lambda *a, **kw: next(sequence))

    def gone(*a, **kw):
        raise ValueError("Key not found")

    monkeypatch.setattr(cache, "incr", gone)
    assert ratelimit._incr("k", 60) == 1


class _DeadCache:
    """Кэш с IGNORE_EXCEPTIONS при недоступном Redis: всё отдаёт None."""

    def __getattr__(self, name):
        return lambda *a, **kw: None


def test_dead_store_fails_open_with_fallback(lockout, monkeypatch, fallback_log_mode, caplog):
    monkeypatch.setattr(ratelimit, "cache", _DeadCache())
    with caplog.at_level("WARNING", logger="htqweb.fallback"):
        _fail("alice", 10)
    assert ratelimit.login_locked("alice") is None
    assert "FALLBACK site=htqweb.ratelimit.store_unavailable" in caplog.text


def test_dead_store_in_strict_mode_raises(lockout, monkeypatch):
    monkeypatch.setattr(ratelimit, "cache", _DeadCache())
    with pytest.raises(FallbackNotAllowed):
        ratelimit.register_login_failure("alice")
