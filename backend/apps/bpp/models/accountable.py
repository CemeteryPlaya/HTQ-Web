"""Подотчётные средства: заявка и авансовые отчёты (задача B4.1, Q-B07).

Перенос ``contracts.AccountableFundsRequest`` / ``AdvanceReport`` в модуль с
прежней логикой: деньги закрепляются за автором заявки, бухгалтер отмечает
выдачу, дальше автор отчитывается авансовыми отчётами, и когда одобренные
отчёты покрыли сумму — заявка закрыта. Источник средств — не строка
годового бюджета, а статья бюджета проекта (D-06): проект и статья, как у
заявки на закупку.

Резерв: заявка занимает свою сумму со статуса «На согласовании» и дальше, в
том числе закрытая (выданные деньги в бюджет не возвращаются) — отдельное
слагаемое «Задействовано» (CALC-002, ``services/budget/committed.py``).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.signoff import interface as signoff

from .core import VersionedModel

__all__ = ["AccountableFundsRequest", "AccountableStatus", "AdvanceReport"]


class AccountableStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    ON_REVIEW = "on_review", "На согласовании"
    AWAITING_ACCOUNTING = "awaiting_accounting", "Ожидает выдачи бухгалтерией"
    AWAITING_REPORT = "awaiting_report", "Ожидает авансовый отчёт"
    CLOSED = "closed", "Закрыта"


class AccountableFundsRequest(signoff.Approvable, VersionedModel):
    SIGNOFF_SUBJECT_TYPE = "bpp.accountable_funds_request"

    number = models.CharField(max_length=32)
    project_id = models.UUIDField()
    article_id = models.UUIDField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="KZT")
    goal = models.TextField()
    status = models.CharField(max_length=24, choices=AccountableStatus.choices,
                              default=AccountableStatus.DRAFT)
    # Подотчётное лицо — автор заявки.
    accountable_user_id = models.IntegerField()
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.IntegerField(null=True, blank=True)
    is_migrated = models.BooleanField(default=False, db_default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["number"], name="uq_bpp_accountable_number"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="ck_bpp_accountable_amount"),
        ]
        indexes = [
            models.Index(fields=["project_id", "article_id", "status"],
                         name="ix_bpp_accountable_line"),
            models.Index(fields=["accountable_user_id", "status"],
                         name="ix_bpp_accountable_user"),
        ]
        verbose_name = "Заявка на подотчётные средства"
        verbose_name_plural = "Заявки на подотчётные средства"

    def __str__(self) -> str:
        return self.number


class AdvanceReport(signoff.Approvable, VersionedModel):
    """Одна подтверждающая трата. Остаток заявки уменьшают только одобренные
    отчёты; отчёт на согласовании держит свою сумму, чтобы два отчёта не
    съели один остаток."""

    SIGNOFF_SUBJECT_TYPE = "bpp.advance_report"

    request = models.ForeignKey(AccountableFundsRequest, on_delete=models.PROTECT,
                                related_name="reports")
    expense_name = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="ck_bpp_advance_amount"),
        ]
        ordering = ("created_at",)
        verbose_name = "Авансовый отчёт"
        verbose_name_plural = "Авансовые отчёты"

    def __str__(self) -> str:
        return f"{self.expense_name} ({self.amount})"
