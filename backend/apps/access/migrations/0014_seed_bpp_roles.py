"""Модуль БЗО: восемь системных ролей (ТЗ §17, матрица —
docs/plans/2026-09-27-bpp-roles-matrix.md, утверждает Алгазы, Q-C14).

Узлы-операции (три сегмента) и группы статей у КАЖДОЙ роли — явной строкой:
без неё узел наследует глубину родителя (CLAUDE.md, «Новые под-узлы
реестра заводить сразу с явными строками», образец — 0008).
"""

from django.db import migrations

V, C, E, D = "can_view", "can_create", "can_edit", "can_delete"
ALL_FLAGS = (V, C, E, D)

OPERATIONS = ("bpp.budgets.approve", "bpp.requests.cancel_approved",
              "bpp.agreements.terminate", "bpp.invoices.decision", "bpp.invoices.payment",
              "bpp.counterparties.block", "bpp.alternatives.select",
              "bpp.accountable.payment", "bpp.invoices.closing_docs",
              "bpp.articles.supply", "bpp.articles.pm", "bpp.plan.all")

ROLES = {
    "bpp-fd": ("БЗО: Финансовый директор", {
        "bpp.budgets": (V, C, E, D), "bpp.budgets.approve": (E,), "bpp.requests": (V,),
        "bpp.requests.cancel_approved": (E,), "bpp.plan": (V,), "bpp.plan.all": (V,),
        "bpp.agreements": (V, E), "bpp.agreements.terminate": (E,),
        "bpp.invoices": (V,), "bpp.invoices.decision": (E,),
        "bpp.invoices.closing_docs": (E,), "bpp.bank": (V, C, E, D),
        "bpp.dashboard": (V,), "bpp.counterparties": (V, C, E),
        "bpp.counterparties.block": (E,), "bpp.alternatives": (V,),
        "bpp.alternatives.select": (E,), "bpp.kpi": (V, E), "bpp.accountable": (V, E),
        "bpp.articles.supply": (V,), "bpp.articles.pm": (V,), "bpp.settings": (V,),
        "refdata": (V, C, E), "project": (V, C, E), "project.members": (V,),
    }),
    "bpp-td": ("БЗО: Технический директор", {
        "bpp.budgets": (V,), "bpp.requests": (V,), "bpp.agreements": (V, E),
        "bpp.invoices": (V,), "bpp.dashboard": (V,), "bpp.counterparties": (V,),
        "bpp.alternatives": (V,), "bpp.articles.supply": (V,), "bpp.articles.pm": (V,),
        "refdata": (V,), "project": (V, C, E), "project.members": (V,),
    }),
    "bpp-od": ("БЗО: Операционный директор", {
        "bpp.budgets": (V,), "bpp.requests": (V,), "bpp.agreements": (V, E),
        "bpp.invoices": (V,), "bpp.dashboard": (V,), "bpp.counterparties": (V,),
        "bpp.alternatives": (V,), "bpp.kpi": (V,), "bpp.articles.supply": (V,),
        "bpp.articles.pm": (V,), "refdata": (V,), "project": (V, C, E),
        "project.members": (V,),
    }),
    "bpp-gd": ("БЗО: Генеральный директор", {
        "bpp.budgets": (V,), "bpp.requests": (V,), "bpp.agreements": (V, E),
        "bpp.invoices": (V,), "bpp.dashboard": (V,), "bpp.counterparties": (V,),
        "bpp.alternatives": (V,), "bpp.alternatives.select": (E,), "bpp.kpi": (V,),
        "bpp.articles.supply": (V,), "bpp.articles.pm": (V,), "refdata": (V,),
        "project": (V, C, E), "project.members": (V,),
    }),
    "bpp-buh": ("БЗО: Бухгалтер", {
        "bpp.agreements": (V,), "bpp.invoices": (V,), "bpp.invoices.payment": (E,),
        "bpp.bank": (V,), "bpp.dashboard": (V,), "bpp.counterparties": (V, C, E),
        "bpp.accountable": (V,), "bpp.accountable.payment": (E,),
        "bpp.articles.supply": (V,), "bpp.articles.pm": (V,), "refdata": (V,),
        "project": (V,), "project.members": (V,),
    }),
    "bpp-sn": ("БЗО: Снабженец", {
        "bpp.budgets": (V,), "bpp.requests": (V, C, E, D), "bpp.plan": (V, E),
        "bpp.agreements": (V, C, E), "bpp.invoices": (V, C, E, D),
        "bpp.invoices.closing_docs": (E,), "bpp.counterparties": (V, C),
        "bpp.alternatives": (V, C), "bpp.kpi": (V,), "bpp.accountable": (V, C),
        "bpp.articles.supply": (V,), "refdata": (V,), "project": (V,),
        "project.members": (V,),
    }),
    "bpp-pm": ("БЗО: Руководитель проекта", {
        "bpp.budgets": (V,), "bpp.requests": (V, C, E, D), "bpp.plan": (V, E),
        "bpp.agreements": (V, C, E), "bpp.invoices": (V, C, E, D),
        "bpp.invoices.closing_docs": (E,), "bpp.counterparties": (V, C),
        "bpp.alternatives": (V,), "bpp.accountable": (V, C), "bpp.articles.pm": (V,),
        "refdata": (V,), "project": (V,), "project.members": (V, E),
    }),
    "bpp-adm": ("БЗО: Администратор модуля", {
        "bpp.budgets": (V,), "bpp.requests": (V,), "bpp.agreements": (V,),
        "bpp.articles.supply": (V,), "bpp.articles.pm": (V,),
        "bpp.settings": (V, C, E, D), "refdata": (V, C, E),
        "project": (V, C, E), "project.members": (V, E),
    }),
}


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for code, (title, nodes) in ROLES.items():
        role, _ = Role.objects.get_or_create(code=code,
                                             defaults={"title": title, "is_system": True})
        explicit = dict.fromkeys(OPERATIONS, ())
        explicit.update(nodes)
        for node, flags in explicit.items():
            RolePermission.objects.update_or_create(
                role=role, node=node, defaults={flag: flag in flags for flag in ALL_FLAGS})


def unseed(apps, schema_editor):
    apps.get_model("access", "Role").objects.filter(code__in=list(ROLES)).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0013_platform_admin_bpp_modules")]

    operations = [migrations.RunPython(seed, unseed)]
