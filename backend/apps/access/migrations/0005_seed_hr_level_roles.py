"""Засеять четыре системные роли взамен четырёх кадровых уровней.

Блок I («Свернуть параллельный RBAC», ``docs/plans/2026-09-17-block-i-single-
rbac.md``, задача 1) переносит СЕГОДНЯШНИЙ фактический доступ старой кадровой
модели (``apps.hr.permissions.LEVEL_PRESETS`` — junior/middle/senior/lead,
плоские наборы ключей ``hr.*``) в целевую модель ролей и глубины: без этого
переноса переключение гейта на новую модель (задачи этого же блока следом)
отняло бы права у всех, кому сегодня назначен один из четырёх уровней.

Раскладка ключ -> (узел реестра, признаки) и её обоснование живут в
``apps/hr/legacy_roles.py`` (``KEY_TO_NODE``, ``nodes_for_level``) — в т.ч.
три места, где перевод неоднозначен (``view`` vs ``view.all``, ``transfer``,
чужой ключ ``contracts.advance_payment.record_payment``, сознательно
оставленный за рамками переноса). Полное обоснование — в отчёте задачи 1:
``.superpowers/sdd/2026-09-17-block-i-single-rbac/task-1-report.md``.

⚠️ Узлы и признаки ниже — ЗАМОРОЖЕННЫЕ ЛИТЕРАЛЫ, снятые с
``apps.hr.legacy_roles.nodes_for_level()`` НА МОМЕНТ НАПИСАНИЯ этой миграции
(тот же приём и та же причина, что в ``0004_seed_employee_role``, — см. его
докстринг): миграция обязана давать один и тот же результат независимо от
того, как реестр функций или таблица соответствия изменятся после неё.
Импортировать ``apps.hr.legacy_roles`` отсюда специально не стали и по
второй причине — эта миграция лежит в ``apps.access``, а ``apps.hr`` для неё
соседняя аппка (тот же ``apps/core/tests/test_app_isolation.py``, что
объясняется в докстринге ``legacy_roles.py``).

Роли системные (``is_system=True``) — как и ``employee-basic`` в 0004, через
API их удалить нельзя: это опора переноса, а не рядовая роль-вариация.
"""

from django.db import migrations

ROLE_CODES: dict[str, str] = {
    "junior": "hr-junior",
    "middle": "hr-middle",
    "senior": "hr-senior",
    "lead": "hr-lead",
}

ROLE_TITLES: dict[str, str] = {
    "hr-junior": "Кадры: junior",
    "hr-middle": "Кадры: middle",
    "hr-senior": "Кадры: senior",
    "hr-lead": "Кадры: lead",
}

# Признаки RolePermission — ровно четыре формы (из четырёх флагов
# view/create/edit/delete), в которые складываются узлы каждой роли (см.
# вывод apps.hr.legacy_roles.nodes_for_level() на момент письма миграции).
VIEW = ("can_view",)
EDIT = ("can_view", "can_edit")
FULL = ("can_view", "can_create", "can_edit")
ADMIN = ("can_view", "can_create", "can_edit", "can_delete")

_ALL_FLAGS = ("can_view", "can_create", "can_edit", "can_delete")

#: ``код роли -> (узел -> признаки)``. Заморожено с
#: ``apps.hr.legacy_roles.nodes_for_level("junior"|"middle"|"senior"|"lead")``.
ROLE_NODES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "hr-junior": (
        ("hr.departments", VIEW),
        ("hr.documents", VIEW),
        ("hr.employees", VIEW),
        ("hr.positions", VIEW),
        ("hr.production_calendar", VIEW),
    ),
    "hr-middle": (
        ("hr.departments", EDIT),
        ("hr.documents", FULL),
        ("hr.employees", EDIT),
        ("hr.employees.family", EDIT),
        ("hr.positions", EDIT),
        ("hr.production_calendar", VIEW),
    ),
    "hr-senior": (
        ("hr.accounts", VIEW),
        ("hr.departments", EDIT),
        ("hr.documents", FULL),
        ("hr.employees", FULL),
        ("hr.employees.family", EDIT),
        ("hr.employees.passport", EDIT),
        ("hr.employees.salary", EDIT),
        ("hr.identity_requests", VIEW),
        ("hr.org", ADMIN),
        ("hr.positions", EDIT),
        ("hr.production_calendar", ADMIN),
        ("hr.reports", VIEW),
        ("hr.staffing", ADMIN),
    ),
    "hr-lead": (
        ("hr.accounts", FULL),
        ("hr.departments", EDIT),
        ("hr.documents", FULL),
        ("hr.employees", ADMIN),
        ("hr.employees.family", EDIT),
        ("hr.employees.passport", EDIT),
        ("hr.employees.salary", EDIT),
        ("hr.identity_requests", EDIT),
        ("hr.org", ADMIN),
        ("hr.positions", EDIT),
        ("hr.production_calendar", ADMIN),
        ("hr.reports", VIEW),
        ("hr.staffing", ADMIN),
    ),
}


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")

    for code, nodes in ROLE_NODES.items():
        role, _created = Role.objects.get_or_create(
            code=code, defaults={"title": ROLE_TITLES[code], "is_system": True},
        )
        if not role.is_system:
            role.is_system = True
            role.save(update_fields=["is_system"])

        for node, flags in nodes:
            RolePermission.objects.update_or_create(
                role=role, node=node,
                defaults={flag: True for flag in flags}
                | {flag: False for flag in _ALL_FLAGS if flag not in flags},
            )


def unseed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    Role.objects.filter(code__in=ROLE_CODES.values()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0004_seed_employee_role"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
