"""Засеять роль рядового сотрудника — то, что выдают в день приёма.

Без неё каждого нового человека пришлось бы собирать вручную из десятка узлов,
а собирают такое молча неправильно: забытый узел выглядит не как ошибка, а как
«наследует», и обнаруживается через неделю жалобой «не могу подать заявку».

Состав продиктован заказчиком и повторён здесь дословно: личный профиль,
мессенджер, конференции (только заходить), почта, календарь, задачи с
ежедневкой, новости на просмотр, заявки — создавать, подтверждать адресованные
и видеть свою статистику.

⚠️ Роль системная (``is_system=True``) — удалить её через API нельзя намеренно:
это шаблон, к которому возвращаются при каждом приёме, и снести его значило бы
вернуть ручную сборку. Копировать её при этом можно: именно так и делают
роль-вариацию (`catalog.copy_role`).

Пути узлов и наборы признаков заморожены литералами: миграция обязана давать
один и тот же результат независимо от того, как с тех пор изменился реестр
функций.
"""

from django.db import migrations

ROLE_CODE = "employee-basic"

VIEW = ("can_view",)
CREATE = ("can_view", "can_create")
EDIT = ("can_view", "can_create", "can_edit")
NONE: tuple[str, ...] = ()

#: ``узел -> признаки``. Пустой набор — ЯВНЫЙ запрет, а не «не задано»: им
#: закрывается создание конференций внутри разрешённого участия в них.
NODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("users.profile", EDIT),

    ("messenger.chats", VIEW),

    # «Только заходить, создавать запрещено»: участие разрешено, выдача ссылок
    # закрыта явным запретом.
    ("conference.join", VIEW),
    ("conference.invites", NONE),

    ("mail.messages", VIEW),

    ("tasks.calendar", CREATE),
    ("tasks.tasks", EDIT),
    ("tasks.daily_reports", CREATE),

    ("cms.news", VIEW),

    ("approvals.requests", CREATE),
    ("approvals.decisions", VIEW),
    ("approvals.stats", VIEW),
)


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")

    role, _created = Role.objects.get_or_create(
        code=ROLE_CODE,
        defaults={"title": "Сотрудник", "is_system": True},
    )
    if not role.is_system:
        role.is_system = True
        role.save(update_fields=["is_system"])

    for node, flags in NODES:
        RolePermission.objects.update_or_create(
            role=role, node=node,
            defaults={flag: True for flag in flags} | {
                flag: False for flag in ("can_view", "can_create", "can_edit",
                                         "can_delete") if flag not in flags},
        )


def unseed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    Role.objects.filter(code=ROLE_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0003_role_permission_depth"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
