"""ГД видит всё (решение Руслана 01.10): разделы модуля БЗО и его «Обзор»
открыты генеральному директору целиком — просмотр плана закупок (все
позиции), подотчёта, выписок и сверки, настроек модуля и закрывающих
документов счёта (АВР, накладные, счета-фактуры — по ТЗ §21 их видели только
автор, ФД и БУХ).

Действия не меняются: решения, оплаты, правка — как в access/0014. Меняется
только признак ``can_view`` у ``bpp-gd``; строки узлов-операций уже есть
(явные пустые — 0014), остальные заводятся здесь.
"""

from django.db import migrations

ROLE = "bpp-gd"
NODES = ("bpp.plan", "bpp.plan.all", "bpp.accountable", "bpp.bank", "bpp.settings",
         "bpp.invoices.closing_docs")
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")


def grant(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    role = Role.objects.filter(code=ROLE).first()
    if role is None:
        return
    for node in NODES:
        row, _ = RolePermission.objects.get_or_create(
            role=role, node=node, defaults={flag: False for flag in FLAGS})
        if not row.can_view:
            row.can_view = True
            row.save(update_fields=["can_view"])


def revoke(apps, schema_editor):
    apps.get_model("access", "RolePermission").objects.filter(
        role__code=ROLE, node__in=NODES).update(can_view=False)


class Migration(migrations.Migration):

    dependencies = [("access", "0018_bpp_routes_node")]

    operations = [migrations.RunPython(grant, revoke)]
