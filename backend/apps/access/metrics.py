"""Бизнес-метрики доступа.

Собирается ``apps.core.metrics.collect_all`` по расписанию (Celery-beat), не на
скрейпе. Прямых импортов моделей соседних аппок здесь нет и не будет
(``apps/core/tests/test_app_isolation.py``) — но одна метрика (разрыв
«обслуживающая должность есть, членства нет», задача 8 блока C) честно ходит
за компанией и держателями через РАЗРЕШЁННЫЙ канал: свой же сервис
``apps.access.services.holders`` (он и так обходит ``apps.hr``/
``apps.companies`` через их ``interface.py``) и напрямую
``apps.companies.interface`` — тот же приём, каким уже пользуется
``holders.external_holders``.

Что здесь важно наблюдать. Ошибки в правах не выглядят авариями: никто не
получает 500, просто у части людей молча пропадают разделы либо, наоборот,
появляются лишние. Поэтому метрики целятся в ТИХИЕ перекосы — роль без единого
права, компания без единой выданной роли, обслуживающая должность без
членства, — а не в объём справочника.
"""

from __future__ import annotations

from django.db.models import Count

from apps.access.services import holders

from .models import PositionRole, Role, RoleAssignment


def _serving_gap_by_company() -> list[tuple[str, int]]:
    """Компании, где держатели обслуживающих должностей предков ещё не
    получили ``CompanyMembership`` — задача 8 блока C: разрыв, который эта
    метрика и заведена показывать (без явного членства токен для поддомена
    компании вообще не выпускается, см. ``manage.py company_grant --serving``).

    Платформенный охват БЕЗ опоры на текущий контекст компании — считать
    его иначе, кроме как обходом всех компаний, нечестно: ``current_company()``
    здесь взять неоткуда (Celery-beat зовёт ``collect()`` вне запроса), а
    подставить одну «главную» компанию значило бы врать про остальные.
    Слаги идут через ``apps.companies.interface.active_company_slugs()``
    (кэш 5 с, не требует ``search_path``), держателей на каждую даёт
    ``holders.serving_holder_ids`` — она сама переключает схему на предка
    (``use_company``) тем же приёмом, что и ``external_holders`` (задача 7).
    Компании без единого держателя — в том числе вершины дерева, у которых
    предков нет вовсе, — в результат не попадают: там разрыва не может быть
    по построению, а не потому что забыли посчитать.

    Стоимость — по компании на итерацию (обход предков плюс проверка
    членства на каждого найденного держателя): у группы, ради которой этот
    признак вообще завели (единицы обслуживающих должностей на холдинг), это
    на порядки дешевле, чем уже идущий раз в минуту сбор остальных метрик.
    """
    from apps.companies import interface as companies

    gap: list[tuple[str, int]] = []
    for slug in companies.active_company_slugs():
        holder_ids = holders.serving_holder_ids(slug)
        if not holder_ids:
            continue
        missing = sum(
            1 for user_id in holder_ids
            if slug not in companies.user_company_slugs(user_id)
        )
        if missing:
            gap.append((slug, missing))
    return gap


def collect() -> dict:
    assignments_by_company = (RoleAssignment.objects
                              .values("company_slug")
                              .annotate(n=Count("id"))
                              .order_by("company_slug"))
    position_roles_by_company = (PositionRole.objects
                                 .values("company_slug")
                                 .annotate(n=Count("id"))
                                 .order_by("company_slug"))

    # Роль без единого права выдаётся людям и не даёт ничего: типовой результат
    # недоведённой настройки, который со стороны выглядит как «нет доступа».
    empty_roles = Role.objects.annotate(n=Count("permissions")).filter(n=0).count()

    # Роль, дающая удаление хоть где-то: не ошибка сама по себе, но их рост
    # означает, что разрушающее право раздают вместо точечного.
    with_delete = (Role.objects
                   .filter(permissions__can_delete=True)
                   .distinct()
                   .count())

    return {
        "access_roles_total": {
            "help": "Ролей в общем каталоге",
            "values": [((), Role.objects.count())],
        },
        "access_roles_without_permissions": {
            "help": "Роли, не дающие ни одного права",
            "values": [((), empty_roles)],
        },
        "access_roles_with_delete": {
            "help": "Роли, дающие право удаления хоть на одной функции",
            "values": [((), with_delete)],
        },
        "access_position_roles_by_company": {
            "help": "Привязок «должность → роль» по компаниям",
            "labels": ["company"],
            "values": [((row["company_slug"],), row["n"])
                       for row in position_roles_by_company],
        },
        "access_personal_assignments_by_company": {
            "help": "Личных назначений ролей по компаниям",
            "labels": ["company"],
            "values": [((row["company_slug"],), row["n"])
                       for row in assignments_by_company],
        },
        "access_serving_holders_without_membership": {
            "help": ("Держат права через обслуживающую должность предка, но "
                     "ещё без CompanyMembership — по компаниям"),
            "labels": ["company"],
            "values": [((slug,), n) for slug, n in _serving_gap_by_company()],
        },
    }
