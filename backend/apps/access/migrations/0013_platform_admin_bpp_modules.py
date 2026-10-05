"""Модуль БЗО: полный доступ роли-минимума на четыре новых модуля.

``platform-admin`` (0002) несёт полный доступ на КАЖДЫЙ модуль реестра —
иначе права некому выдать. Список модулей в 0002 заморожен литералом, и
новые модули к роли сами не прирастают (см. её докстринг), поэтому
project/refdata/notifications/bpp добавляются здесь явно — тем же приёмом,
что у 0012 (RolePermission, все четыре признака глубины).
"""

from django.db import migrations

ROLE_CODE = "platform-admin"
MODULES = ("project", "refdata", "notifications", "bpp")
_FULL = {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True}


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    role = Role.objects.filter(code=ROLE_CODE).first()
    if role is None:
        return
    for module in MODULES:
        RolePermission.objects.update_or_create(role=role, node=module, defaults=_FULL)


def unseed(apps, schema_editor):
    RolePermission = apps.get_model("access", "RolePermission")
    RolePermission.objects.filter(role__code=ROLE_CODE, node__in=MODULES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0012_seed_services_admin_role"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
