"""Засеять роль-минимум, с которой систему прав можно раздать.

Без неё стадия 2 выкатывается с ПУСТЫМ каталогом: ролей нет, назначений нет,
а значит у всех, кроме суперпользователя, карта прав пуста и закрыт каждый
гейтованный раздел — включая те, через которые роли и выдаются. Классический
запертый-снаружи ключ: чтобы выдать права, нужны права.

Роль системная (``is_system=True``) — удалить её через API нельзя намеренно:
это единственный гарантированно существующий носитель полного доступа, и
снести его значило бы вернуть ту же блокировку.

Список модулей заморожен литералом, а не прочитан из ``KNOWN_SERVICES``:
миграции обязаны давать один и тот же результат независимо от того, как с тех
пор изменился код. Новый модуль в реестре не появится у этой роли сам — его
добавляют осознанно, отдельной миграцией или через интерфейс.
"""

from django.db import migrations

ROLE_CODE = "platform-admin"

MODULES = (
    "users", "hr", "tasks", "approvals", "cms", "media", "mail",
    "messenger", "conference", "contracts", "signoff", "companies", "access",
)


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RoleModulePermission = apps.get_model("access", "RoleModulePermission")

    role, _created = Role.objects.get_or_create(
        code=ROLE_CODE,
        defaults={"title": "Администратор платформы", "is_system": True},
    )
    # is_system выставляется и на уже существующей строке: роль могли завести
    # руками до этой миграции, и тогда она осталась бы удаляемой.
    if not role.is_system:
        role.is_system = True
        role.save(update_fields=["is_system"])

    for module in MODULES:
        RoleModulePermission.objects.update_or_create(
            role=role, module=module, defaults={"level": "admin"},
        )


def unseed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    Role.objects.filter(code=ROLE_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
