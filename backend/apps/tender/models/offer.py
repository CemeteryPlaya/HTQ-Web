"""Предложение поставщика (T3.3; план этапа 3, §2 T3.3; мастер-план §3.2).

Поставщик работает на портале по ссылке приглашения: у приглашения один
ЧЕРНОВИК (частичный уникальный индекс) и отправленные версии отдельными
строками — ``number`` 1, 2, … (номер отправки; у черновика пусто). Повторная
отправка переводит прежнюю версию в «Заменено», отзыв — в «Отозвано».
Предложенная схема оплаты — ``PaymentScheme(offer=…)`` по шаблонам 1–3.

Строки — по позициям заявки (``TenderRequestItem``); доставка и СМР — по
строке ``OfferExtra`` на вид, если тендер их запросил.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from .core import TenderModel, VersionedModel
from .request import TenderRequestItem
from .supplier import Invitation

__all__ = ["ExtraKind", "Offer", "OfferExtra", "OfferLine", "OfferStatus"]


class OfferStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    SUBMITTED = "submitted", "Отправлено"
    REPLACED = "replaced", "Заменено"
    WITHDRAWN = "withdrawn", "Отозвано"


class ExtraKind(models.TextChoices):
    DELIVERY = "delivery", "Доставка"
    WORKS = "works", "СМР"


class Offer(VersionedModel):
    invitation = models.ForeignKey(Invitation, on_delete=models.CASCADE,
                                   related_name="offers")
    number = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=OfferStatus.choices,
                              default=OfferStatus.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    currency_code = models.CharField(max_length=3, default="KZT")
    with_vat = models.BooleanField(default=True, db_default=True)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    delivery_cost = models.DecimalField(max_digits=18, decimal_places=2, null=True,
                                        blank=True)
    delivery_included = models.BooleanField(default=False, db_default=False)
    works_cost = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    works_note = models.TextField(default="", blank=True)
    valid_until = models.DateField(null=True, blank=True)
    extra_terms = models.TextField(default="", blank=True)
    # Реквизиты поставщика: name, country_code, reg_number, is_vat_payer,
    # contact_name, phone, email. У контрагента БЗО — копия карточки (правка
    # с портала не принимается), у потенциального поставщика — ввод.
    requisites = models.JSONField(default=dict, blank=True)
    pd_consent_at = models.DateTimeField(null=True, blank=True)
    declined_reason = models.TextField(default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["invitation"], name="uq_tender_offer_draft",
                                    condition=Q(status="draft")),
            models.UniqueConstraint(fields=["invitation", "number"],
                                    name="uq_tender_offer_number",
                                    condition=Q(number__isnull=False)),
            models.CheckConstraint(
                condition=Q(delivery_cost__isnull=True) | Q(delivery_cost__gte=0),
                name="ck_tender_offer_delivery_cost"),
            models.CheckConstraint(condition=Q(works_cost__isnull=True) | Q(works_cost__gte=0),
                                   name="ck_tender_offer_works_cost"),
        ]
        ordering = ("created_at",)
        verbose_name = "Предложение поставщика"
        verbose_name_plural = "Предложения поставщиков"


class OfferLine(TenderModel):
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(TenderRequestItem, on_delete=models.PROTECT,
                             related_name="offer_lines")
    participates = models.BooleanField(default=True, db_default=True)
    price = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    qty = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    is_analog = models.BooleanField(default=False, db_default=False)
    analog_note = models.TextField(default="", blank=True)
    comment = models.TextField(default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["offer", "item"], name="uq_tender_offer_line"),
            models.CheckConstraint(condition=Q(price__isnull=True) | Q(price__gt=0),
                                   name="ck_tender_offer_line_price"),
            models.CheckConstraint(condition=Q(qty__isnull=True) | Q(qty__gt=0),
                                   name="ck_tender_offer_line_qty"),
        ]
        verbose_name = "Строка предложения"
        verbose_name_plural = "Строки предложения"


class OfferExtra(TenderModel):
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="extras")
    kind = models.CharField(max_length=8, choices=ExtraKind.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    included_in_price = models.BooleanField(default=False, db_default=False)
    note = models.TextField(default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["offer", "kind"], name="uq_tender_offer_extra"),
            models.CheckConstraint(condition=Q(amount__isnull=True) | Q(amount__gte=0),
                                   name="ck_tender_offer_extra_amount"),
        ]
        verbose_name = "Доставка / СМР предложения"
        verbose_name_plural = "Доставка / СМР предложений"
