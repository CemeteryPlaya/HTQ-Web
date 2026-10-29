"""Узел ``tasks.boards.admin`` — «Доски: настройки, поля и автоматизация»
(канбан-доски, решение K-39).

Свою доску без узла правят глава отдела и владелец проекта задач, любую —
администратор задач (``is_elevated``). Узел ``EXPLICIT_ONLY``
(``tasks/access_functions.py``): по умолчанию его нет ни у одной системной
роли — явная пустая строка у каждой, кроме ``platform-admin`` (приём
``0028``), чтобы редактор ролей показывал «нет доступа (выдаётся только явно)».
Выданное вручную не затирается (``get_or_create``).
"""

from django.db import migrations

FLAGS = ("can_view", "can_create", "can_edit", "can_delete")
NODE = "tasks.boards.admin"


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for role in Role.objects.filter(is_system=True).exclude(code="platform-admin"):
        RolePermission.objects.get_or_create(
            role=role, node=NODE, defaults={flag: False for flag in FLAGS})


def unseed(apps, schema_editor):
    RolePermission = apps.get_model("access", "RolePermission")
    (RolePermission.objects.filter(node=NODE, role__is_system=True)
     .filter(**{flag: False for flag in FLAGS})
     .delete())


class Migration(migrations.Migration):

    dependencies = [("access", "0028_tasks_board_nodes")]

    operations = [migrations.RunPython(seed, unseed)]
