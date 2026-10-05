"""Узлы «все документы» ``bpp.invoices.all``, ``bpp.agreements.all``,
``bpp.accountable.all`` (D-S6-5, сверка B §19; план этапа 6 A, задача 5).

Правило ``sees_all`` в сервисах счетов, договоров и подотчёта выводилось
как «просмотр без права создавать» на самом документе. Совмещающий роли
(СН + ФД) получал создание от СН и переставал видеть чужие счета. Теперь —
отдельный узел, как ``bpp.requests.all`` (``access/0017``); круг ролей тот
же, что давала прежняя формула (матрица Алгазы 27.09 не меняется):

- счета — ФД, ТД, ОД, ГД, БУХ (у АДМ строки на счетах нет);
- договоры — ФД, ТД, ОД, ГД, БУХ, АДМ;
- подотчёт — ФД, БУХ.

Явная строка — у КАЖДОЙ из восьми ролей ``bpp-*``: без неё узел унаследовал
бы глубину родителя (CLAUDE.md). У прочих — пустая строка (запрет).
"""

from django.db import migrations

ROLES = ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-sn", "bpp-pm", "bpp-adm")
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")

GRANTS = {
    "bpp.invoices.all": ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh"),
    "bpp.agreements.all": ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-adm"),
    "bpp.accountable.all": ("bpp-fd", "bpp-buh"),
}


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for code in ROLES:
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for node, holders in GRANTS.items():
            RolePermission.objects.update_or_create(
                role=role, node=node,
                defaults={f: (f == "can_view" and code in holders) for f in FLAGS})


def unseed(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(node__in=list(GRANTS)).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0020_project_board_node")]

    operations = [migrations.RunPython(seed, unseed)]
