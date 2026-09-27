"""Имена полей и статусов — как в плане этапа 2 (docs/plans/2026-09-28-bpp-stage2-executor-b.md).

- ``Budget.currency`` → ``currency_code``, ``PurchaseRequest.currency`` →
  ``currency_code``;
- ``BudgetVersion.status`` → ``state`` (``VersionState``) + одна действующая
  версия на бюджет ограничением БД;
- статус заявки «На согласовании» — ``in_approval`` (был ``on_review``):
  строки переводятся данными;
- ``PurchaseRequest.rework_comment`` — комментарий последнего возврата.

Переименования, а не «удалить и создать»: данные стенда сохраняются.
"""

from django.db import migrations, models
from django.db.models import Q


def forward_status(apps, schema_editor):
    PurchaseRequest = apps.get_model("bpp", "PurchaseRequest")
    PurchaseRequest.objects.filter(status="on_review").update(status="in_approval")


def backward_status(apps, schema_editor):
    PurchaseRequest = apps.get_model("bpp", "PurchaseRequest")
    PurchaseRequest.objects.filter(status="in_approval").update(status="on_review")


class Migration(migrations.Migration):

    dependencies = [
        ("bpp", "0005_accountable"),
    ]

    operations = [
        migrations.RenameField("budget", "currency", "currency_code"),
        migrations.RenameField("purchaserequest", "currency", "currency_code"),
        migrations.RemoveConstraint("budgetversion", "uq_bpp_budget_one_draft"),
        migrations.RenameField("budgetversion", "status", "state"),
        migrations.AlterField(
            "budgetversion", "state",
            models.CharField(choices=[("draft", "Черновик"), ("active", "Действующая"),
                                      ("archived", "Архив")],
                             default="draft", max_length=16)),
        migrations.AddConstraint(
            "budgetversion",
            models.UniqueConstraint(condition=Q(state="active"), fields=("budget",),
                                    name="uq_bpp_budget_one_active")),
        migrations.AddConstraint(
            "budgetversion",
            models.UniqueConstraint(condition=Q(state="draft"), fields=("budget",),
                                    name="uq_bpp_budget_one_draft")),
        migrations.AlterField(
            "purchaserequest", "status",
            models.CharField(choices=[("draft", "Черновик"), ("in_approval", "На согласовании"),
                                      ("approved", "Утверждена"), ("rework", "На доработке"),
                                      ("rejected", "Отклонена"), ("cancelled", "Отменена"),
                                      ("closed", "Закрыта")],
                             default="draft", max_length=16)),
        migrations.RunPython(forward_status, backward_status),
        migrations.AddField(
            "purchaserequest", "rework_comment",
            models.TextField(blank=True, default="")),
    ]
