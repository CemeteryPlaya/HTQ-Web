"""Общие справочники модуля БЗО — одна копия на группу, схема public (D-03).

Удаления нет: запись уходит в архив (``is_active=False``) и остаётся в
старых документах (ТЗ §18). Периодические значения (НДС, МРП, курсы) —
по датам: документ берёт значение на свою дату.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now


class _Base(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        abstract = True


class Country(_Base):
    code = models.CharField(max_length=2, unique=True)  # ISO 3166-1 alpha-2
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Страна"
        verbose_name_plural = "Страны"


class Currency(_Base):
    code = models.CharField(max_length=3, unique=True)  # ISO 4217
    name = models.CharField(max_length=64)
    symbol = models.CharField(max_length=8, default="", blank=True)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ("code",)
        verbose_name = "Валюта"
        verbose_name_plural = "Валюты"


class RateSource(models.TextChoices):
    NBRK = "nbrk", "НБРК"
    MANUAL = "manual", "Вручную"


class ExchangeRate(_Base):
    """Курс валюты к KZT на дату. Ручной курс не перезаписывается загрузкой."""

    currency_code = models.CharField(max_length=3)
    on_date = models.DateField()
    rate = models.DecimalField(max_digits=18, decimal_places=6)
    source = models.CharField(max_length=8, choices=RateSource.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["currency_code", "on_date"],
                                               name="uq_refdata_rate_day")]
        verbose_name = "Курс валюты"
        verbose_name_plural = "Курсы валют"


class VatRate(_Base):
    """Ставка НДС страны на период ``[date_from, date_to]`` (``date_to`` пусто — бессрочно)."""

    country_code = models.CharField(max_length=2)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    date_from = models.DateField()
    date_to = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("country_code", "date_from")
        verbose_name = "Ставка НДС"
        verbose_name_plural = "Ставки НДС"


class MrpValue(_Base):
    """МРП, действующий с ``date_from`` (ТЗ §18: 2026 — 4 325 тг)."""

    date_from = models.DateField(unique=True)
    value = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ("date_from",)
        verbose_name = "МРП"
        verbose_name_plural = "МРП"


class Uom(_Base):
    code = models.CharField(max_length=16, unique=True)
    short_name = models.CharField(max_length=16)
    name = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Единица измерения"
        verbose_name_plural = "Единицы измерения"


class ArticleGroup(_Base):
    """Группа статей. ``node_key`` — узел реестра прав, открывающий статьи группы (BR-010)."""

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    node_key = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Группа статей"
        verbose_name_plural = "Группы статей"


class Article(_Base):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    group = models.ForeignKey(ArticleGroup, on_delete=models.PROTECT, related_name="articles")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="children")
    is_active = models.BooleanField(default=True, db_default=True)
    ext_1c_ref = models.CharField(max_length=64, default="", blank=True)

    class Meta:
        ordering = ("code",)
        verbose_name = "Статья бюджета"
        verbose_name_plural = "Статьи бюджета"
