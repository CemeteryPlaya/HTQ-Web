"""Контрагенты и их банковские счета (ТЗ §18, решение D-20, задача A2.3).

Контрагент заводится без согласования. Метка «Проверенный» не хранится
готовой: она следует из ``successful_documents`` (удачные договоры и
оплаченные счета — их засчитывает B, ``lookup.record_success``) и порога
настройки модуля ``counterparty_verified_threshold``. ``verified_override``
— ручное решение ФД: ``None`` — по порогу, ``True``/``False`` — поверх него.

Уникальна пара (страна, рег. номер) — номер хранится нормализованным
(``services/counterparties/validation.normalize_reg_number``), поэтому
«123 456-789 012» и «123456789012» — один контрагент. Удаления нет:
справочник архивный (ТЗ §18, soft delete).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from .core import BppModel, VersionedModel

__all__ = [
    "Counterparty",
    "CounterpartyBankAccount",
    "CounterpartyKind",
    "CounterpartyStatus",
]


class CounterpartyKind(models.TextChoices):
    LEGAL = "legal", "Юридическое лицо"
    IP = "ip", "Индивидуальный предприниматель"
    INDIVIDUAL = "individual", "Физическое лицо"
    NONRESIDENT = "nonresident", "Нерезидент"


class CounterpartyStatus(models.TextChoices):
    ACTIVE = "active", "Активен"
    BLOCKED = "blocked", "Заблокирован"
    ARCHIVED = "archived", "Архив"


class Counterparty(VersionedModel):
    name = models.CharField(max_length=500)
    short_name = models.CharField(max_length=255, default="", blank=True)
    kind = models.CharField(max_length=16, choices=CounterpartyKind.choices)
    country_code = models.CharField(max_length=2)  # ISO 3166-1 alpha-2, refdata.Country
    reg_number = models.CharField(max_length=30)   # БИН/ИИН или номер нерезидента
    is_vat_payer = models.BooleanField(default=False, db_default=False)
    vat_cert_series = models.CharField(max_length=32, default="", blank=True)
    vat_cert_number = models.CharField(max_length=32, default="", blank=True)
    legal_address = models.TextField(default="", blank=True)
    contact_person = models.CharField(max_length=255, default="", blank=True)
    phone = models.CharField(max_length=64, default="", blank=True)
    email = models.CharField(max_length=254, default="", blank=True)
    status = models.CharField(max_length=16, choices=CounterpartyStatus.choices,
                              default=CounterpartyStatus.ACTIVE,
                              db_default=CounterpartyStatus.ACTIVE)
    # Блокировка — решение ФД с причиной (E-CTR-01 печатает дату и причину).
    block_reason = models.TextField(default="", blank=True)
    blocked_at = models.DateTimeField(null=True, blank=True)
    blocked_by = models.IntegerField(null=True, blank=True)
    # Метка «Проверенный» (D-20): счётчик удачных документов и ручное
    # решение ФД поверх порога.
    successful_documents = models.PositiveIntegerField(default=0, db_default=0)
    verified_override = models.BooleanField(null=True, blank=True)
    # Ключ записи в 1С — заготовка синхронизации (D-38, A7.3).
    ext_1c_ref = models.CharField(max_length=64, default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["country_code", "reg_number"],
                                    name="uq_bpp_counterparty_reg"),
        ]
        indexes = [
            models.Index(fields=["status", "name"], name="ix_bpp_counterparty_status"),
        ]
        ordering = ("name",)
        verbose_name = "Контрагент"
        verbose_name_plural = "Контрагенты"

    def __str__(self) -> str:
        return f"{self.short_name or self.name} ({self.reg_number})"


class CounterpartyBankAccount(BppModel):
    """Банковский счёт контрагента: IBAN (KZ + 18 знаков), банк, БИК (8 или
    11 знаков), валюта, признак «основной». Архив — ``is_active=False``."""

    counterparty = models.ForeignKey(Counterparty, on_delete=models.PROTECT,
                                     related_name="bank_accounts")
    iban = models.CharField(max_length=34)
    bank_name = models.CharField(max_length=255, default="", blank=True)
    bic = models.CharField(max_length=11)
    currency = models.CharField(max_length=3, default="KZT", db_default="KZT")
    is_primary = models.BooleanField(default=False, db_default=False)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["iban"], name="uq_bpp_cp_account_iban"),
            # Основной счёт у контрагента — один.
            models.UniqueConstraint(fields=["counterparty"], condition=Q(is_primary=True),
                                    name="uq_bpp_cp_account_primary"),
        ]
        ordering = ("-is_primary", "created_at")
        verbose_name = "Банковский счёт контрагента"
        verbose_name_plural = "Банковские счета контрагентов"

    def __str__(self) -> str:
        return self.iban
