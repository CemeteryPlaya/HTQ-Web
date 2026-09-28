"""Договор и его позиции (ТЗ §09, §15.3, задача B3.1).

Как у заявки, статусов две оси (Q-C08): ``status`` — жизненный цикл
договора, который видит пользователь; ``approval_state`` — согласование,
его ведёт ``signoff`` (примесь ``Approvable``). ``status`` меняют сервисы
договора и колбэки согласования (``approval_hooks``).

Резерв бюджета не хранится: позиции закрытого договора «На согласовании» и
«Действует» — слагаемое «Задействовано» (CALC-002, ``services/budget/
committed.py``). Открытый договор бюджет не занимает — его занимают счета
(D-09).

Допсоглашение — договор с ``parent_agreement`` (D-18): та же форма, свой
маршрут (область ``supplementary``). Его сумма и позиции — ПРИРОСТ к
родителю: сумма договора для остатка (CALC-009) — сумма родителя плюс
утверждённые допсоглашения (``services/agreements/read.py``).
"""

from __future__ import annotations

from django.db import models
from django.db.models import F, Q

from apps.signoff import interface as signoff

from .core import VersionedModel
from .counterparties import Counterparty
from .requests import PurchaseRequestItem

__all__ = ["Agreement", "AgreementItem", "AgreementStatus", "AgreementType", "VatSource"]


class AgreementType(models.TextChoices):
    WORKS = "works", "Работы и услуги"
    GOODS = "goods", "ТМЦ"


class AgreementStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    ON_REVIEW = "on_review", "На согласовании"
    ACTIVE = "active", "Действует"
    REWORK = "rework", "На доработке"
    REJECTED = "rejected", "Отклонён"
    FULFILLED = "fulfilled", "Исполнен"
    TERMINATED = "terminated", "Расторгнут"
    REPLACED = "replaced", "Заменён альтернативой"


class VatSource(models.TextChoices):
    REFDATA = "refdata", "Справочник"
    DEFAULT = "default", "По умолчанию (16%)"
    MANUAL = "manual", "Вручную"


class Agreement(signoff.Approvable, VersionedModel):
    SIGNOFF_SUBJECT_TYPE = "bpp.agreement"

    number = models.CharField(max_length=32)
    ext_number = models.CharField(max_length=50, default="", blank=True)
    ext_date = models.DateField(null=True, blank=True)
    name = models.CharField(max_length=500, default="", blank=True)
    project_id = models.UUIDField()
    article_id = models.UUIDField()
    counterparty = models.ForeignKey(Counterparty, on_delete=models.PROTECT,
                                     related_name="agreements", null=True, blank=True)
    agreement_type = models.CharField(max_length=8, choices=AgreementType.choices,
                                      default="", blank=True)
    is_open = models.BooleanField(default=False, db_default=False)
    # null — у открытого договора; у допсоглашения — прирост (может быть 0).
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    currency_code = models.CharField(max_length=3, default="KZT")
    with_vat = models.BooleanField(default=True, db_default=True)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    vat_source = models.CharField(max_length=8, choices=VatSource.choices, default="",
                                  blank=True)
    vat_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=AgreementStatus.choices,
                              default=AgreementStatus.DRAFT)
    status_comment = models.TextField(default="", blank=True)
    rework_comment = models.TextField(default="", blank=True)
    author_id = models.IntegerField()
    initiator_role = models.CharField(max_length=8, default="", blank=True)
    parent_agreement = models.ForeignKey("self", on_delete=models.PROTECT, null=True,
                                         blank=True, related_name="supplements")
    # Лимит альтернативных предложений (A5.1, ТЗ §12.1): 3 по умолчанию.
    alt_limit = models.PositiveSmallIntegerField(default=3, db_default=3)
    # Непроверенного контрагента автор подтвердил при отправке (D-20).
    counterparty_confirmed = models.BooleanField(default=False, db_default=False)
    is_migrated = models.BooleanField(default=False, db_default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["number"], name="uq_bpp_agreement_number"),
            # BR-032: номер и дата по документу уникальны у контрагента —
            # кроме отклонённых и заменённых альтернативой.
            models.UniqueConstraint(
                fields=["counterparty", "ext_number", "ext_date"],
                condition=~Q(status__in=["rejected", "replaced", "draft", "rework"]),
                name="uq_bpp_agreement_ext"),
            models.CheckConstraint(
                condition=Q(is_open=True) | Q(amount__isnull=False),
                name="ck_bpp_agreement_amount"),
            models.CheckConstraint(
                condition=Q(amount__isnull=True) | Q(amount__gte=0),
                name="ck_bpp_agreement_amount_nonneg"),
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(ext_date__isnull=True)
                | Q(valid_to__gte=F("ext_date")),
                name="ck_bpp_agreement_valid_to"),
        ]
        indexes = [
            models.Index(fields=["project_id", "article_id", "status"],
                         name="ix_bpp_agreement_line"),
            models.Index(fields=["author_id", "status"], name="ix_bpp_agreement_author"),
        ]
        verbose_name = "Договор"
        verbose_name_plural = "Договоры"

    def __str__(self) -> str:
        return self.number


class AgreementItem(VersionedModel):
    agreement = models.ForeignKey(Agreement, on_delete=models.CASCADE, related_name="items")
    request_item = models.ForeignKey(PurchaseRequestItem, on_delete=models.PROTECT,
                                     related_name="agreement_items")
    qty = models.DecimalField(max_digits=15, decimal_places=3)
    # null — у открытого договора (суммы позиций необязательны, ТЗ §9.3 п.2).
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["agreement", "request_item"],
                                    name="uq_bpp_agreement_item"),
            models.CheckConstraint(condition=Q(qty__gt=0), name="ck_bpp_agreement_item_qty"),
        ]
        verbose_name = "Позиция договора"
        verbose_name_plural = "Позиции договора"
