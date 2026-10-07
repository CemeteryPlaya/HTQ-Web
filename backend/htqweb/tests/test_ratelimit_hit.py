"""Общий лимитер запросов — ``htqweb.ratelimit.hit`` (тендерный портал, T3.1;
план этапа 3, §1 «Лимиты»).

Окно фиксированное и выровнено по часам (``time // window``): номер окна —
часть ключа, поэтому ``retry_after`` считается без чтения TTL из кэша.
"""
import time

import pytest
from django.core.cache import cache

from htqweb import ratelimit
from htqweb.fallback import FallbackNotAllowed

TOKEN = "Zr1yQ7m0-very-secret-token-value-from-the-link"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def clock(monkeypatch):
    """Закреплённое время у начала минутного окна; LocMemCache и модуль
    читают один ``time.time``."""
    state = {"now": 1_800_000_000.0}
    monkeypatch.setattr(time, "time", lambda: state["now"])
    return state


def test_within_the_limit_then_over(clock):
    for _ in range(3):
        assert ratelimit.hit("portal_token", TOKEN, limit=3, window=60) is True
    assert ratelimit.hit("portal_token", TOKEN, limit=3, window=60) is False
    assert ratelimit.hit("portal_token", TOKEN, limit=3, window=60) is False


def test_buckets_and_keys_are_separate(clock):
    assert ratelimit.hit("portal_token", TOKEN, limit=1, window=60)
    assert not ratelimit.hit("portal_token", TOKEN, limit=1, window=60)
    assert ratelimit.hit("portal_ip", TOKEN, limit=1, window=60)
    assert ratelimit.hit("portal_token", TOKEN + "x", limit=1, window=60)


def test_next_window_starts_from_zero(clock):
    assert ratelimit.hit("b", "k", limit=1, window=60)
    assert not ratelimit.hit("b", "k", limit=1, window=60)
    clock["now"] += 60
    assert ratelimit.hit("b", "k", limit=1, window=60)


def test_retry_after_counts_to_the_end_of_the_window(clock):
    clock["now"] = 1_800_000_000.0 - (1_800_000_000 % 60) + 15   # 15 с от начала окна
    assert ratelimit.retry_after("b", "k", 60) == 45
    clock["now"] += 44.5
    assert ratelimit.retry_after("b", "k", 60) == 1


def test_key_does_not_keep_the_raw_value(clock):
    ratelimit.hit("portal_token", TOKEN, limit=5, window=60)
    keys = list(cache._cache.keys())  # LocMemCache: ключи с префиксом версии
    assert keys and all(TOKEN not in key for key in keys)
    assert any("ratelimit:portal_token:" in key for key in keys)


class _DeadCache:
    """Кэш с IGNORE_EXCEPTIONS при недоступном Redis: всё отдаёт None."""

    def __getattr__(self, name):
        return lambda *a, **kw: None


@pytest.fixture
def dead_store(monkeypatch):
    monkeypatch.setattr(ratelimit, "cache", _DeadCache())


def test_dead_store_fails_open_with_fallback(dead_store, fallback_log_mode, caplog):
    with caplog.at_level("WARNING", logger="htqweb.fallback"):
        assert ratelimit.hit("portal_ip", "10.0.0.1", limit=1, window=60) is True
        assert ratelimit.hit("portal_ip", "10.0.0.1", limit=1, window=60) is True
    assert "FALLBACK site=htqweb.ratelimit.store_unavailable" in caplog.text


def test_dead_store_fails_closed_when_asked(dead_store):
    """OTP (этап 4): недоступный счётчик — отказ, а не пропуск; без подмены."""
    assert ratelimit.hit("otp", "inv", limit=5, window=600, fail_closed=True) is False


def test_dead_store_in_strict_mode_raises(dead_store):
    with pytest.raises(FallbackNotAllowed):
        ratelimit.hit("portal_ip", "10.0.0.1", limit=1, window=60)


@pytest.mark.parametrize("limit,window", [(0, 60), (1, 0), (-1, 60)])
def test_bad_parameters_are_refused(limit, window):
    with pytest.raises(ValueError):
        ratelimit.hit("b", "k", limit=limit, window=window)
