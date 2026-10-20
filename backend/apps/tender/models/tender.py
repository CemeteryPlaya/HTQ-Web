"""Тендер и желаемая схема оплаты (T2.1; план этапов 0–2, §4.1).

Тендер объявляется по утверждённой заявке; у заявки не больше одного
АКТИВНОГО тендера — это держит частичный уникальный индекс, а не только код
(две параллельные «Объявить тендер» иначе прошли бы обе). Схема оплаты —
шаблоны 1–3 ТЗ (``services/tenders/schemes.py``); модель этапов
(``PaymentStage``) заложена сразу и под схему 4 (EPC, после пилота, T-15).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from .core import TenderModel, VersionedModel
from .request import TenderRequest

__all__ = [
    "ACTIVE_TENDER_STATUSES", "PaymentKind", "PaymentScheme", "PaymentStage",
    "PaymentTrigger", "Tender", "TenderStatus",
]


class TenderStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    INTAKE = "intake", "Приём предложений"
    OPENED = "opened", "Вскрыт"
    ON_APPROVAL = "on_approval", "На утверждении"
    AWARDED = "awarded", "Выбор утверждён"
    HANDED_OVER = "handed_over", "Документы в БЗО"
    DELIVERY = "delivery", "Поставка"
    CLOSED = "closed", "Закрыт"
    CANCELLED = "cancelled", "Отменён"
    FAILED = "failed", "Не состоялся"
    REWORK = "rework", "Возвращён на доработку"


#: Завершённые тендеры; все остальные — активные (держат заявку).
FINISHED_TENDER_STATUSES = (TenderStatus.CANCELLED, TenderStatus.FAILED, TenderStatus.CLOSED)
ACTIVE_TENDER_STATUSES = tuple(s for s in TenderStatus if s not in FINISHED_TENDER_STATUSES)


class Tender(VersionedModel):
    number = models.CharField(max_length=32)
    request = models.ForeignKey(TenderRequest, on_delete=models.PROTECT,
                                related_name="tenders")
    author_id = models.IntegerField()
    # Пусто у черновика; публикация требует срок в будущем.
    deadline_at = models.DateTimeField(null=True, blank=True)
    currency_code = models.CharField(max_length=3, default="KZT")
    delivery_terms = models.TextField(default="", blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    round = models.PositiveSmallIntegerField(default=1, db_default=1)
    parent_tender = models.ForeignKey("self", on_delete=models.PROTECT, null=True,
                                      blank=True, related_name="rounds")
    # Пусто — проверяют держатели должности ТД (T-11); иначе — выбранный
    # закупщиком пользователь с ролью ``tender-quality``.
    quality_reviewer_user_id = models.IntegerField(null=True, blank=True)
    cancel_reason = models.TextField(default="", blank=True)
    status = models.CharField(max_length=16, choices=TenderStatus.choices,
                              default=TenderStatus.DRAFT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["number"], name="uq_tender_number"),
            # Одна заявка — один активный тендер (E-TND-01).
            models.UniqueConstraint(
                fields=["request"], name="uq_tender_active_request",
                condition=~Q(status__in=[s.value for s in FINISHED_TENDER_STATUSES])),
        ]
        indexes = [models.Index(fields=["author_id", "status"], name="ix_tender_author")]
        verbose_name = "Тендер"
        verbose_name_plural = "Тендеры"

    def __str__(self) -> str:
        return self.number


class PaymentKind(models.TextChoices):
    PREPAY = "prepay", "Предоплата 100%"
    ADVANCE = "advance", "Аванс и остаток после поставки"
    POSTPAY = "postpay", "Оплата после поставки"
    STAGED = "staged", "Поэтапная оплата"


class PaymentTrigger(models.TextChoices):
    BEFORE_SHIPMENT = "before_shipment", "До отгрузки"
    ON_RECEIPT = "on_receipt", "После приёмки"
    AFTER_WORKS = "after_works", "После выполнения работ"
    AFTER_WARRANTY = "after_warranty", "После гарантийного срока"


class PaymentScheme(TenderModel):
    """Схема оплаты: желаемая у тендера (одна), у предложения поставщика —
    этап 3 (тогда ``tender`` пуст и схему держит предложение)."""

    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, null=True, blank=True,
                               related_name="payment_schemes")
    # Схема, предложенная поставщиком (T3.3): у неё ``tender`` пуст.
    offer = models.ForeignKey("tender.Offer", on_delete=models.CASCADE, null=True,
                              blank=True, related_name="payment_schemes")
    kind = models.CharField(max_length=8, choices=PaymentKind.choices)
    postpay_days = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tender"], name="uq_tender_payment_scheme",
                                    condition=Q(tender__isnull=False)),
            models.UniqueConstraint(fields=["offer"], name="uq_tender_offer_payment_scheme",
                                    condition=Q(offer__isnull=False)),
        ]
        verbose_name = "Схема оплаты"
        verbose_name_plural = "Схемы оплаты"


class PaymentStage(TenderModel):
    scheme = models.ForeignKey(PaymentScheme, on_delete=models.CASCADE,
                               related_name="stages")
    order = models.PositiveSmallIntegerField()
    trigger = models.CharField(max_length=16, choices=PaymentTrigger.choices)
    pct = models.DecimalField(max_digits=5, decimal_places=2)
    days = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["scheme", "order"], name="uq_tender_payment_stage"),
            models.CheckConstraint(condition=Q(pct__gt=0) & Q(pct__lte=100),
                                   name="ck_tender_payment_stage_pct"),
        ]
        ordering = ("order",)
        verbose_name = "Этап оплаты"
        verbose_name_plural = "Этапы оплаты"
