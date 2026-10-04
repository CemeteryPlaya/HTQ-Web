"""Общие справочники модуля БЗО — одна копия на группу, схема public (D-03).

Удаления нет: запись уходит в архив (``is_active=False``) и остаётся в
старых документах (ТЗ §18). Периодические значения (НДС, МРП, курсы) —
по датам: документ берёт значение на свою дату.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
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

    def parent_problem(self, parent: "Article | None") -> tuple[str, str] | None:
        """Почему ``parent`` не годится в родители этой статьи: ``(текст, коротко
        для поля)``; ``None`` — годится.

        Одно правило на оба входа — ручку API (``services/articles.py``,
        ошибка E-REF-05) и django-admin (``clean()`` ниже): иначе админка
        обходила бы то, что держит API.

        - родитель — из той же группы: группа открывает статьи по узлу прав
          (BR-010), и статья одной группы в дереве другой показывалась бы тем,
          кому её группа закрыта;
        - не сама статья и не её потомок — дерево без циклов;
        - не архивная — но только когда родителя ставят сейчас: статья,
          чей родитель ушёл в архив позже, остаётся редактируемой.
        """
        if parent is None:
            return None
        if parent.pk == self.pk:
            return ("Статья не может быть родителем самой себе.", "Та же статья")
        if self.group_id is not None and str(parent.group_id) != str(self.group_id):
            return (f"Статья „{parent.name}“ относится к группе „{parent.group.name}“. "
                    f"Родительская статья выбирается из той же группы, что и сама статья.",
                    "Статья другой группы")
        # Цикл: поднимаемся от родителя к корню; встретили себя — родитель
        # оказался бы собственным потомком. ``seen`` страхует от уже
        # испорченного дерева.
        seen = {parent.pk}
        ancestor_id = parent.parent_id
        while ancestor_id is not None and ancestor_id not in seen:
            if ancestor_id == self.pk:
                return (f"Статья „{parent.name}“ вложена в эту статью — родителем "
                        f"она быть не может.", "Вложенная статья")
            seen.add(ancestor_id)
            ancestor_id = (Article.objects.filter(pk=ancestor_id)
                           .values_list("parent_id", flat=True).first())
        if not parent.is_active and self._parent_changes(parent):
            return (f"Статья „{parent.name}“ в архиве. Родителем может быть только "
                    f"действующая статья — выберите другую или верните эту из архива.",
                    "Статья в архиве")
        return None

    def _parent_changes(self, parent: "Article") -> bool:
        if self._state.adding:
            return True
        stored = (Article.objects.filter(pk=self.pk)
                  .values_list("parent_id", flat=True).first())
        return stored != parent.pk

    def clean(self):
        super().clean()
        if self.parent_id is None:
            return
        problem = self.parent_problem(self.parent)
        if problem is not None:
            raise ValidationError({"parent": problem[0]})


class ProductionDay(_Base):
    """Ручное переопределение дня производственного календаря РК (D-S7-1).

    Одна таблица на группу (``public``): базовый календарь считает
    ``apps.core.kz_holidays``, строка здесь — правка поверх него. Раньше такие
    строки жили в схеме каждой компании (``tasks.ProductionDay``).
    ``working_days_since_epoch`` — бегущий счёт рабочих дней с 1 января года
    строки (имя историческое, счётчик сбрасывается каждый год).
    """

    date = models.DateField(unique=True)
    # working | weekend | holiday | short
    day_type = models.CharField(max_length=20, default="working", db_default="working")
    note = models.CharField(max_length=255, null=True, blank=True)
    working_days_since_epoch = models.IntegerField(db_index=True)

    class Meta:
        ordering = ("date",)
        verbose_name = "Производственный день"
        verbose_name_plural = "Производственные дни"
