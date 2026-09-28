"""Узлы ``bpp.requests.all`` и ``bpp.plan.reassign`` (сверка B §7.3, план
этапа 2 A, задача 3).

До этой миграции оба права выводились из соседних узлов:

- «видит все заявки» — ``view`` на ``bpp.requests`` без ``create`` (ФД, ТД,
  ОД, ГД, АДМ — у них на заявках только просмотр, access/0014);
- «переназначает исполнителя позиций плана» — ``edit`` на ``bpp.settings``
  (только АДМ).

Теперь это отдельные узлы с тем же кругом ролей — смысл матрицы Алгазы не
меняется. Явная строка — у КАЖДОЙ из восьми ролей ``bpp-*`` (CLAUDE.md:
новые под-узлы заводить сразу с явными строками): без неё узел унаследовал
бы глубину родителя, и СН с ``view`` на ``bpp.requests`` увидел бы чужие
заявки, а СН и ПМ с ``edit`` на ``bpp.plan`` — переназначали бы позиции.
У остальных ролей — пустая строка (запрет).
"""

from django.db import migrations

ROLES = ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-sn", "bpp-pm", "bpp-adm")
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")

#: узел → (признак, роли, у которых он есть)
GRANTS = {
    "bpp.requests.all": ("can_view", ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-adm")),
    "bpp.plan.reassign": ("can_edit", ("bpp-adm",)),
}


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for code in ROLES:
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for node, (flag, holders) in GRANTS.items():
            RolePermission.objects.update_or_create(
                role=role, node=node,
                defaults={f: (f == flag and code in holders) for f in FLAGS})


def unseed(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(node__in=list(GRANTS)).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0016_grant_files_module")]

    operations = [migrations.RunPython(seed, unseed)]
