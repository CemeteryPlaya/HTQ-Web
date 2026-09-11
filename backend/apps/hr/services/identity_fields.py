"""Единственное место, где записано соответствие полей Employee и аккаунта.

Спека: docs/superpowers/specs/2026-08-25-hr-identity-sync-design.md §8.

Сравнение идёт ПОСЛЕ нормализации, иначе "+7 705…" против "8705…" выглядел бы
вечным расхождением: синк писал бы в БД на каждом проходе, а подтверждающий
получал бы заявку на пустом месте. Регистр при этом значим — "иван" и "Иван"
это разные значения, и решать, какое верное, должен человек.
"""
from __future__ import annotations

#: Employee-поле -> поле профиля в apps.users.
FIELD_MAP: dict[str, str] = {
    "first_name": "first_name",
    "last_name": "last_name",
    "middle_name": "patronymic",
    "phone": "phone",
    "bio": "bio",
    "avatar_url": "avatar_url",
    "email": "email",
}

#: То, что вообще может быть записано в аккаунт. ``email`` сюда НЕ входит:
#: смена логина остаётся админской операцией (спека §15), а расхождение по нему
#: только показывается.
SYNCABLE: tuple[str, ...] = tuple(f for f in FIELD_MAP if f != "email")

_DIGITS_ONLY = {"phone"}


def normalize(field: str, value) -> str:
    """Каноническая форма значения для сравнения. None/пусто/пробелы -> ""."""
    text = ("" if value is None else str(value)).strip()
    if field in _DIGITS_ONLY:
        return "".join(ch for ch in text if ch.isdigit())
    return text


def differs(field: str, left, right) -> bool:
    """Различаются ли два значения одного поля после нормализации."""
    return normalize(field, left) != normalize(field, right)
