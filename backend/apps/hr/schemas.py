"""Pydantic-схемы тел запросов домена hr.

Порт services/hr/app/schemas/. Формы ОТВЕТОВ здесь не описываются — они
собираются сериализаторами в apps/hr/services/*, чтобы не плодить второй
слой моделей поверх ORM (как и в остальных перенесённых аппках).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    """Порт schemas/department.py::DepartmentCreate.

    ``path`` необязателен: если не прислан, сервис генерирует его
    транслитерацией имени (с учётом ``parent_id``).
    """

    name: str = Field(..., max_length=255)
    path: str | None = Field(default=None, max_length=500)
    description: str | None = None
    manager_id: int | None = None
    is_active: bool = True
    parent_id: int | None = None


class DepartmentUpdate(BaseModel):
    """Порт schemas/department.py::DepartmentUpdate — все поля опциональны.

    Исходник применяет патч через ``model_dump(exclude_none=True)``: поле со
    значением ``None`` НЕ затирает существующее. Это ровно PATCH-семантика.
    """

    name: str | None = Field(default=None, max_length=255)
    path: str | None = Field(default=None, max_length=500)
    description: str | None = None
    manager_id: int | None = None
    is_active: bool | None = None
