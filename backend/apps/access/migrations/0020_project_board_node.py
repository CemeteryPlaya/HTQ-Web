"""Узел ``project.board`` — «Доска задач проекта» (решение Руслана 01.10).

Ссылка с карточки «Проекта» на его доску задач и вход на страницу досок без
кадровых прав; доски видны по «Проектам», которые человек видит в модуле
(ПМ — свои, с ``project.all`` — все; ``tasks/services/project_service``).
Править и заводить доски по-прежнему может только администратор задач.

Просмотр — у ТД, ОД, АДМ и ПМ. Явная пустая строка — у ФД, ГД, БУХ и СН:
без неё узел наследует глубину ``project``, где просмотр есть у всех восьми
ролей (CLAUDE.md: новые под-узлы — сразу с явными строками).
"""

from django.db import migrations

ROLES = ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-sn", "bpp-pm", "bpp-adm")
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")
NODE = "project.board"
VIEWERS = ("bpp-td", "bpp-od", "bpp-adm", "bpp-pm")


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for code in ROLES:
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        RolePermission.objects.update_or_create(
            role=role, node=NODE,
            defaults={flag: (flag == "can_view" and code in VIEWERS) for flag in FLAGS})


def unseed(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(node=NODE).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0019_bpp_gd_sees_all")]

    operations = [migrations.RunPython(seed, unseed)]
