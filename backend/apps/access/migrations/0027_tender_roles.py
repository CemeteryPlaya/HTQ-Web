"""Тендерный модуль: пять системных ролей ``tender-*`` (T0.3; матрица — план
этапов 0–2, §1, docs/plans/2026-10-07-tender-stages-0-2-plan.md).

Явная строка у КАЖДОЙ роли на КАЖДОМ узле матрицы: пустая — запрет (без неё
узел наследует глубину родителя, CLAUDE.md, образец — 0014). Узлы
``EXPLICIT_ONLY`` модуля (``tender/access_functions.py``) получают явную
пустую строку и у остальных системных ролей, кроме модульной
``platform-admin`` (приём 0022/0024/0025). А новые роли — явные пустые строки
на узлах ``EXPLICIT_ONLY`` соседей, которые несёт каждая системная роль
(0022, 0024, 0025). Списки — литералами: миграция не читает реестр, он
меняется вместе с кодом.

Роли ``tender-gd`` в пилоте нет (мастер-план, T-11).
"""

from django.db import migrations

V, C, E, D = "can_view", "can_create", "can_edit", "can_delete"
FLAGS = (V, C, E, D)

#: Узлы матрицы. Группа ``tender.award`` строк не несёт (как ``bpp.articles``).
NODES = ("tender", "tender.requests", "tender.requests.all", "tender.tenders",
         "tender.tenders.all", "tender.award.quality", "tender.award.approve",
         "tender.prospects", "tender.receipts", "tender.settings")

EXPLICIT_ONLY = ("tender.requests.all", "tender.tenders.all", "tender.award.quality",
                 "tender.award.approve")

#: Узлы ``EXPLICIT_ONLY`` соседей с явной строкой у каждой системной роли.
FOREIGN_EXPLICIT = ("refdata.production_calendar", "project.structure", "project.roles",
                    "bpp.entry")

ROLES = {
    "tender-buyer": ("Тендеры: Закупщик", {
        "tender": (V, C, E, D), "tender.requests": (V, C, E, D),
        "tender.tenders": (V, C, E, D), "tender.prospects": (V, C, E),
        "tender.receipts": (V, C, E),
    }),
    "tender-quality": ("Тендеры: Проверка качества", {
        "tender": (V,), "tender.tenders": (V,), "tender.tenders.all": (V,),
        "tender.award.quality": (E,),
    }),
    "tender-fd": ("Тендеры: Финансовый директор", {
        "tender": (V,), "tender.requests": (V,), "tender.requests.all": (V,),
        "tender.tenders": (V,), "tender.tenders.all": (V,), "tender.award.approve": (E,),
        "tender.prospects": (V,), "tender.receipts": (V,), "tender.settings": (V,),
    }),
    "tender-viewer": ("Тендеры: Просмотр", {
        "tender": (V,), "tender.requests": (V,), "tender.requests.all": (V,),
        "tender.tenders": (V,), "tender.tenders.all": (V,), "tender.prospects": (V,),
        "tender.receipts": (V,),
    }),
    "tender-adm": ("Тендеры: Администратор модуля", {
        "tender": (V, C, E, D), "tender.requests": (V, C, E, D), "tender.requests.all": (V,),
        "tender.tenders": (V, C, E, D), "tender.tenders.all": (V,),
        "tender.prospects": (V, C, E, D), "tender.receipts": (V, C, E),
        "tender.settings": (V, E),
    }),
}


def _put(RolePermission, role, node, flags) -> None:
    RolePermission.objects.update_or_create(
        role=role, node=node, defaults={flag: flag in flags for flag in FLAGS})


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for code, (title, rows) in ROLES.items():
        role, _ = Role.objects.get_or_create(code=code,
                                             defaults={"title": title, "is_system": True})
        for node in NODES:
            _put(RolePermission, role, node, rows.get(node, ()))
        for node in FOREIGN_EXPLICIT:
            _put(RolePermission, role, node, ())
    # ``platform-admin`` — роль-минимум из одних модульных строк (access/0002):
    # узел ``EXPLICIT_ONLY`` ему без строки и так закрыт.
    others = (Role.objects.filter(is_system=True)
              .exclude(code__in=[*ROLES, "platform-admin"]))
    for role in others:
        for node in EXPLICIT_ONLY:
            _put(RolePermission, role, node, ())


def unseed(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(node__in=EXPLICIT_ONLY).delete()
    apps.get_model("access", "Role").objects.filter(code__in=list(ROLES)).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0026_grant_tender_module")]

    operations = [migrations.RunPython(seed, unseed)]
