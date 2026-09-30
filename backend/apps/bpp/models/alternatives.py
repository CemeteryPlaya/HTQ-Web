"""Альтернативные предложения снабженца и KPI снабжения (ТЗ §12, A5.1/A5.2;
план этапа 5 A, задача 1).

**Альтернативное предложение (АП)** ``АП-ГГГГ-NNNNNN`` — другой контрагент
на часть или все позиции исходного документа: счёта без договора или
договора (``source_type``/``source_id`` — ссылка без FK, как у журнала: АП
не держит исходный документ от удаления и не лезет в его таблицу).

- Цена позиции — за единицу, с НДС, если он есть (D-S5-3): так же, как
  суммы строк счёта и договора. Количество равно исходному.
- ``source_amount_kzt`` — исходная часть: Σ сумм выбранных позиций
  исходного документа в KZT по его курсу (D-S5-3, D-S5-4). Экономия —
  исходная часть − сумма АП (CALC-013, ``services/alternatives/calc.py``);
  отрицательная — удорожание.
- Действующие АП — «Черновик», «Подано», «Выбрано» (D-S5-2): среди них
  контрагент уникален в пределах документа (BR-091, частичный индекс
  ниже). Лимиты «на документ» и «на автора» — кодом под блокировкой
  исходного документа, а не БД: у ПМ до трёх АП на документ.
- ``project_id``/``article_id`` — снимок проекта и статьи исходного
  документа; заполняет ``offers.create`` (задача 2) при создании АП. По
  ним R-01 (задача 5) фильтрует «подано» по проекту и статье без
  подзапросов к счетам и договорам. Пусты только у строк, созданных до
  поля (expand), — такие в фильтр по проекту не попадают.
- ``result_type``/``result_id`` — новый документ по выбранной АП; пишет
  выбор (B5.1).

**Запись KPI** — одна на АП (BR-096, ``OneToOneField``): снимок выбора
(покупатель, исходный и новый документ, суммы, экономия) и статус
«Предварительный → Подтверждён / Аннулирован» по статусу нового документа
(D-S5-7). Ведёт её ``services/alternatives/kpi.py``.

Журнал обоих типов (``bpp.alternativeoffer``, ``bpp.kpirecord``) читается
с проверкой доступа — регистрация в ``services/alternatives/file_owner.py``
(стартовый крючок подмодуля): модели сервисов не импортируют.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from .agreements import VatSource
from .core import VersionedModel
from .counterparties import Counterparty
from .requests import InitiatorRole, PurchaseRequestItem

__all__ = [
    "AlternativeOffer",
    "AlternativeOfferLine",
    "KpiRecord",
    "KpiStatus",
    "LIVE_OFFER_STATUSES",
    "OfferSource",
    "OfferStatus",
    "PaymentTerms",
]


class OfferSource(models.TextChoices):
    """Вид исходного документа АП (ТЗ §12.1): счёт без договора или договор."""

    INVOICE = "invoice", "Счёт на оплату"
    AGREEMENT = "agreement", "Договор"


class OfferStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    SUBMITTED = "submitted", "Подано"
    SELECTED = "selected", "Выбрано"
    NOT_SELECTED = "not_selected", "Не выбрано"
    WITHDRAWN = "withdrawn", "Отозвано"
    ANNULLED = "annulled", "Аннулировано"


#: Действующие АП (D-S5-2): входят в лимиты и в уникальность контрагента.
LIVE_OFFER_STATUSES = (OfferStatus.DRAFT, OfferStatus.SUBMITTED, OfferStatus.SELECTED)


class PaymentTerms(models.TextChoices):
    FULL_PREPAY = "full_prepay", "Полная предоплата"
    PARTIAL_PREPAY = "partial_prepay", "Частичная предоплата"
    POSTPAY = "postpay", "Постоплата"


class AlternativeOffer(VersionedModel):
    number = models.CharField(max_length=32)
    source_type = models.CharField(max_length=16, choices=OfferSource.choices)
    source_id = models.UUIDField()
    # Снимок проекта и статьи исходного документа — пишет ``offers.create``
    # (задача 2); фильтры R-01 по «подано» (задача 5).
    project_id = models.UUIDField(null=True, blank=True)
    article_id = models.UUIDField(null=True, blank=True)
    author_id = models.IntegerField()
    author_role = models.CharField(max_length=8, choices=InitiatorRole.choices)
    # BR-092: АП к своему же документу — допустима, но видна в KPI отдельно.
    own_document = models.BooleanField(default=False, db_default=False)
    # Пусто — у черновика, где контрагента ещё не выбрали.
    counterparty = models.ForeignKey(Counterparty, on_delete=models.PROTECT, null=True,
                                     blank=True, related_name="alternative_offers")
    currency_code = models.CharField(max_length=3, default="KZT", db_default="KZT")
    # Курс к KZT на дату подачи (D-S5-4); у KZT — 1.
    rate = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0, db_default=0)
    # Пусто, пока курса нет: подача без него отклоняется (E-REF-05).
    amount_kzt = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    with_vat = models.BooleanField(default=True, db_default=True)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    vat_source = models.CharField(max_length=8, choices=VatSource.choices, default="",
                                  db_default="", blank=True)
    vat_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    # Исходная часть в KZT (D-S5-3) и экономия CALC-013 — пересчитываются
    # при каждой правке черновика. Процент — ``Decimal(12,2)``: опечатка в
    # цене (×10 000 к исходной) не должна ронять правку переполнением столбца;
    # за пределами столбца сервис отвечает 422, а не БД — 500.
    source_amount_kzt = models.DecimalField(max_digits=18, decimal_places=2, null=True,
                                            blank=True)
    saving_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    saving_pct = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=16, choices=PaymentTerms.choices, default="",
                                     db_default="", blank=True)
    payment_terms_note = models.TextField(default="", db_default="", blank=True)
    justification = models.TextField(default="", db_default="", blank=True)
    status = models.CharField(max_length=16, choices=OfferStatus.choices,
                              default=OfferStatus.DRAFT, db_default=OfferStatus.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_by_id = models.IntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_comment = models.TextField(default="", db_default="", blank=True)
    # Новый документ по выбранной АП — пишет выбор (B5.1).
    result_type = models.CharField(max_length=16, choices=OfferSource.choices, default="",
                                   db_default="", blank=True)
    result_id = models.UUIDField(null=True, blank=True)
    # Почему «Не выбрано» или «Аннулировано» (``lifecycle.close_for_source``).
    closed_reason = models.TextField(default="", db_default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["number"], name="uq_bpp_altoffer_number"),
            # BR-091: один контрагент — одна действующая АП к документу.
            models.UniqueConstraint(
                fields=["source_type", "source_id", "counterparty"],
                condition=Q(status__in=[s.value for s in LIVE_OFFER_STATUSES]),
                name="uq_bpp_altoffer_counterparty"),
        ]
        indexes = [
            models.Index(fields=["source_type", "source_id", "status"],
                         name="ix_bpp_altoffer_source"),
            models.Index(fields=["author_id", "status"], name="ix_bpp_altoffer_author"),
            models.Index(fields=["project_id", "article_id"], name="ix_bpp_altoffer_line"),
        ]
        ordering = ("-created_at",)
        verbose_name = "Альтернативное предложение"
        verbose_name_plural = "Альтернативные предложения"

    def __str__(self) -> str:
        return self.number


class AlternativeOfferLine(VersionedModel):
    """Позиция АП — одна позиция исходного документа (строка счёта или
    позиция договора, ``source_line_id``) с ценой альтернативы.

    У черновика цена пуста: при создании АП получает все позиции документа
    без цен (задача 2), автор заполняет цены и убирает лишние позиции.
    """

    offer = models.ForeignKey(AlternativeOffer, on_delete=models.CASCADE, related_name="lines")
    source_line_id = models.UUIDField()
    request_item = models.ForeignKey(PurchaseRequestItem, on_delete=models.PROTECT,
                                     related_name="alternative_offer_lines")
    qty = models.DecimalField(max_digits=15, decimal_places=3)
    # Цена позиции исходного документа за единицу (``calc.source_price``).
    source_price = models.DecimalField(max_digits=18, decimal_places=2)
    price = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["offer", "source_line_id"],
                                    name="uq_bpp_altline_source"),
            models.CheckConstraint(condition=Q(price__isnull=True) | Q(price__gt=0),
                                   name="ck_bpp_altline_price"),
            models.CheckConstraint(condition=Q(qty__gt=0), name="ck_bpp_altline_qty"),
        ]
        ordering = ("created_at",)
        verbose_name = "Позиция альтернативного предложения"
        verbose_name_plural = "Позиции альтернативного предложения"


class KpiStatus(models.TextChoices):
    PRELIMINARY = "preliminary", "Предварительный"
    CONFIRMED = "confirmed", "Подтверждён"
    ANNULLED = "annulled", "Аннулирован"


class KpiRecord(VersionedModel):
    """Запись KPI снабжения по выбранной АП (ТЗ §12.5, BR-095, BR-096).

    Снимок на момент выбора: кто покупатель, какой документ заменён и чем.
    Пока «Предварительный» — сумма нового документа и экономия
    пересчитываются (CALC-013); после «Подтверждён» заморожены (D-S5-7).
    """

    offer = models.OneToOneField(AlternativeOffer, on_delete=models.PROTECT,
                                 related_name="kpi")
    buyer_id = models.IntegerField()
    buyer_role = models.CharField(max_length=8, choices=InitiatorRole.choices)
    own_document = models.BooleanField(default=False, db_default=False)
    project_id = models.UUIDField()
    article_id = models.UUIDField()
    source_type = models.CharField(max_length=16, choices=OfferSource.choices)
    source_id = models.UUIDField()
    source_number = models.CharField(max_length=32)
    source_counterparty_id = models.UUIDField(null=True, blank=True)
    source_amount_kzt = models.DecimalField(max_digits=18, decimal_places=2)
    result_type = models.CharField(max_length=16, choices=OfferSource.choices)
    result_id = models.UUIDField()
    result_number = models.CharField(max_length=32, default="", db_default="", blank=True)
    result_amount_kzt = models.DecimalField(max_digits=18, decimal_places=2, null=True,
                                            blank=True)
    saving_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    saving_pct = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    selected_at = models.DateTimeField()
    selected_by_id = models.IntegerField()
    status = models.CharField(max_length=16, choices=KpiStatus.choices,
                              default=KpiStatus.PRELIMINARY, db_default=KpiStatus.PRELIMINARY)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    annul_comment = models.TextField(default="", db_default="", blank=True)
    annulled_by_id = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["buyer_id", "status"], name="ix_bpp_kpi_buyer"),
            models.Index(fields=["selected_at"], name="ix_bpp_kpi_selected"),
            # ``kpi.sync_for_document`` ищет запись по новому документу на
            # каждой смене статуса любого счёта и договора (D-S5-8).
            models.Index(fields=["result_type", "result_id"], name="ix_bpp_kpi_result"),
        ]
        ordering = ("-selected_at",)
        verbose_name = "Запись KPI снабжения"
        verbose_name_plural = "Записи KPI снабжения"

    def __str__(self) -> str:
        return f"KPI {self.source_number} → {self.result_number or self.result_id}"
