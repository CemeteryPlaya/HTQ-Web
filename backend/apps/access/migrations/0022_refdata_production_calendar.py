"""Узел ``refdata.production_calendar`` — правка производственного календаря
(A7.1, D-S7-1, решение 02.10).

Календарь РК стал общим справочником группы (``refdata.ProductionDay``).
Править его могут операционный директор (``bpp-od``) и HR (``hr-senior``,
``hr-lead``) — именно у них сегодня правка кадрового календаря; «только
управляющая компания» проверяет ``refdata.interface.can_edit``. Узел объявлен
``EXPLICIT_ONLY`` (``refdata/access_functions.py``): роль с правами на весь
``refdata`` его не наследует. Явная строка — у КАЖДОЙ системной роли, кроме
модульной ``platform-admin`` (у остальных пустая, то есть запрет). Кастомным ролям право не выдаётся.
"""

from django.db import migrations

NODE = "refdata.production_calendar"
EDITORS = ("bpp-od", "hr-senior", "hr-lead")
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    # ``platform-admin`` — роль-минимум из одних модульных строк (access/0002):
    # узел ``EXPLICIT_ONLY`` ему без строки и так закрыт, а лишняя строка ломает
    # «ровно по модулю на роль».
    for role in Role.objects.filter(is_system=True).exclude(code="platform-admin"):
        RolePermission.objects.update_or_create(
            role=role, node=NODE,
            defaults={f: (f == "can_edit" and role.code in EDITORS) for f in FLAGS})


def unseed(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(node=NODE).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0021_bpp_all_nodes")]

    operations = [migrations.RunPython(seed, unseed)]
