"""Узел ``bpp.holding`` — «Сводка группы по модулю БЗО» (A8.1, D-S7-8).

Просмотр сводки по компаниям группы (лимит бюджетов, счета, договоры) — у ФД
и ГД; явная пустая строка у остальных шести ролей ``bpp-*`` (узел
``EXPLICIT_ONLY``: глубину у предка он не берёт, но редактор ролей и сторож
«у каждой роли — явная строка» ждут её, как у ``bpp.*.all``, access/0021).
Сама ручка к тому же открывается только на поддомене холдинга.
"""

from django.db import migrations

ROLES = ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-sn", "bpp-pm", "bpp-adm")
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")
NODE = "bpp.holding"
VIEWERS = ("bpp-fd", "bpp-gd")


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for code in ROLES:
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        RolePermission.objects.update_or_create(
            role=role, node=NODE,
            defaults={f: (f == "can_view" and code in VIEWERS) for f in FLAGS})


def unseed(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(node=NODE).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0022_refdata_production_calendar")]

    operations = [migrations.RunPython(seed, unseed)]
