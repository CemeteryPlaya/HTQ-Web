"""Чистая логика сравнения идентичности — без БД.

План: docs/superpowers/plans/2026-08-25-hr-identity-sync.md, задача 1.
"""
from __future__ import annotations

from apps.hr.services.identity_fields import FIELD_MAP, SYNCABLE, differs, normalize


def test_field_map_pairs_middle_name_to_patronymic():
    assert FIELD_MAP["middle_name"] == "patronymic"
    assert FIELD_MAP["phone"] == "phone"


def test_email_is_not_syncable():
    # email — сигнал: расхождение показываем, но в аккаунт никогда не пишем.
    assert "email" in FIELD_MAP
    assert "email" not in SYNCABLE


def test_empty_values_are_equivalent():
    assert not differs("bio", None, "")
    assert not differs("bio", "  ", None)


def test_phone_compared_by_digits():
    assert not differs("phone", "+7 705 123-45-67", "77051234567")
    assert differs("phone", "+7 705 123-45-67", "77051234568")


def test_text_compared_trimmed_but_case_sensitive():
    assert not differs("first_name", " Иван ", "Иван")
    assert differs("first_name", "иван", "Иван")


def test_normalize_returns_string_for_none():
    assert normalize("bio", None) == ""
