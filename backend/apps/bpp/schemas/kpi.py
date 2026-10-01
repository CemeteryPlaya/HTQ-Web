"""Тела запросов KPI снабжения (A5.2)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KpiAnnul(BaseModel):
    """Аннулирование записи: длину комментария (BR-060) проверяет сервис —
    отказ приходит кодом модуля, а не общей ошибкой схемы."""

    version: int | None = None
    comment: str = Field(default="", max_length=1000)
