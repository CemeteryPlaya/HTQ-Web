"""Выдать роли «Администратор платформы» новый модуль ``files``.

Файловая подсистема ТЗ §21 (``apps.files``) добавила сервис ``files`` в
``KNOWN_SERVICES``. Роль из 0002 заморожена литералом и новый модуль сама не
получит — это сделано намеренно (см. докстринг 0002), поэтому модуль
добавляется здесь, осознанно. Полный доступ, как у остальных модулей этой
роли: все четыре признака глубины.
"""

from django.db import migrations

ROLE_CODE = "platform-admin"
MODULE = "files"
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")


def grant(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    role = Role.objects.filter(code=ROLE_CODE).first()
    if role is None:
        return  # роли нет — нечего расширять (её заводит 0002)
    RolePermission.objects.update_or_create(
        role=role, node=MODULE, defaults={flag: True for flag in FLAGS})


def revoke(apps, schema_editor):
    RolePermission = apps.get_model("access", "RolePermission")
    RolePermission.objects.filter(role__code=ROLE_CODE, node=MODULE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0012_seed_services_admin_role"),
    ]

    operations = [
        migrations.RunPython(grant, revoke),
    ]
