"""Механизм громких fallback'ов (htqweb/fallback.py).

Стерегут ровно то, ради чего он заведён:

* в строгом режиме подмены НЕ происходит — иначе весь смысл разделения сред
  теряется, и разработчик снова видит следствие вместо причины;
* в прод-режиме, наоборот, ничего не падает: пользователю подмена не видна;
* исходное исключение не теряется ни в одном из режимов — оно и есть ответ
  на вопрос «почему подменили»;
* счётчик растёт, иначе алерт «на проде что-то подменяется» построить не на чем.

Прогон идёт в strict (settings/test.py), поэтому прод-режим включается
фикстурой `fallback_log_mode` (backend/conftest.py).
"""
from __future__ import annotations

import logging

import pytest

from htqweb.fallback import (
    FallbackNotAllowed,
    fallback,
    fallback_total,
    is_strict,
)


def _counter(site: str, expected: str = "false") -> float:
    value = fallback_total.labels(site=site, expected=expected)._value.get()
    return float(value)


# ── strict: подмены нет ────────────────────────────────────────────────────

def test_strict_mode_raises_instead_of_substituting():
    with pytest.raises(FallbackNotAllowed) as info:
        fallback("core.tests.strict", "подменённое",
                 reason="нет данных", who="тест")

    message = str(info.value)
    assert "FALLBACK site=core.tests.strict" in message
    assert "who='тест'" in message           # контекст идёт в текст как key=value
    # Сообщение обязано говорить, что делать: без этого strict выглядит как
    # непонятная поломка среды, и его первым делом выключат.
    assert "expected=True" in message


def test_strict_mode_keeps_the_original_cause():
    original = ValueError("реальная причина")
    with pytest.raises(FallbackNotAllowed) as info:
        try:
            raise original
        except ValueError as exc:
            fallback("core.tests.cause", None, reason="сбой", exc=exc)

    assert info.value.__cause__ is original


def test_expected_degradation_survives_strict_mode():
    """`expected=True` — штатная деградация, а не замаскированный сбой."""
    assert is_strict()
    assert fallback("core.tests.expected", [], reason="плана нет",
                    expected=True) == []


# ── log: пользователю ничего не видно ──────────────────────────────────────

def test_log_mode_returns_the_value(fallback_log_mode):
    assert fallback("core.tests.log", 42, reason="нет данных") == 42


def test_log_mode_writes_a_greppable_line(fallback_log_mode, caplog):
    with caplog.at_level(logging.INFO, logger="htqweb.fallback"):
        fallback("core.tests.line", None, reason="кэш пуст", app="mail")

    record = next(r for r in caplog.records if r.name == "htqweb.fallback")
    assert record.levelno == logging.WARNING
    # По подстроке FALLBACK строится Loki-правило (единственный канал для
    # Celery-воркеров, у которых нет своего /metrics) — формат тут контракт.
    assert record.getMessage().startswith("FALLBACK site=core.tests.line ")
    assert "app='mail'" in record.getMessage()


def test_expected_degradation_logs_quieter(fallback_log_mode, caplog):
    """INFO против WARNING: штатная деградация не должна шуметь наравне со
    сбоем, иначе на WARNING перестанут смотреть."""
    with caplog.at_level(logging.INFO, logger="htqweb.fallback"):
        fallback("core.tests.quiet", 0, reason="SUM вернул NULL", expected=True)

    record = next(r for r in caplog.records if r.name == "htqweb.fallback")
    assert record.levelno == logging.INFO


def test_log_mode_attaches_the_traceback(fallback_log_mode, caplog):
    """exc_info передаётся явным исключением: вызов часто происходит уже
    после выхода из except-блока, где sys.exc_info() пуст."""
    with caplog.at_level(logging.INFO, logger="htqweb.fallback"):
        try:
            raise RuntimeError("причина")
        except RuntimeError as exc:
            fallback("core.tests.trace", None, reason="сбой", exc=exc)

    record = next(r for r in caplog.records if r.name == "htqweb.fallback")
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], RuntimeError)


# ── метрика ────────────────────────────────────────────────────────────────

def test_counter_grows_in_both_modes(fallback_log_mode, settings):
    before = _counter("core.tests.counter")
    fallback("core.tests.counter", None, reason="раз")

    settings.FALLBACK_MODE = "strict"
    with pytest.raises(FallbackNotAllowed):
        fallback("core.tests.counter", None, reason="два")

    # Считаем и то, что упало: иначе на стейдже, где strict включают руками,
    # график молча обнулился бы.
    assert _counter("core.tests.counter") == before + 2


def test_expected_is_a_separate_series(fallback_log_mode):
    before = _counter("core.tests.series", expected="true")
    fallback("core.tests.series", None, reason="штатно", expected=True)
    assert _counter("core.tests.series", expected="true") == before + 1
    # Алерт смотрит только на expected="false" — смешать их значило бы
    # утопить настоящие сбои в фоне штатных деградаций.
    assert _counter("core.tests.series", expected="false") == 0


# ── режим выводится из среды ───────────────────────────────────────────────

@pytest.mark.parametrize("environment,expected_mode", [
    ("production", "log"),
    ("staging", "log"),
    ("development", "strict"),
])
def test_mode_follows_the_environment(environment, expected_mode, monkeypatch):
    from htqweb.settings.base import fallback_mode_for

    monkeypatch.delenv("FALLBACK_MODE", raising=False)
    assert fallback_mode_for(environment) == expected_mode


def test_explicit_mode_overrides_the_environment(monkeypatch):
    """Строгий режим на стейдже включается переменной, без пересборки среды."""
    from htqweb.settings.base import fallback_mode_for

    monkeypatch.setenv("FALLBACK_MODE", "strict")
    assert fallback_mode_for("production") == "strict"
