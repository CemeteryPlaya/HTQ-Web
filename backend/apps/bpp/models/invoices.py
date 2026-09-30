"""Счёт на оплату — единый: без договора и по договору (ТЗ §10, §15.4, D-11;
задача B3.2).

Статусов две оси (Q-C08): ``status`` — жизненный цикл счёта; решение ФД —
одноэтапный маршрут ``signoff`` (D-12), его ведёт примесь ``Approvable``.
Действия бухгалтера — доменные операции, не этапы согласования.

Цепочка (мастер-план §2.5, D-13): Черновик → На рассмотрении ФД → К оплате /
Не к оплате / Возвращён на доработку → Оплачено частично → Оплачено → Ждёт
закрывающих → Документы предоставлены → Закрыт; финальные — «Отменён» и
«Заменён альтернативой». Закрывающие документы — только после оплаты (D-13).
Статус сверки с банком — отдельное поле, его пишет сверка A4.2.

Резерв бюджета не хранится: строки счетов от «На рассмотрении ФД», кроме
«Отменён» и «Не к оплате», — слагаемое «Задействовано» (CALC-002).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.signoff import interface as signoff

from .agreements import Agreement
from .core import VersionedModel
from .counterparties import Counterparty
from .requests import PurchaseRequestItem

__all__ = ["Invoice", "InvoiceBasis", "InvoiceLine", "InvoiceStatus", "PaymentMark",
           "RateSource", "ReconStatus"]


class InvoiceBasis(models.TextChoices):
    NO_CONTRACT = "no_contract", "Без договора"
    CONTRACT = "contract", "По договору"


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    UNDER_REVIEW = "under_review", "На рассмотрении ФД"
    RETURNED = "returned", "Возвращён на доработку"
    NOT_PAYABLE = "not_payable", "Не к оплате"
    TO_PAY = "to_pay", "К оплате"
    PARTIALLY_PAID = "partially_paid", "Оплачено частично"
    PAID = "paid", "Оплачено"
    AWAITING_DOCS = "awaiting_docs", "Ждёт закрывающих документов"
    DOCS_PROVIDED = "docs_provided", "Документы предоставлены"
    CLOSED = "closed", "Закрыт"
    CANCELLED = "cancelled", "Отменён"
    REPLACED = "replaced", "Заменён альтернативой"


class RateSource(models.TextChoices):
    KZT = "kzt", "Тенге"
    NBRK = "nbrk", "Курс НБРК"
    MANUAL = "manual", "Фактический курс"


class ReconStatus(models.TextChoices):
    """Статус сверки с банком (CALC-010) — пишет сверка A4.2."""
    NO_DATA = "no_data", "Нет данных банка"
    PARTIAL = "partial", "Оплачен частично"
    FULL = "full", "Оплачен полностью"
    OVERPAID = "overpaid", "Переплата"


class Invoice(signoff.Approvable, VersionedModel):
    SIGNOFF_SUBJECT_TYPE = "bpp.invoice"

    number = models.CharField(max_length=32)
    basis = models.CharField(max_length=16, choices=InvoiceBasis.choices,
                             default=InvoiceBasis.NO_CONTRACT)
    agreement = models.ForeignKey(Agreement, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="invoices")
    project_id = models.UUIDField()
    article_id = models.UUIDField()
    counterparty = models.ForeignKey(Counterparty, on_delete=models.PROTECT, null=True,
                                     blank=True, related_name="invoices")
    ext_number = models.CharField(max_length=50, default="", blank=True)
    ext_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency_code = models.CharField(max_length=3, default="KZT")
    # Курс к KZT (D-15): НБРК на дату счёта или фактический; сумма в KZT — CALC-012.
    rate = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    rate_source = models.CharField(max_length=8, choices=RateSource.choices, default="",
                                   blank=True)
    amount_kzt = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    with_vat = models.BooleanField(default=True, db_default=True)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    vat_source = models.CharField(max_length=8, default="", blank=True)
    vat_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    purchase_type = models.CharField(max_length=8, default="", blank=True)
    # Аванс (предоплата) — признак счёта (D-11).
    is_advance = models.BooleanField(default=False, db_default=False)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=InvoiceStatus.choices,
                              default=InvoiceStatus.DRAFT)
    status_comment = models.TextField(default="", blank=True)
    rework_comment = models.TextField(default="", blank=True)
    fd_decided_at = models.DateTimeField(null=True, blank=True)
    planned_pay_date = models.DateField(null=True, blank=True)
    # Закрывающие документы (D-13): ``{"avr": bool, "waybill": bool, "vat_invoice": bool}``.
    docs_required = models.JSONField(default=dict, blank=True)
    docs_requested_at = models.DateTimeField(null=True, blank=True)
    docs_comment = models.TextField(default="", blank=True)
    recon_status = models.CharField(max_length=10, choices=ReconStatus.choices,
                                    default=ReconStatus.NO_DATA, db_default=ReconStatus.NO_DATA)
    # Σ сопоставленных строк выписки — ведёт сверка A4.2 (``recalc_invoice``).
    paid_bank_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0,
                                           db_default=0)
    author_comment = models.TextField(default="", blank=True)
    author_id = models.IntegerField()
    initiator_role = models.CharField(max_length=8, default="", blank=True)
    # Непроверенного контрагента автор подтвердил при отправке (D-20).
    counterparty_confirmed = models.BooleanField(default=False, db_default=False)
    is_migrated = models.BooleanField(default=False, db_default=False)
    # Лимит альтернативных предложений (A5.1, ТЗ §12.1, D-S5-2): 3 по
    # умолчанию, как у договора; поднимает СН — автор счёта, не выше 10.
    alt_limit = models.PositiveSmallIntegerField(default=3, db_default=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["number"], name="uq_bpp_invoice_number"),
            # BR-045: номер и дата счёта контрагента уникальны среди действующих.
            models.UniqueConstraint(
                fields=["counterparty", "ext_number", "ext_date"],
                condition=~Q(status__in=["draft", "returned", "cancelled", "replaced",
                                         "not_payable"]),
                name="uq_bpp_invoice_ext"),
            models.CheckConstraint(condition=Q(amount__gte=0), name="ck_bpp_invoice_amount"),
            models.CheckConstraint(
                condition=(Q(basis="contract", agreement__isnull=False)
                           | Q(basis="no_contract", agreement__isnull=True)),
                name="ck_bpp_invoice_basis"),
        ]
        indexes = [
            models.Index(fields=["project_id", "article_id", "status"],
                         name="ix_bpp_invoice_line"),
            models.Index(fields=["author_id", "status"], name="ix_bpp_invoice_author"),
            models.Index(fields=["status", "due_date"], name="ix_bpp_invoice_queue"),
        ]
        verbose_name = "Счёт на оплату"
        verbose_name_plural = "Счета на оплату"

    def __str__(self) -> str:
        return self.number


class InvoiceLine(VersionedModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    request_item = models.ForeignKey(PurchaseRequestItem, on_delete=models.PROTECT,
                                     related_name="invoice_lines")
    qty = models.DecimalField(max_digits=15, decimal_places=3)
    amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["invoice", "request_item"],
                                    name="uq_bpp_invoice_line"),
            models.CheckConstraint(condition=Q(qty__gt=0), name="ck_bpp_invoice_line_qty"),
            models.CheckConstraint(condition=Q(amount__gt=0),
                                   name="ck_bpp_invoice_line_amount"),
        ]
        verbose_name = "Строка счёта"
        verbose_name_plural = "Строки счёта"


class PaymentMark(VersionedModel):
    """Отметка оплаты бухгалтера (ТЗ §10.2): частичная оплата и транши — несколько
    отметок по одному счёту (Q-B24). Σ неотменённых ≤ суммы счёта (BR-052,
    сервис под блокировкой счёта). Отмена — пометкой, не удалением."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    pay_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    pp_number = models.CharField(max_length=50, default="", blank=True)
    # Фактический курс транзакции (D-15), у счёта в валюте.
    rate = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    marked_by_id = models.IntegerField()
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by_id = models.IntegerField(null=True, blank=True)
    cancel_comment = models.TextField(default="", blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="ck_bpp_payment_amount"),
        ]
        verbose_name = "Отметка оплаты"
        verbose_name_plural = "Отметки оплаты"
