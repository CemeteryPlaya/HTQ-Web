"""Pydantic-схемы тел запросов домена hr.

Порт services/hr/app/schemas/. Формы ОТВЕТОВ здесь не описываются — они
собираются сериализаторами в apps/hr/services/*, чтобы не плодить второй
слой моделей поверх ORM (как и в остальных перенесённых аппках).
"""
from __future__ import annotations

from datetime import date
from typing import Literal

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


# ── positions — порт services/hr/app/schemas/position.py ────────────────────

HRLevelLiteral = Literal["junior", "middle", "senior", "lead"]


class PositionPermissions(BaseModel):
    """Матрица прав, прикреплённая к несистемной должности.

    ``permissions`` — авторитетный набор ключей (проверяется исходником в
    ``app.auth.hr_access``, который в porту ещё не появился — см. брифы
    employees). ``hr_level`` — UI/миграционный пресет: выбор уровня
    заполняет ``permissions`` соответствующим пресетом (apps.hr.permissions).
    """

    hr_level: HRLevelLiteral | None = None
    permissions: list[str] = Field(default_factory=list)


class PositionCreate(BaseModel):
    title: str = Field(..., max_length=255)
    department_id: int
    grade: int = Field(default=1, ge=1, le=10)
    description: str | None = None
    requirements: dict | None = None
    is_active: bool = True
    weight: int = Field(default=100, ge=0)
    permissions: PositionPermissions | None = None


class PositionUpdate(BaseModel):
    """Порт PositionUpdate — все поля опциональны, exclude_none PATCH-семантика
    (как и DepartmentUpdate)."""

    title: str | None = Field(default=None, max_length=255)
    department_id: int | None = None
    grade: int | None = Field(default=None, ge=1, le=10)
    description: str | None = None
    requirements: dict | None = None
    is_active: bool | None = None
    weight: int | None = Field(default=None, ge=0)
    permissions: PositionPermissions | None = None


class PositionWeightUpdate(BaseModel):
    weight: int = Field(..., ge=0)


class PositionMoveRequest(BaseModel):
    before_position_id: int | None = None
    after_position_id: int | None = None
    target_level: int | None = Field(default=None, ge=1)


class PositionRebalanceRequest(BaseModel):
    level: int | None = Field(default=None, ge=1)


class PositionListQuery(BaseModel):
    """Порт Query(page, limit) роутера — валидация даёт тот же 422, что и
    FastAPI при выходе за границы (страница <1, лимит вне [1, 200])."""

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=200)


class LevelThresholdCreate(BaseModel):
    level_number: int = Field(..., ge=1)
    weight_from: int = Field(..., ge=0)
    weight_to: int = Field(..., ge=0)
    label: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class LevelThresholdUpdate(BaseModel):
    weight_from: int | None = Field(default=None, ge=0)
    weight_to: int | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


# ── employees — порт services/hr/app/schemas/employee.py ────────────────────
#
# ``status`` — ШЕСТЬ значений контракта (см. models.py::EmployeeStatus
# docstring): active|inactive|terminated|suspended|pending|rejected —
# идентичный regex EmployeeBase.status исходника, не сокращённый список.
_STATUS_PATTERN = r"^(active|inactive|terminated|suspended|pending|rejected)$"


class EmployeeCreate(BaseModel):
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    email: str = Field(..., max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    department_id: int
    position_id: int
    hire_date: date
    status: str = Field(default="active", pattern=_STATUS_PATTERN)
    avatar_url: str | None = Field(default=None, max_length=500)
    bio: str | None = None
    user_id: int | None = None


class EmployeeUpdate(BaseModel):
    """Порт EmployeeUpdate — все поля опциональны, exclude_none PATCH-семантика
    (как и Department/PositionUpdate)."""

    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    middle_name: str | None = None
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = None
    department_id: int | None = None
    position_id: int | None = None
    status: str | None = Field(default=None, pattern=_STATUS_PATTERN)
    avatar_url: str | None = None
    bio: str | None = None
    termination_date: date | None = None


class EmployeeTransfer(BaseModel):
    department_id: int
    position_id: int | None = None
    effective_date: date | None = None


class EmployeeListQuery(BaseModel):
    """Порт Query(department_id, status, search, page, limit) роутера —
    page/limit валидируются как PositionListQuery (та же 422-семантика)."""

    department_id: int | None = None
    status: str | None = None
    search: str | None = None
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=200)
