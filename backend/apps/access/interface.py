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

from apps.access.services import assignment, hierarchy, holders, resolve
from apps.access.services.identity import identity
from apps.core.services import require_service


def permission_level(user, module: str, company: str | None, *,
                     resolution=None) -> str:
    """Уровень пользователя на модуль в компании: none | read | write | admin.

    ``resolution`` — уже посчитанные роли (``resolution()`` ниже): гейт
    ``api_view(module=, level=)`` считает их один раз на запрос и отдаёт сюда,
    чтобы узловые проверки внутри вьюхи не пересчитывали то же самое (блок
    I.2, R8). ``None`` — «посчитай сам», как у ``flags_for``/``permissions_for``.
    """
    require_service("access")
    return resolve.permission_level(user, module, company, resolution=resolution)


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


def ensure_position_role(company_slug: str, position_id: int, role_code: str,
                         scope_kind: str) -> bool:
    """Выдать должности системную роль по коду — идемпотентно, не трогая
    остальные её роли (задача 11 блока I, ``apps.access.services.assignment.
    ensure_position_role``).

    Для сидов и переносов, а не для UI: ровно то, что сделал бы
    администратор в разделе «Роли должностей» после ``access_backfill_
    positions``. ``seed_hr_demo`` раскладывает через неё ``Post.hr_level``
    справочника структур (``apps/hr/management/group_structures.py``) в
    ``PositionRole`` — колонку ``Position.permissions`` сид с задачи 9 не
    пишет, а без ролей свежий стенд получал бы директоров без кадровых прав.
    Область — по тому же правилу, что у переноса: junior/middle → отдел
    держателя, senior/lead → компания.

    ``scope_kind`` — строковое значение (``"company"``/``"department"``):
    вызывающий не импортирует ``apps.access.models.ScopeKind`` — сосед
    видит только этот модуль. Роль обязана быть системной и существовать;
    иначе ``UnknownRole``/``ScopeInvalid`` (``apps.access.services.errors``)
    — сид не должен молча пропускать выдачу.

    Возвращает ``True``, если связь создана этим вызовом, ``False`` — если
    уже была (в т.ч. с другой областью — её не переписывает).
    """
    require_service("access")
    return assignment.ensure_position_role(company_slug, position_id, role_code, scope_kind)


def ensure_basic_role(company_slug: str, user_id: int) -> bool:
    """Выдать участнику компании базовую роль ``employee-basic`` —
    идемпотентно (рулинг M финальной волны блока I,
    ``apps.access.services.assignment.ensure_basic_role``).

    Единственный вызывающий — ``apps.companies`` в точке создания членства
    (``membership_service.grant_membership``): через неё идут ``company_grant``,
    ``tenancy_bootstrap --grant-all``, экран участников и стенд. Базовый
    доступ участникам на день выкатки раздаёт ``access_backfill_basic``;
    эта функция — всем, кто станет участником после.

    Область — вся компания. Роли нет в каталоге — ``UnknownRole``
    (``apps.access.services.errors``), а не молчаливое членство без прав.
    Возвращает ``True``, если назначение создано этим вызовом.
    """
    require_service("access")
    return assignment.ensure_basic_role(company_slug, user_id)


__all__ = ["ensure_basic_role", "ensure_position_role", "external_holders", "flags_for",
           "permission_level", "permissions_for", "resolution", "serving_holders",
           "subordinate_companies"]
