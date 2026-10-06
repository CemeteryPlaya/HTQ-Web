"""Узел ``bpp.entry`` — вход в раздел «Закупки и оплаты» без документов
(решение пользователя 06.10, проектная структура).

Экран «Проектов» со структурой проекта живёт в разделе ``/bpp``, а гейт
раздела — уровень модуля ``bpp:read``. Кадровый руководитель (``hr-lead``)
правит проектную структуру (``project.structure``, access/0024), но ролей
``bpp-*`` у него нет. Узел-пропуск даёт ровно этот уровень: глубину он
никому не передаёт (лист реестра), а реестры модуля пускают к документам по
своим узлам.

``view`` — у ``hr-lead`` и восьми ролей ``bpp-*`` (у них раздел и так
открыт, строка — для явности); у остальных системных ролей, кроме модульной
``platform-admin``, — явная пустая строка (приём ``0022``).
"""

from django.db import migrations

NODE = "bpp.entry"
VIEWERS = ("hr-lead", "bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-sn", "bpp-pm",
           "bpp-adm")
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for role in Role.objects.filter(is_system=True).exclude(code="platform-admin"):
        RolePermission.objects.update_or_create(
            role=role, node=NODE,
            defaults={f: (f == "can_view" and role.code in VIEWERS) for f in FLAGS})


def unseed(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(node=NODE).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0024_project_structure_nodes")]

    operations = [migrations.RunPython(seed, unseed)]
