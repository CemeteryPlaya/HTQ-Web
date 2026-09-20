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
from apps.access.services.identity import identity
from apps.core.services import require_service


def permission_level(user, module: str, company: str | None) -> str:
    """Уровень пользователя на модуль в компании: none | read | write | admin."""
    require_service("access")
    return resolve.permission_level(user, module, company)


def resolution(user, company: str | None):
    """Роли пользователя в компании, посчитанные ОДИН раз — для серии проверок.

    Непрозрачный контекст (``apps.access.services.resolve.Resolution``):
    вызывающий не разбирает его, а передаёт обратно в ``flags_for``/
    ``permissions_for`` параметром ``resolution=``. Нужен там, где одна
    ручка проверяет несколько узлов подряд (кадровая карточка — редактирование,
    перевод, секции Т-2, область отдела): без него каждая проверка заново
    ходила бы в базу за ролями и назначениями и переключала бы схему на
    компании-предки ради наследования — по три запроса на узел.

    ``None`` для суперпользователя: ему контекст не нужен вовсе, каждая
    функция ниже отвечает ему до обращения к ролям, и строить ``Resolution``
    значило бы вернуть в горячий путь ровно те запросы, которых он избегает
    (см. докстринг ``resolve.resolve_for``). ``None`` в ``resolution=`` —
    штатное значение, а не ошибка: функции считают роли сами.
    """
    require_service("access")
    if identity(user)[1]:
        return None
    return resolve.resolve_for(user, company)


def flags_for(user, node: str, company: str | None, *, resolution=None) -> frozenset[str]:
    """Действующие признаки глубины пользователя на узле реестра функций.

    Объединение по всем его ролям в компании; у узла без собственной строки —
    глубина ближайшего предка (``resolve.flags_for``). Пустое множество —
    «нет прав», в том числе без контекста компании. Суперпользователь получает
    все признаки без единого запроса.

    Это проверка ПО УЗЛУ, а не по модулю — тоньше гейта ``api_view(module=,
    level=)``: уровень модуля считается по всему поддереву, и роль с DELETE
    на календаре агрегируется в ``admin`` модуля ``hr``, ничего не говоря о
    праве удалять сотрудников. Ручка, которой важен конкретный узел,
    спрашивает именно его — так с задачи 9 блока I проверяет кадровый домен
    (``apps.hr.rbac``).
    """
    require_service("access")
    return resolve.flags_for(user, node, company, resolution=resolution)


def permissions_for(user, company: str | None, *, resolution=None) -> dict[str, dict]:
    """Карта «модуль → уровень и область» для ``/me`` и профиля.

    Модули со ``none`` в карту не попадают: отсутствие ключа и есть «нет
    доступа». ``scope`` каждого модуля — область, с которой пришло право
    САМОГО ВЫСОКОГО уровня (широкое чтение не расширяет узкую запись, см.
    ``resolve.permissions_for``): по ней домен режет выборки — «свой отдел»
    против «вся компания».
    """
    require_service("access")
    return resolve.permissions_for(user, company, resolution=resolution)


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


def serving_holders(company: str) -> list[int]:
    """Id пользователей, чья должность в компании-предке помечена
    обслуживающей и реально несёт им права в ``company`` — задача 8 блока C
    (``apps.access.services.holders.serving_holder_ids``).

    То же ядро обхода, что у ``external_holders`` выше, только голые id вместо
    витрины: ``apps.companies`` использует их, чтобы завести
    ``CompanyMembership`` (``manage.py company_grant --serving``) и напечатать
    разрыв при заведении компании (``company_create``) — членство остаётся
    отдельным, явным решением человека (решение заказчика 3), эта функция
    только называет, кому оно понадобится.
    """
    require_service("access")
    return holders.serving_holder_ids(company)


__all__ = ["external_holders", "flags_for", "permission_level", "permissions_for",
           "resolution", "serving_holders", "subordinate_companies"]
