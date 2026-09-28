"""Заявка на закупку и её позиции (ТЗ §07, §15.2, задача B2.2).

Статусов две оси (Q-C08): ``status`` — жизненный цикл заявки, который видит
пользователь; ``approval_state`` — состояние согласования, его ведёт
``signoff`` (примесь ``Approvable``). ``status`` меняют только сервисы
заявки и колбэки согласования (``approval_hooks``).

Резерв бюджета (BR-012) не хранится: он следует из статуса заявки и
позиций, «Задействовано» считается на лету (D-08, ``services/budget/
committed.py``).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.signoff import interface as signoff

from .core import VersionedModel

__all__ = [
    "InitiatorRole", "ItemStatus", "PurchaseRequest", "PurchaseRequestItem",
    "PurchaseType", "RequestStatus",
]


class InitiatorRole(models.TextChoices):
    SN = "sn", "Снабженец"
    PM = "pm", "Руководитель проекта"


class PurchaseType(models.TextChoices):
    GOODS = "goods", "ТМЦ"
    WORKS = "works", "Работы и услуги"


class RequestStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    IN_APPROVAL = "in_approval", "На согласовании"
    APPROVED = "approved", "Утверждена"
    REWORK = "rework", "На доработке"
    REJECTED = "rejected", "Отклонена"
    CANCELLED = "cancelled", "Отменена"
    CLOSED = "closed", "Закрыта"


class ItemStatus(models.TextChoices):
    OPEN = "open", "Открыта"
    PARTIALLY_CLOSED = "partially_closed", "Частично закрыта"
    CLOSED = "closed", "Закрыта"
    ANNULLED = "annulled", "Аннулирована"


class PurchaseRequest(signoff.Approvable, VersionedModel):
    SIGNOFF_SUBJECT_TYPE = "bpp.purchase_request"

    number = models.CharField(max_length=32)
    author_id = models.IntegerField()
    initiator_role = models.CharField(max_length=8, choices=InitiatorRole.choices)
    project_id = models.UUIDField()
    article_id = models.UUIDField(null=True, blank=True)
    purchase_type = models.CharField(max_length=8, choices=PurchaseType.choices,
                                     default="", blank=True)
    need_date = models.DateField(null=True, blank=True)
    justification = models.TextField(default="", blank=True)
    currency_code = models.CharField(max_length=3, default="KZT")
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=RequestStatus.choices,
                              default=RequestStatus.DRAFT)
    # Комментарий последнего возврата согласующим — жёлтая плашка формы (ТЗ
    # §7.6 п.6); пишет колбэк ``on_rework``.
    rework_comment = models.TextField(default="", blank=True)
    # Комментарий отмены или закрытия остатка.
    status_comment = models.TextField(default="", blank=True)
    # Техническая заявка переноса из contracts (B6.1, Q-D06): не видна в
    # Плане закупок, реестрах и статистике.
    is_migrated = models.BooleanField(default=False, db_default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["number"], name="uq_bpp_request_number"),
        ]
        indexes = [
            models.Index(fields=["project_id", "article_id", "status"],
                         name="ix_bpp_request_line"),
            models.Index(fields=["author_id", "status"], name="ix_bpp_request_author"),
        ]
        verbose_name = "Заявка на закупку"
        verbose_name_plural = "Заявки на закупку"

    def __str__(self) -> str:
        return self.number


class PurchaseRequestItem(VersionedModel):
    request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE,
                                related_name="items")
    line_no = models.PositiveIntegerField()
    sys_number = models.CharField(max_length=40)
    name = models.CharField(max_length=500)
    specs = models.TextField(default="", blank=True)
    uom_id = models.UUIDField()
    qty = models.DecimalField(max_digits=15, decimal_places=3)
    price = models.DecimalField(max_digits=18, decimal_places=2)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    need_date = models.DateField()
    status = models.CharField(max_length=20, choices=ItemStatus.choices,
                              default=ItemStatus.OPEN)
    # Исполнитель позиции в Плане закупок: по умолчанию автор заявки,
    # АДМ может переназначить (B2.3).
    executor_id = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sys_number"], name="uq_bpp_request_item_sys"),
            models.UniqueConstraint(fields=["request", "line_no"],
                                    name="uq_bpp_request_item_line"),
            models.CheckConstraint(condition=Q(qty__gt=0), name="ck_bpp_request_item_qty"),
            models.CheckConstraint(condition=Q(price__gt=0),
                                   name="ck_bpp_request_item_price"),
            models.CheckConstraint(condition=Q(amount__gt=0),
                                   name="ck_bpp_request_item_amount"),
        ]
        indexes = [models.Index(fields=["executor_id", "status"],
                                name="ix_bpp_request_item_exec")]
        ordering = ("line_no",)
        verbose_name = "Позиция заявки"
        verbose_name_plural = "Позиции заявок"

    def __str__(self) -> str:
        return self.sys_number
