"""Блок L: системная роль «Администратор сервисов».

Заменяет is_staff на экранах шести аппок (admin=True снимается, решение
заказчика 24.09.2026): admin по media, conference, messenger, mail, cms,
approvals. Текущим is_staff её выдаёт manage.py access_backfill_services_admin,
новым — редактор ролей. Общая для группы (company_slug пуст), системная.

Узлы и признаки — литералами по access_functions.py шести аппок на 24.09.2026.
"""

from django.db import migrations

ROLE_CODE = "services-admin"
TITLE = "Администратор сервисов"

V = ("can_view",)
VD = ("can_view", "can_delete")
VCD = ("can_view", "can_create", "can_delete")
VE = ("can_view", "can_edit")
FULL = ("can_view", "can_create", "can_edit", "can_delete")

NODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("media.files", VCD),
    ("media.avatars", VCD),
    ("conference.join", V),
    ("conference.history", VD),
    ("conference.recordings", VD),
    ("conference.transcripts", VD),
    ("conference.invites", VCD),
    ("messenger.chats", V),
    ("messenger.rooms", FULL),
    ("messenger.moderation", VD),
    ("mail.messages", V),
    ("mail.mailboxes", FULL),
    ("mail.server", VE),
    ("cms.news", FULL),
    ("cms.home_sections", FULL),
    ("cms.contact_requests", FULL),
    ("cms.conference", FULL),
    ("approvals.requests", FULL),
    ("approvals.templates", FULL),
    ("approvals.projects", FULL),
    ("approvals.reference", FULL),
    ("approvals.stats", FULL),
    ("approvals.decisions", V),
)

_ALL = ("can_view", "can_create", "can_edit", "can_delete")


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    role, _ = Role.objects.get_or_create(
        code=ROLE_CODE, defaults={"title": TITLE, "is_system": True})
    for node, flags in NODES:
        RolePermission.objects.update_or_create(
            role=role, node=node,
            defaults={flag: flag in flags for flag in _ALL},
        )


def unseed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    Role.objects.filter(code=ROLE_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0011_employee_basic_block_l"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
