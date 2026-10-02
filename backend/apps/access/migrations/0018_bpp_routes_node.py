"""Узел ``bpp.routes`` — правка маршрутов согласования документов модуля
(В-09, отложенная часть B1.2 мастер-плана БЗО).

Ответ В-09: у разных документов своё ветвление, «менять его могут только
администратор и ФД». Право — у ``bpp-fd`` и ``bpp-adm``; администратор
платформы правит маршруты, как и раньше, без роли (``is_elevated``).
Явная строка — у КАЖДОЙ из восьми ролей ``bpp-*`` (CLAUDE.md: новые узлы
заводить сразу с явными строками), у остальных шести — пустая (запрет).
"""

from django.db import migrations

ROLES = ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-sn", "bpp-pm", "bpp-adm")
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")
NODE = "bpp.routes"
EDITORS = ("bpp-fd", "bpp-adm")


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for code in ROLES:
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        RolePermission.objects.update_or_create(
            role=role, node=NODE,
            defaults={flag: (flag == "can_edit" and code in EDITORS) for flag in FLAGS})


def unseed(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(node=NODE).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0017_bpp_requests_all_plan_reassign")]

    operations = [migrations.RunPython(seed, unseed)]
