"""Бюджет проекта: лимиты по статьям с версиями (ТЗ §06, §15.1, задача B2.1).

Один бюджет на проект на весь срок (D-06, BR-001). Лимиты живут в версиях:
черновик бюджета — версия 1 в статусе ``draft``; «Утвердить» делает её
``active``. Корректировка копирует строки действующей версии в новый
``draft`` с номером N+1 — пока он не утверждён, остатки считаются по
действующей версии (ТЗ §13.1 п.18), а после утверждения версия N уходит в
``archived`` и остаётся снимком во вкладке «Версии».

Проект и статья — ссылки на соседние аппки (``project``, ``refdata``)
строкой UUID, без FK: межаппный FK запрещён (CLAUDE.md).
"""

from __future__ import annotations

from django.db import models
from django.db.models import F, Q

from .core import BppModel, VersionedModel

__all__ = ["Budget", "BudgetLine", "BudgetStatus", "BudgetVersion", "BudgetVersionStatus"]


class BudgetStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    APPROVED = "approved", "Утверждён"
    CLOSED = "closed", "Закрыт"


class BudgetVersionStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    ACTIVE = "active", "Действующая"
    ARCHIVED = "archived", "Архивная"


class Budget(VersionedModel):
    project_id = models.UUIDField()
    number = models.CharField(max_length=48)
    currency = models.CharField(max_length=3, default="KZT")
    status = models.CharField(max_length=16, choices=BudgetStatus.choices,
                              default=BudgetStatus.DRAFT)
    # Действующая версия — та, по которой считаются остатки. Пуста до
    # первого утверждения.
    active_version = models.ForeignKey("BudgetVersion", null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="+")
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    # Комментарий последнего закрытия или повторного открытия.
    status_comment = models.TextField(default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project_id"], name="uq_bpp_budget_project"),
            models.UniqueConstraint(fields=["number"], name="uq_bpp_budget_number"),
            models.CheckConstraint(
                condition=Q(date_from__isnull=True) | Q(date_to__isnull=True)
                | Q(date_to__gte=F("date_from")),
                name="ck_bpp_budget_period"),
        ]
        verbose_name = "Бюджет"
        verbose_name_plural = "Бюджеты"

    def __str__(self) -> str:
        return self.number


class BudgetVersion(BppModel):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="versions")
    version_no = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=BudgetVersionStatus.choices,
                              default=BudgetVersionStatus.DRAFT)
    # Комментарий корректировки (≥ 10 символов); у версии 1 пуст.
    comment = models.TextField(default="", blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.IntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["budget", "version_no"],
                                    name="uq_bpp_budget_version_no"),
            # Один черновик на бюджет: вторая корректировка при открытой первой
            # невозможна и на уровне БД.
            models.UniqueConstraint(fields=["budget"], condition=Q(status="draft"),
                                    name="uq_bpp_budget_one_draft"),
        ]
        ordering = ("version_no",)
        verbose_name = "Версия бюджета"
        verbose_name_plural = "Версии бюджета"


class BudgetLine(BppModel):
    version = models.ForeignKey(BudgetVersion, on_delete=models.CASCADE, related_name="lines")
    article_id = models.UUIDField()
    limit_amount = models.DecimalField(max_digits=18, decimal_places=2)
    comment = models.CharField(max_length=255, default="", blank=True)
    # Порядок строк в форме: по нему BR-002 называет «строку 4».
    position = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["version", "article_id"],
                                    name="uq_bpp_budget_line_article"),
            models.CheckConstraint(condition=Q(limit_amount__gte=0),
                                   name="ck_bpp_budget_line_limit"),
        ]
        ordering = ("position", "created_at")
        verbose_name = "Строка бюджета"
        verbose_name_plural = "Строки бюджета"
