"""Базовые модели модуля БЗО.

``BppModel`` — общая основа документов: UUID-ключ (ТЗ §24, решение Q-C23),
кто и когда создал и изменил. ``VersionedModel`` добавляет ``version`` —
счётчик правок для оптимистической блокировки (E-CON-01, D-29).
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now


class BppModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    created_by = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())
    updated_by = models.IntegerField(null=True, blank=True)

    class Meta:
        abstract = True


class VersionedModel(BppModel):
    version = models.PositiveIntegerField(default=1, db_default=1)

    class Meta:
        abstract = True


class NumberSequence(models.Model):
    """Годовой счётчик номеров одного вида документа в схеме компании.

    Строка на (префикс, год). Номер выдаёт одна атомарная команда
    ``INSERT … ON CONFLICT DO UPDATE … RETURNING`` (``services/core/
    numbering.py``) — гонка двух выдач невозможна без явной блокировки.
    """

    prefix = models.CharField(max_length=8)
    year = models.PositiveSmallIntegerField()
    last = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["prefix", "year"],
                                               name="uq_bpp_number_prefix_year")]
        verbose_name = "Счётчик номеров"
        verbose_name_plural = "Счётчики номеров"


class AuditLog(models.Model):
    """Журнал изменений документов — только для записи (ТЗ §25.2, D-30).

    Правку и удаление запрещает триггер БД (миграция ``0001_core``): запрет
    только в коде обходится django-admin'ом и сырым SQL. Хранение — 5 лет
    (Q-B32); чистка — отдельной задачей через отключение триггера под
    ролью миграций, не из приложения.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    action = models.CharField(max_length=32)
    actor_id = models.IntegerField(null=True, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    comment = models.TextField(default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        indexes = [models.Index(fields=["object_type", "object_id", "created_at"],
                                name="ix_bpp_audit_object")]
        ordering = ("created_at",)
        verbose_name = "Запись журнала"
        verbose_name_plural = "Журнал изменений"
