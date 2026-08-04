"""Нормализация почтового домена из env.

Значение подставляется прямо в адрес (``f"{local}@{domain}"``), поэтому
опечатка в ``.env`` не выдаёт ошибку, а молча создаёт ящики с невозможными
адресами — и обнаруживается уже на почтовом сервере. Эти тесты фиксируют
лечение типовых опечаток; каждый случай здесь встречался вживую.
"""
from __future__ import annotations

import pytest

from htqweb.settings.base import _mail_domain


@pytest.fixture(autouse=True)
def _quiet_warnings(caplog):
    """Нормализация пишет предупреждение — оно проверяется отдельно."""
    caplog.set_level("ERROR", logger="htqweb.settings.base")


@pytest.mark.parametrize("raw,expected", [
    # Канонический вид проходит насквозь.
    ("htq.group", "htq.group"),
    # Ведущая @ — самая частая опечатка: дала бы i.ivanov@@htq.group.
    ("@htq.group", "htq.group"),
    # Пробел после `=` в .env: Docker Compose его НЕ срезает.
    (" htq.group", "htq.group"),
    ("  htq.group  ", "htq.group"),
    # URL панели вместо домена (перепутано с MAILCOW_API_URL).
    ("https://mail.htq.group/", "mail.htq.group"),
    ("http://mail.htq.group", "mail.htq.group"),
    ("https://mail.htq.group/api/v1", "mail.htq.group"),
    # Адрес целиком вместо домена.
    ("i.ivanov@htq.group", "htq.group"),
    # Регистр и завершающая точка (FQDN-запись).
    ("HTQ.Group", "htq.group"),
    ("htq.group.", "htq.group"),
    # Пусто остаётся пустым — это валидное «почта не настроена».
    ("", ""),
    ("   ", ""),
])
def test_domain_is_normalized(monkeypatch, raw, expected):
    monkeypatch.setenv("TEST_MAIL_DOMAIN", raw)
    assert _mail_domain("TEST_MAIL_DOMAIN") == expected


def test_unset_variable_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("TEST_MAIL_DOMAIN", raising=False)
    assert _mail_domain("TEST_MAIL_DOMAIN", "htq.group") == "htq.group"


def test_normalization_is_reported_not_silent(monkeypatch, caplog):
    """Молча подставить домен, которого админ не имел в виду, — худший из
    исходов: ящики создадутся, но не там. Предупреждение обязано быть."""
    monkeypatch.setenv("TEST_MAIL_DOMAIN", "https://mail.htq.group/")
    with caplog.at_level("WARNING", logger="htqweb.settings.base"):
        _mail_domain("TEST_MAIL_DOMAIN")
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "MAILCOW_API_URL" in messages
    assert "URL" in messages


def test_clean_value_produces_no_warning(monkeypatch, caplog):
    monkeypatch.setenv("TEST_MAIL_DOMAIN", "htq.group")
    with caplog.at_level("WARNING", logger="htqweb.settings.base"):
        _mail_domain("TEST_MAIL_DOMAIN")
    assert caplog.records == []
