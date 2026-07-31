"""Разбор старой свободной строки ``contacts`` на три поля.

Функция живёт в миграции 0007 и выполняется ровно один раз, поэтому
проверяется здесь напрямую: ошибку в ней после `migrate` уже не увидеть —
исходной строки в базе не останется.
"""

from importlib import import_module

import pytest

_split = import_module(
    "apps.contracts.migrations.0007_counterparty_contact_fields")._split_contacts


@pytest.mark.parametrize("text, expected", [
    # То, как контакты и писали: placeholder старой формы. Должности своего
    # поля не имеет, поэтому «директор» остаётся частью ФИО — разносить это
    # по колонкам значило бы угадывать (см. докстринг миграции).
    ("Петров П., директор, +7 700 000 00 00, info@alfa.kz",
     {"contact_name": "Петров П., директор", "phone": "+7 700 000 00 00",
      "email": "info@alfa.kz"}),
    # Один телефон без имени — самый частый короткий вариант.
    ("+7 700 000 00 00",
     {"contact_name": "", "phone": "+7 700 000 00 00", "email": ""}),
    # Порядок произвольный, разделители разные.
    ("info@beta.kz; Иванова А.\nглавный бухгалтер",
     {"contact_name": "Иванова А., главный бухгалтер", "phone": "",
      "email": "info@beta.kz"}),
    # Ничего узнаваемого — текст целиком уходит в ФИО, а не теряется.
    ("связь через приёмную",
     {"contact_name": "связь через приёмную", "phone": "", "email": ""}),
    ("", {"contact_name": "", "phone": "", "email": ""}),
])
def test_split_contacts(text, expected):
    assert _split(text) == expected


def test_split_contacts_never_overflows_the_new_columns():
    """Длины полей — 200/30/254; разбор обязан в них укладываться, иначе
    миграция упадёт на первой же мусорной строке."""
    result = _split("Я" * 400 + ", " + "Ю" * 400 + ", +7 700 000 00 00")
    assert len(result["contact_name"]) == 200
    assert len(result["phone"]) <= 30
