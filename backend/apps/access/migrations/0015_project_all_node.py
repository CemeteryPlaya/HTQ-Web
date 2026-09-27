"""Узел ``project.all`` — «все проекты, а не только участия» (мастер-план A1.3).

Явная строка у КАЖДОЙ роли модуля БЗО (CLAUDE.md: новые под-узлы заводить
сразу с явными строками): без неё узел унаследовал бы ``view`` от ``project``,
и ПМ снова видел бы чужие проекты. У ПМ — пустая строка (запрет), у
остальных — просмотр. ``platform-admin`` несёт полный доступ к корню
``project`` и получает узел наследованием — так и задумано.
"""

from django.db import migrations

NODE = "project.all"
SEES_ALL = ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-sn", "bpp-adm")
MEMBERS_ONLY = ("bpp-pm",)


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for code in SEES_ALL + MEMBERS_ONLY:
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        RolePermission.objects.update_or_create(
            role=role, node=NODE,
            defaults={"can_view": code in SEES_ALL, "can_create": False,
                      "can_edit": False, "can_delete": False})


def unseed(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(node=NODE).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0014_seed_bpp_roles")]

    operations = [migrations.RunPython(seed, unseed)]
