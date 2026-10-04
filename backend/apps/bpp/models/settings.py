"""Настройки модуля БЗО — ключ → значение в схеме компании.

Одна строка на настройку; умолчания живут в коде
(``services/core/settings.DEFAULTS``), строка появляется, только когда
настройку поменяли. Первая настройка — порог метки «Проверенный» у
контрагента (D-20).
"""

from __future__ import annotations

from django.db import models
from django.db.models.functions import Now

__all__ = ["ModuleSetting"]


class ModuleSetting(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())
    updated_by = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Настройка модуля"
        verbose_name_plural = "Настройки модуля"

    def __str__(self) -> str:
        return self.key
