"""Передача в БЗО и приёмка (T5.5; спека этапа 5, §2, §3 T5.5).

- ``Handover`` — документ БЗО, созданный передачей выбора: по одному на
  поставщика × часть заявки (ЗЗ). Уникальность — идемпотентность ручки
  «Передать в БЗО» на стороне tender (в БЗО — ``tender_key`` документа).
- ``Receipt`` / ``ReceiptLine`` — приёмка товара или работ по выбору: дата,
  количество по строкам выбора (частичная допустима), сканы и фото — файлы
  владельца ``tender.receipt``, «оригиналы переданы в бухгалтерию» (дата,
  кому). Ошибочную приёмку отменяют датой, а не удаляют: на счёте БЗО дата
  приёмки пересчитывается по оставшимся.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from .award import Award
from .core import TenderModel, VersionedModel
from .supplier import Invitation
from .tender import Tender

__all__ = ["Handover", "Receipt", "ReceiptKind", "ReceiptLine"]


class Handover(TenderModel):
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name="handovers")
    invitation = models.ForeignKey(Invitation, on_delete=models.PROTECT,
                                   related_name="handovers")
    part_id = models.UUIDField()
    bpp_document_type = models.CharField(max_length=16)
    bpp_document_id = models.UUIDField()
    bpp_number = models.CharField(max_length=32, default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tender", "invitation", "part_id"],
                                    name="uq_tender_handover_part"),
        ]
        verbose_name = "Передача в БЗО"
        verbose_name_plural = "Передачи в БЗО"


class ReceiptKind(models.TextChoices):
    GOODS = "goods", "Товар получен"
    WORKS = "works", "Работы приняты"


class Receipt(VersionedModel):
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name="receipts")
    invitation = models.ForeignKey(Invitation, on_delete=models.PROTECT,
                                   related_name="receipts")
    received_at = models.DateField()
    kind = models.CharField(max_length=8, choices=ReceiptKind.choices, default=ReceiptKind.GOODS)
    comment = models.TextField(default="", blank=True)
    originals_at = models.DateField(null=True, blank=True)
    originals_to = models.CharField(max_length=255, default="", blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.IntegerField(null=True, blank=True)
    cancel_comment = models.TextField(default="", blank=True)

    class Meta:
        indexes = [models.Index(fields=["tender", "invitation"], name="ix_tender_receipt_inv")]
        verbose_name = "Приёмка"
        verbose_name_plural = "Приёмки"


class ReceiptLine(TenderModel):
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="lines")
    award = models.ForeignKey(Award, on_delete=models.PROTECT, related_name="receipt_lines")
    qty = models.DecimalField(max_digits=15, decimal_places=3)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(qty__gt=0), name="ck_tender_receipt_line_qty"),
            models.UniqueConstraint(fields=["receipt", "award"], name="uq_tender_receipt_award"),
        ]
        verbose_name = "Строка приёмки"
        verbose_name_plural = "Строки приёмки"
