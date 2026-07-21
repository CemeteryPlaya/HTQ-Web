"""Pydantic-схемы тел запросов домена hr.

Порт services/hr/app/schemas/. Формы ОТВЕТОВ здесь не описываются — они
собираются сериализаторами в apps/hr/services/*, чтобы не плодить второй
слой моделей поверх ORM (как и в остальных перенесённых аппках).
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


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


# ── org — порт services/hr/app/api/v1/org.py (схемы были inline в роутере) ──

RelationTypeLiteral = Literal["direct", "functional", "project"]
DeletionStrategyLiteral = Literal["block", "reassign_to_parent", "cascade"]


class OrgTreeQuery(BaseModel):
    """Порт Query(root_id, depth, mode, lang) роутера ``GET /org/tree``."""

    root_id: int | None = Field(default=None)
    depth: int = Field(default=5, ge=1, le=10)
    mode: Literal["positions", "employees", "both"] = "positions"
    lang: Literal["ru", "en"] = "ru"


class OrgMatrixQuery(BaseModel):
    """Порт Query(unit_id) роутера ``GET /org/subordination-matrix``."""

    unit_id: int | None = None


class RelationCreate(BaseModel):
    superior_position_id: int
    subordinate_position_id: int
    relation_type: RelationTypeLiteral = "direct"
    effective_from: date | None = None
    effective_to: date | None = None


class OrgSettingUpdate(BaseModel):
    deletion_strategy: DeletionStrategyLiteral


# ── recruiting — порт services/hr/app/schemas/{vacancy,application}.py ──────

VacancyStatusLiteral = Literal["open", "closed", "on_hold"]
ApplicationStatusLiteral = Literal["new", "reviewed", "interview", "offer", "rejected", "hired"]


class VacancyCreate(BaseModel):
    title: str = Field(..., max_length=255)
    department_id: int
    position_id: int
    description: str = ""
    requirements: str = ""
    status: VacancyStatusLiteral = "open"
    assigned_recruiter_id: int | None = None


class VacancyUpdate(BaseModel):
    """Порт VacancyUpdate — все поля опциональны, exclude_none PATCH-семантика
    (как и Department/PositionUpdate)."""

    title: str | None = Field(default=None, max_length=255)
    department_id: int | None = None
    position_id: int | None = None
    description: str | None = None
    requirements: str | None = None
    status: VacancyStatusLiteral | None = None
    assigned_recruiter_id: int | None = None
    closed_at: date | None = None


class VacancyListQuery(BaseModel):
    """Порт Query(status, department_id, page, limit) роутера ``GET /vacancies/``.

    ``status`` — свободная строка в исходнике (без pattern на фильтре, в
    отличие от VacancyCreate/Update.status) — фильтр по несуществующему
    статусу просто не найдёт совпадений, не 422.
    """

    status: str | None = None
    department_id: int | None = None
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=200)


class ApplicationCreate(BaseModel):
    vacancy_id: int
    candidate_name: str = Field(..., max_length=255)
    candidate_email: EmailStr
    candidate_phone: str | None = Field(default=None, max_length=20)
    resume_url: str | None = Field(default=None, max_length=500)
    cover_letter: str | None = None
    notes: str | None = None


class ApplicationUpdate(BaseModel):
    """Порт ApplicationUpdate — все поля опциональны, exclude_none PATCH-семантика."""

    candidate_name: str | None = Field(default=None, max_length=255)
    candidate_email: EmailStr | None = None
    candidate_phone: str | None = None
    resume_url: str | None = None
    cover_letter: str | None = None
    notes: str | None = None
    status: ApplicationStatusLiteral | None = None


class ApplicationStatusChange(BaseModel):
    status: ApplicationStatusLiteral
    notes: str | None = None


class ApplicationListQuery(BaseModel):
    """Порт Query(page, limit) роутера ``GET /applications/`` — без фильтров."""

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=200)
