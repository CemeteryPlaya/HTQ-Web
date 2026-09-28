"""Счета организации и шаблоны выписок (ТЗ §11.2, §18 — строка «Банковские
счета организации и шаблоны выписок», задача A3.1).

Справочник ведёт АДМ (узел ``bpp.settings``), читают ФД и БУХ (``bpp.bank``).
Удаления нет — архив ``is_active=False`` (ТЗ §18: «Да / да / архив»).

**Шаблон выписки** описывает, как читать файл банк-клиента. Код не знает ни
одного банка (D-S3-3): Excel и CSV разбираются только по шаблону.
``columns`` — «поле выписки → текст заголовка колонки в файле»; колонки
ищутся по заголовку, а не по номеру, поэтому их порядок в файле не важен
(``services/bank/templates.py``). Выписке 1С (1CClientBankExchange) колонки
не нужны: имена полей задаёт стандарт формата, разбор — задача 3.

``amount_mode``: ``signed`` — одна колонка суммы со знаком, отрицательная
сумма — списание (дебет), положительная — поступление; ``split`` — две
колонки «Дебет» и «Кредит», списание — непустой дебет.

``date_format`` — маска для человека («ДД.ММ.ГГГГ»), а не шаблон
``strptime``: её правит АДМ в форме. Перевод — ``templates.date_pattern``.

**Счёт организации** — IBAN (KZ + 18 знаков, mod 97 — та же проверка, что у
счетов контрагентов), банк, БИК, валюта и шаблон, по которому разбирается
его выписка (ТЗ §11.2: счёт «определяет шаблон разбора»). IBAN уникален —
вместе с архивными: счёт, выведенный в архив, возвращается из архива, а не
заводится вторым (E-BNK-01).
"""

from __future__ import annotations

from django.db import models

from .core import BppModel, VersionedModel

__all__ = [
    "AmountMode",
    "OrgBankAccount",
    "StatementFormat",
    "StatementTemplate",
]


class StatementFormat(models.TextChoices):
    ONEC = "onec", "1С (1CClientBankExchange, .txt)"
    XLSX = "xlsx", "Excel (.xlsx)"
    CSV = "csv", "CSV"


class AmountMode(models.TextChoices):
    SIGNED = "signed", "Одна колонка суммы со знаком"
    SPLIT = "split", "Колонки «Дебет» и «Кредит»"


class StatementTemplate(VersionedModel):
    name = models.CharField(max_length=255)
    format = models.CharField(max_length=8, choices=StatementFormat.choices)
    # cp1251 — 1С и CSV банк-клиентов, utf-8 — xlsx (кодировку xlsx задаёт
    # сама книга, поле для неё справочное). Умолчание по формату ставит
    # сервис (``services/bank/settings.py``).
    encoding = models.CharField(max_length=32, default="cp1251", db_default="cp1251")
    delimiter = models.CharField(max_length=4, default=";", db_default=";", blank=True)
    date_format = models.CharField(max_length=32, default="ДД.ММ.ГГГГ",
                                   db_default="ДД.ММ.ГГГГ")
    columns = models.JSONField(default=dict, blank=True)
    amount_mode = models.CharField(max_length=8, choices=AmountMode.choices,
                                   default=AmountMode.SIGNED, db_default=AmountMode.SIGNED)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ("name", "created_at")
        verbose_name = "Шаблон выписки"
        verbose_name_plural = "Шаблоны выписок"

    def __str__(self) -> str:
        return self.name


class OrgBankAccount(VersionedModel):
    iban = models.CharField(max_length=34)
    bank_name = models.CharField(max_length=255, default="", blank=True)
    bic = models.CharField(max_length=11)
    currency = models.CharField(max_length=3, default="KZT", db_default="KZT")
    template = models.ForeignKey(StatementTemplate, on_delete=models.PROTECT,
                                 related_name="accounts")
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["iban"], name="uq_bpp_org_account_iban"),
        ]
        ordering = ("-is_active", "bank_name", "iban")
        verbose_name = "Банковский счёт организации"
        verbose_name_plural = "Банковские счета организации"

    def __str__(self) -> str:
        return f"{self.bank_name} {self.iban}".strip()
