"""Узлы проектной структуры — ``project.structure`` и ``project.roles``
(docs/plans/2026-10-06-project-structure-spec.md, PS-9).

``project.structure`` — правка структуры ЛЮБОГО проекта (свой проект
руководитель правит по факту руководства, без узла); ``project.roles`` —
правка справочника проектных ролей. Право — у ФД, ТД, ОД, ГД, АДМ и
``hr-lead``. Оба узла ``EXPLICIT_ONLY`` (``project/access_functions.py``):
роль с правами на весь ``project`` их не наследует. Явная строка — у КАЖДОЙ
системной роли, кроме модульной ``platform-admin`` (у остальных пустая, то
есть запрет) — приём ``0022``.
"""

from django.db import migrations

NODES = ("project.structure", "project.roles")
EDITORS = ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-adm", "hr-lead")
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    # ``platform-admin`` — роль-минимум из одних модульных строк (access/0002):
    # узел ``EXPLICIT_ONLY`` ему без строки и так закрыт.
    for role in Role.objects.filter(is_system=True).exclude(code="platform-admin"):
        for node in NODES:
            RolePermission.objects.update_or_create(
                role=role, node=node,
                defaults={f: (f == "can_edit" and role.code in EDITORS) for f in FLAGS})


def unseed(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(node__in=NODES).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0023_bpp_holding_node")]

    operations = [migrations.RunPython(seed, unseed)]
