"""Выбор поставщиков (T5.2; спека этапа 5, §2, §3 T5.2).

Строка выбора — либо позиция предложения (``line``), либо его доставка или
СМР (``extra``): у доставки и СМР нет строки предложения, поэтому выбор
ссылается на ``OfferExtra`` (мастер-план §3.2, находка 15). У позиции — один
поставщик (S5-05): уникальность по строке предложения и по позиции держит
сервис, а БД — по строке и по ``OfferExtra``. ``part_id`` — часть заявки
(ЗЗ БЗО), куда уйдёт документ; суммы — к оплате в валюте предложения и в KZT
по курсу вскрытия (``amount_kzt`` пуст, если курса нет — такой выбор не
уходит на утверждение, ``E-TND-10``).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from .core import TenderModel
from .offer import Offer, OfferExtra, OfferLine
from .tender import Tender

__all__ = ["Award"]


class Award(TenderModel):
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name="awards")
    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name="awards")
    line = models.ForeignKey(OfferLine, on_delete=models.PROTECT, null=True, blank=True,
                             related_name="awards")
    extra = models.ForeignKey(OfferExtra, on_delete=models.PROTECT, null=True, blank=True,
                              related_name="awards")
    part_id = models.UUIDField()
    qty = models.DecimalField(max_digits=15, decimal_places=3)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    amount_kzt = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    plan_amount_kzt = models.DecimalField(max_digits=18, decimal_places=2)
    is_cheapest = models.BooleanField(default=True)
    comment = models.TextField(default="", blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(line__isnull=False, extra__isnull=True)
                           | Q(line__isnull=True, extra__isnull=False)),
                name="ck_tender_award_line_xor_extra"),
            models.UniqueConstraint(fields=["tender", "line"], name="uq_tender_award_line",
                                    condition=Q(line__isnull=False)),
            models.UniqueConstraint(fields=["tender", "extra"], name="uq_tender_award_extra",
                                    condition=Q(extra__isnull=False)),
            models.CheckConstraint(condition=Q(qty__gt=0), name="ck_tender_award_qty"),
        ]
        verbose_name = "Выбор поставщика"
        verbose_name_plural = "Выбор поставщиков"
