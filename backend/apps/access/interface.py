"""Публичный API аппки access для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к правам. Прямой
импорт ``apps.access.models`` / ``apps.access.services`` из другой аппки
запрещён и ловится ``apps/core/tests/test_app_isolation.py``.

``require_service("access")`` первой строкой каждой функции — общий для
платформы гейт отключаемости. Он же объясняет, почему ``access`` внесён в
``CORE_MODULES``: выключенный домен доступа означал бы «ни у кого нет прав»,
то есть не режим работы, а авария.
"""

from __future__ import annotations

from apps.access.services import hierarchy, holders, resolve
from apps.core.services import require_service


def permission_level(user, module: str, company: str | None) -> str:
    """Уровень пользователя на модуль в компании: none | read | write | admin."""
    require_service("access")
    return resolve.permission_level(user, module, company)


def permissions_for(user, company: str | None) -> dict[str, dict]:
    """Карта «модуль → уровень и область» для ``/me`` и профиля.

    Модули со ``none`` в карту не попадают: отсутствие ключа и есть «нет
    доступа».
    """
    require_service("access")
    return resolve.permissions_for(user, company)


def subordinate_companies(user, company: str | None) -> list[str]:
    """Компании ниже по дереву владения, над сотрудниками которых он начальник.

    Пусто у всех, кроме руководителей с включённой внешней иерархией (§1.4).
    Стадия 2 список отдаёт, но выборки по нему не режет.
    """
    require_service("access")
    return hierarchy.subordinate_companies(user, company)


def external_holders(company: str) -> list[dict]:
    """Кто из компаний-предков держит права в ``company`` через обслуживающую
    должность — задача 7 блока C (``apps.access.services.holders.external_holders``).

    ``apps.companies`` — единственный вызывающий: своей ручкой
    (``GET companies/<slug>/external-holders``) она обязана спросить
    настройку видимости (``Company.show_external_holders``, решение
    заказчика 4) САМА, до этого вызова — здесь её нет и быть не должно
    (``apps.access`` не видит модели соседа), список отдаётся безусловно.
    """
    require_service("access")
    return holders.external_holders(company)


__all__ = ["external_holders", "permission_level", "permissions_for", "subordinate_companies"]
