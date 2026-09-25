"""Блок L: добавить employee-basic узлы под сегодняшний открытый доступ.

До гейта модуля ручки media/conference/messenger/approvals пускали любого
вошедшего; «перенести как есть» (решение заказчика 24.09.2026) значит выдать
это базовой роли, а не отнять. Только ДОБАВЛЕНИЕ строк: существующие
(access/0004) не трогаются. Ни одного can_delete — иначе агрегат модуля
станет admin и откроет всем бывшие admin=True ручки (инвариант L1 спеки).

Пути и признаки заморожены литералами, как в 0004.
"""

from django.db import migrations

ROLE_CODE = "employee-basic"

VIEW = ("can_view",)
CREATE = ("can_view", "can_create")
EDIT = ("can_view", "can_create", "can_edit")

NODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("media.files", CREATE),
    ("messenger.rooms", EDIT),
    ("conference.history", VIEW),
    ("conference.transcripts", VIEW),
    ("approvals.projects", VIEW),
    ("approvals.templates", VIEW),
    ("approvals.reference", VIEW),
)

_ALL = ("can_view", "can_create", "can_edit", "can_delete")


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    role = Role.objects.filter(code=ROLE_CODE).first()
    if role is None:
        return
    for node, flags in NODES:
        RolePermission.objects.get_or_create(
            role=role, node=node,
            defaults={flag: flag in flags for flag in _ALL},
        )


def unseed(apps, schema_editor):
    RolePermission = apps.get_model("access", "RolePermission")
    RolePermission.objects.filter(
        role__code=ROLE_CODE, node__in=[node for node, _ in NODES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0010_backfill_role_company_slug"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
