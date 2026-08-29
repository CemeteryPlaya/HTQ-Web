"""Бизнес-метрики доступа.

Собирается ``apps.core.metrics.collect_all`` по расписанию (Celery-beat), не на
скрейпе. Обращается ТОЛЬКО к своим моделям: кросс-доменные импорты запрещены
(``apps/core/tests/test_app_isolation.py``).

Что здесь важно наблюдать. Ошибки в правах не выглядят авариями: никто не
получает 500, просто у части людей молча пропадают разделы либо, наоборот,
появляются лишние. Поэтому метрики целятся в ТИХИЕ перекосы — роль без единого
права, компания без единой выданной роли, — а не в объём справочника.
"""

from __future__ import annotations

from django.db.models import Count

from .models import Level, PositionRole, Role, RoleAssignment


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

    # Роль, где ВСЕ уровни admin: не ошибка сама по себе, но их рост означает,
    # что грубые уровни используются как «включить всё».
    admin_only = (Role.objects
                  .annotate(total=Count("permissions"))
                  .exclude(total=0)
                  .exclude(permissions__level__in=[Level.READ, Level.WRITE])
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
        "access_roles_admin_only": {
            "help": "Роли, у которых все права уровня admin",
            "values": [((), admin_only)],
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
    }
