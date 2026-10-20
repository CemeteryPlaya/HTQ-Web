"""Заявка тендерного модуля (T1.1; план этапов 0–2, §3.1).

Заявка ведётся в tender (мастер-план, T-02): «Отправить на согласование»
(T1.3) режет её на части по паре «статья × вид закупки» и под каждой частью
заводит заявку на закупку (ЗЗ) в БЗО. Части рождаются только при отправке;
позиции доставки и СМР строками не хранятся — их собирает отправка из
плановых сумм шапки (T-04).

Ссылки на ``project``/``refdata``/``bpp`` — голые ``UUIDField`` без FK: между
аппками связь только через ``interface``.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from .core import TenderModel, VersionedModel

__all__ = [
    "InitiatorRole", "PartKind", "PurchaseType", "TenderRequest", "TenderRequestItem",
    "TenderRequestPart", "TenderRequestStatus",
]


class TenderRequestStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    IN_APPROVAL = "in_approval", "На согласовании"
    APPROVED = "approved", "Утверждена"
    REWORK = "rework", "На доработке"
    REJECTED = "rejected", "Отклонена"
    IN_TENDER = "in_tender", "В тендере"
    HANDED_OVER = "handed_over", "Передана в БЗО"
    CLOSED = "closed", "Закрыта"
    CANCELLED = "cancelled", "Отменена"


class InitiatorRole(models.TextChoices):
    """Роль БЗО, в которой подаются ЗЗ заявки (BR-010: группа статей роли)."""

    SN = "sn", "Снабженец"
    PM = "pm", "Руководитель проекта"


class PurchaseType(models.TextChoices):
    GOODS = "goods", "Товары"
    WORKS = "works", "Работы и услуги"


class PartKind(models.TextChoices):
    GOODS = "goods", "Основные позиции"
    DELIVERY = "delivery", "Доставка"
    WORKS = "works", "СМР"


class TenderRequest(VersionedModel):
    number = models.CharField(max_length=32)
    author_id = models.IntegerField()
    initiator_role = models.CharField(max_length=8, choices=InitiatorRole.choices)
    project_id = models.UUIDField()
    # Статья основных позиций; у позиции может быть своя (``item.article_id``).
    article_id = models.UUIDField(null=True, blank=True)
    purchase_type = models.CharField(max_length=8, choices=PurchaseType.choices,
                                     default=PurchaseType.GOODS)
    need_date = models.DateField(null=True, blank=True)
    delivery_address = models.TextField(default="", blank=True)
    # «Обоснование» уходит во все ЗЗ заявки — ≥ 10 символов при отправке (T-05).
    justification = models.TextField(default="", blank=True)
    needs_delivery = models.BooleanField(default=False, db_default=False)
    delivery_article_id = models.UUIDField(null=True, blank=True)
    # Плановые суммы доставки и СМР обязательны при отправке, если признак
    # включён (T-04): позиция ЗЗ без цены > 0 не создаётся.
    delivery_plan_amount = models.DecimalField(max_digits=18, decimal_places=2,
                                               null=True, blank=True)
    needs_works = models.BooleanField(default=False, db_default=False)
    works_scope = models.TextField(default="", blank=True)
    works_article_id = models.UUIDField(null=True, blank=True)
    works_plan_amount = models.DecimalField(max_digits=18, decimal_places=2,
                                            null=True, blank=True)
    allow_analogs = models.BooleanField(default=False, db_default=False)
    allow_partial = models.BooleanField(default=True, db_default=True)
    status = models.CharField(max_length=16, choices=TenderRequestStatus.choices,
                              default=TenderRequestStatus.DRAFT)
    status_comment = models.TextField(default="", blank=True)
    rework_comment = models.TextField(default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["number"], name="uq_tender_request_number"),
            models.CheckConstraint(
                condition=Q(delivery_plan_amount__isnull=True) | Q(delivery_plan_amount__gt=0),
                name="ck_tender_request_delivery_amount"),
            models.CheckConstraint(
                condition=Q(works_plan_amount__isnull=True) | Q(works_plan_amount__gt=0),
                name="ck_tender_request_works_amount"),
        ]
        indexes = [
            models.Index(fields=["author_id", "status"], name="ix_tender_request_author"),
            models.Index(fields=["project_id", "status"], name="ix_tender_request_project"),
        ]
        verbose_name = "Заявка (тендер)"
        verbose_name_plural = "Заявки (тендер)"

    def __str__(self) -> str:
        return self.number


class TenderRequestPart(TenderModel):
    """Одна ЗЗ в БЗО под заявкой: пара «статья × вид» (T-03). ``bpp_status`` —
    зеркало статуса ЗЗ, его пишет слушатель ``bpp.register_request_listener``
    (T-09); ``excluded_at`` — отклонённая часть исключена закупщиком (T-08)."""

    request = models.ForeignKey(TenderRequest, on_delete=models.CASCADE,
                                related_name="parts")
    kind = models.CharField(max_length=8, choices=PartKind.choices)
    article_id = models.UUIDField()
    purchase_type = models.CharField(max_length=8, choices=PurchaseType.choices)
    bpp_request_id = models.UUIDField(null=True, blank=True)
    bpp_number = models.CharField(max_length=32, default="", blank=True)
    bpp_status = models.CharField(max_length=16, default="", blank=True)
    excluded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "kind", "article_id"],
                                    name="uq_tender_request_part"),
        ]
        verbose_name = "Часть заявки (ЗЗ в БЗО)"
        verbose_name_plural = "Части заявки (ЗЗ в БЗО)"


class TenderRequestItem(TenderModel):
    """Основная позиция заявки. ``part`` назначает отправка; ``article_id``
    пустой — статья заявки."""

    request = models.ForeignKey(TenderRequest, on_delete=models.CASCADE,
                                related_name="items")
    part = models.ForeignKey(TenderRequestPart, on_delete=models.SET_NULL, null=True,
                             blank=True, related_name="items")
    line_no = models.PositiveIntegerField()
    name = models.CharField(max_length=500)
    specs = models.TextField(default="", blank=True)
    uom_id = models.UUIDField()
    qty = models.DecimalField(max_digits=15, decimal_places=3)
    plan_price = models.DecimalField(max_digits=18, decimal_places=2)
    # Пустая — дата потребности заявки (обязательна при отправке).
    need_date = models.DateField(null=True, blank=True)
    article_id = models.UUIDField(null=True, blank=True)
    bpp_request_item_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            # Отложенная: правка заявки перенумеровывает позиции на месте.
            models.UniqueConstraint(fields=["request", "line_no"],
                                    name="uq_tender_request_item_line",
                                    deferrable=models.Deferrable.DEFERRED),
            models.CheckConstraint(condition=Q(qty__gt=0), name="ck_tender_request_item_qty"),
            models.CheckConstraint(condition=Q(plan_price__gt=0),
                                   name="ck_tender_request_item_price"),
        ]
        ordering = ("line_no",)
        verbose_name = "Позиция заявки (тендер)"
        verbose_name_plural = "Позиции заявки (тендер)"
