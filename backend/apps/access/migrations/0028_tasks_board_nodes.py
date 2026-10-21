"""Узлы досок задач — ``tasks.departments.all`` и ``project.board``
(docs/plans/2026-10-21-kanban-boards-master-plan.md, K-11, K-12, K-15;
спека этапа 1, K1.2).

``tasks.departments.all`` — «Доски всех отделов»: просмотр у ОД и ГД.
``project.board`` теперь открывает и задачи внутри досок проектов, поэтому
получает просмотр у ГД (решение заказчика 21.10) и становится
``EXPLICIT_ONLY`` (``project/access_functions.py``): системным ролям без строки
ставится явная пустая. Оба узла — явная строка у КАЖДОЙ системной роли, кроме
модульной ``platform-admin`` (приём ``0024``): ей узел ``EXPLICIT_ONLY`` без
строки и так закрыт.

У ролей ``bpp-*`` строка доски уже есть (``0020``) — меняется только ``bpp-gd``.
У остальных — ``get_or_create``: выданный вручную просмотр не затирается.
"""

from django.db import migrations

FLAGS = ("can_view", "can_create", "can_edit", "can_delete")
ALL_DEPTS = "tasks.departments.all"
BOARD = "project.board"
DIRECTORS = ("bpp-od", "bpp-gd")
BOARD_VIEWERS = ("bpp-td", "bpp-od", "bpp-gd", "bpp-pm", "bpp-adm")


def _view_only(view: bool) -> dict[str, bool]:
    return {flag: (flag == "can_view" and view) for flag in FLAGS}


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for role in Role.objects.filter(is_system=True).exclude(code="platform-admin"):
        RolePermission.objects.update_or_create(
            role=role, node=ALL_DEPTS, defaults=_view_only(role.code in DIRECTORS))
        if role.code.startswith("bpp-"):
            RolePermission.objects.update_or_create(
                role=role, node=BOARD, defaults=_view_only(role.code in BOARD_VIEWERS))
        else:
            RolePermission.objects.get_or_create(
                role=role, node=BOARD, defaults=_view_only(False))


def unseed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    RolePermission.objects.filter(node=ALL_DEPTS).delete()
    gd = Role.objects.filter(code="bpp-gd").first()
    if gd is not None:
        RolePermission.objects.update_or_create(role=gd, node=BOARD, defaults=_view_only(False))
    # Пустые строки, поставленные этой миграцией не-bpp ролям; ручной просмотр остаётся.
    (RolePermission.objects.filter(node=BOARD, role__is_system=True)
     .exclude(role__code__startswith="bpp-")
     .filter(**{flag: False for flag in FLAGS})
     .delete())


class Migration(migrations.Migration):

    dependencies = [("access", "0027_tender_roles")]

    operations = [migrations.RunPython(seed, unseed)]
