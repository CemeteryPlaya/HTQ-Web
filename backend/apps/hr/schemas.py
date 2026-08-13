"""Pydantic-схемы тел запросов домена hr.

Порт services/hr/app/schemas/. Формы ОТВЕТОВ здесь не описываются — они
собираются сериализаторами в apps/hr/services/*, чтобы не плодить второй
слой моделей поверх ORM (как и в остальных перенесённых аппках).
"""
from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, RootModel, field_validator, model_validator


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
    # НЕ поле модели: level в БД — кэш, вычисляемый из веса. Здесь это способ
    # выбрать вес («поставь должность на уровень L3»): сервис подбирает
    # свободный вес внутри диапазона порога, а level, как и прежде, приходит
    # из _compute_level. Вес, заданный явно вместе с level, обязан попадать
    # в диапазон этого уровня — иначе 422.
    level: int | None = Field(default=None, ge=1)
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
    level: int | None = Field(default=None, ge=1)  # см. PositionCreate.level
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
    # Диапазон необязателен: UI просит у HR только номер, название и цвет, а
    # веса подбирает сервис (position_service.next_free_range) по МЕСТУ уровня
    # среди существующих. Переданный явно — работает как раньше, с проверкой
    # на пересечение.
    weight_from: int | None = Field(default=None, ge=0)
    weight_to: int | None = Field(default=None, ge=0)
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


class HRUserCreateRequest(BaseModel):
    """``POST /employees/users/`` body — порт
    ``services/hr/app/api/v1/employees.py::HRUserCreateRequest``. ``username``
    по-прежнему выводится из email в ``apps.users.interface.create_user``.

    ``password`` ДОБАВЛЕН сверх исходника и обязателен. Раньше HR-форма его не
    спрашивала, а ``interface.create_user`` молча минтил случайный
    ``secrets.token_urlsafe(12)``, которого не видел никто — включая самого
    сотрудника. Формально аккаунт создавался, фактически войти в него было
    нельзя, пока администратор не сбросит пароль через свою панель. Пустую
    строку отбиваем во вьюхе (422), а не тут: так сообщение об ошибке
    остаётся в одном стиле с проверкой email рядом.

    Поля ``must_change_password`` тут НЕТ намеренно. Пароль на этом маршруте
    всегда назначает HR, а не сам сотрудник, и HR его видит — значит первый
    вход обязан заканчиваться сменой. Будь это поле в теле запроса, гарантия
    держалась бы на клиенте: любой, кто шлёт запрос напрямую, отправил бы
    ``false``. Вьюха проставляет ``True`` жёстко, а лишний ключ pydantic по
    умолчанию игнорирует — старые клиенты не ломаются, но и обойти правило не
    могут. Админской панели поле по-прежнему доступно: там сценарии другие
    (сервисные учётки, ручной сброс).

    ``email`` is a plain ``str`` (not ``EmailStr``) — the source's field is
    plain ``str`` too; the source does its own manual "has an @" check in the
    view (``apps.hr.views._create_user_option`` ports it verbatim) rather
    than relying on pydantic's stricter validator, which also rejects the
    reserved ``.test`` TLD this codebase's tests use throughout."""

    first_name: str = ""
    last_name: str = ""
    patronymic: str = ""
    email: str
    password: str = ""


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


# ── time-tracking — порт services/hr/app/schemas/time_tracking.py ───────────

class TimeEntryCreate(BaseModel):
    """Порт TimeEntryBase + TimeEntryCreate — валидатор end_after_start
    буквально: end_time <= start_time -> 422 (pydantic ValueError)."""

    employee_id: int
    date: date
    start_time: time
    end_time: time
    break_minutes: int = Field(default=0, ge=0)
    description: str | None = None
    project: str | None = Field(default=None, max_length=255)
    task: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _end_after_start(self) -> "TimeEntryCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class TimeEntryUpdate(BaseModel):
    """Порт TimeEntryUpdate — все поля опциональны, exclude_none PATCH-семантика
    (как и Department/PositionUpdate). Без end_after_start валидатора — как
    и в исходнике (только TimeEntryBase/Create его несут).

    Атрибут ``entry_date`` (не ``date``) с ``alias="date"`` — умышленно, НЕ
    косметика: поле, названное как свой же тип (``date: date | None = None``),
    в сочетании с ``from __future__ import annotations`` (файл целиком под
    postponed evaluation) ловит реальный питоновский капкан — присвоенный
    class-body default ``None`` попадает в пространство имён класса под тем
    же именем ``date`` ДО того, как pydantic лениво вычисляет строковую
    аннотацию ``"date | None"``, и резолвит ``date`` в ``None`` вместо
    импортированного типа (``TypeError: unsupported operand type(s) for |:
    'NoneType' and 'NoneType'`` при первом же обращении к роуту). Обходится
    переименованием python-атрибута при сохранении wire-имени "date" через
    alias — вызывающая сторона обязана дампить с ``by_alias=True``
    (services/time_service.py::update_entry)."""

    model_config = ConfigDict(populate_by_name=True)

    entry_date: date | None = Field(default=None, alias="date")
    start_time: time | None = None
    end_time: time | None = None
    break_minutes: int | None = Field(default=None, ge=0)
    description: str | None = None
    project: str | None = None
    task: str | None = None


class TimeEntryListQuery(BaseModel):
    """Порт Query(page, limit) роутера ``GET /time-tracking/`` и
    ``GET /time-tracking/entries/`` — идентичная page/limit валидация."""

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=200)


class TimeDailyReportQuery(BaseModel):
    """Порт Query(employee_id, date) роутера ``GET /time-tracking/reports/daily``.

    ``date`` опционален (default_factory=date.today в исходнике) — здесь
    ``None`` и подстановка ``date.today()`` в вьюхе, тот же эффект.

    ``report_date``/``alias="date"`` — та же защита от самозатеняющегося
    поля под postponed evaluation, что и TimeEntryUpdate.entry_date выше."""

    model_config = ConfigDict(populate_by_name=True)

    employee_id: int
    report_date: date | None = Field(default=None, alias="date")


class TimeWeeklyReportQuery(BaseModel):
    employee_id: int
    week_start: date


class TimeMonthlyReportQuery(BaseModel):
    employee_id: int
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)


# ── staffing — порт services/hr/app/schemas/staffing.py ─────────────────────

class StaffingLineIn(BaseModel):
    """Порт StaffingLineIn — СТРОКОВЫЕ headcount/salary (не float), дефолты
    "1"/"0". Используется И для create (POST), И для update (PUT) — в
    исходнике нет отдельной Update-схемы: PUT всегда ожидает ПОЛНОЕ тело
    (контракт, не баг)."""

    position_id: int
    department_id: int
    grade: int | None = None
    headcount: str = "1"
    salary: str = "0"
    note: str | None = None


class StaffingListQuery(BaseModel):
    """Порт Query(department_id) роутера ``GET /staffing/``."""

    department_id: int | None = None


# ── personnel-history — порт services/hr/app/api/v1/personnel_history.py ───
# (схемы были inline в роутере исходника, как и у org/*)

class PersonnelHistoryIn(BaseModel):
    employee: int
    event_type: str = "other"
    event_date: date
    from_department: int | None = None
    to_department: int | None = None
    from_position: int | None = None
    to_position: int | None = None
    order_number: str = ""
    comment: str = ""


# ── calendar — порт services/hr/app/schemas/calendar.py ─────────────────────
#
# WeekTemplateOut/ShiftPatternOut исходника не переносятся как pydantic-модели
# (как и везде в этом файле — формы ответов собираются сериализаторами в
# apps/hr/services/calendar_service.py: template_out/shift_pattern_out).

_CALENDAR_DAY_TYPES = {"working", "weekend", "holiday", "short"}
_CALENDAR_TMPL_TYPES = {"working", "weekend"}


class WeekDayConfig(BaseModel):
    type: str
    hours: float = Field(ge=0)

    @field_validator("type")
    @classmethod
    def _type_ok(cls, v: str) -> str:
        if v not in _CALENDAR_TMPL_TYPES:
            raise ValueError(f"type must be one of {_CALENDAR_TMPL_TYPES}")
        return v


class WeekTemplateIn(BaseModel):
    name: str = Field(max_length=100)
    days: dict[str, WeekDayConfig]

    @field_validator("days")
    @classmethod
    def _days_ok(cls, v: dict[str, WeekDayConfig]) -> dict[str, WeekDayConfig]:
        if set(v.keys()) != {str(i) for i in range(7)}:
            raise ValueError('days must have keys "0".."6"')
        return v


class CalendarDayIn(BaseModel):
    day_type: str
    norm_hours: float = Field(default=0, ge=0)
    note: str | None = None

    @field_validator("day_type")
    @classmethod
    def _type_ok(cls, v: str) -> str:
        if v not in _CALENDAR_DAY_TYPES:
            raise ValueError(f"day_type must be one of {_CALENDAR_DAY_TYPES}")
        return v


class CalendarImportItem(CalendarDayIn):
    day: date


class CalendarImportBody(RootModel[list[CalendarImportItem]]):
    """Порт ``items: list[CalendarImportItem]`` роутера — тело запроса POST
    /calendar/import ЦЕЛИКОМ является JSON-массивом (не обёрткой-объектом).
    ``RootModel`` — единственный способ отдать это через
    ``htqweb.http.api_view(body=...)``, которое зовёт
    ``body.model_validate_json(...)`` (принимает произвольный BaseModel-
    наследник, включая RootModel)."""


class AssignTemplateIn(BaseModel):
    week_template_id: int | None = None


class ShiftSlot(BaseModel):
    type: str
    hours: float = Field(ge=0)

    @field_validator("type")
    @classmethod
    def _slot_type_ok(cls, v: str) -> str:
        if v not in {"work", "off"}:
            raise ValueError('slot type must be "work" or "off"')
        return v


class ShiftPatternIn(BaseModel):
    name: str = Field(max_length=100)
    slots: list[ShiftSlot] = Field(min_length=1)
    holidays_off: bool = False


class AssignShiftIn(BaseModel):
    shift_pattern_id: int
    anchor_date: date


class EmployeeDayOverrideIn(BaseModel):
    day_type: str
    norm_hours: float = Field(default=0, ge=0)
    note: str | None = None

    @field_validator("day_type")
    @classmethod
    def _ovr_type_ok(cls, v: str) -> str:
        if v not in _CALENDAR_DAY_TYPES:
            raise ValueError(f"day_type must be one of {_CALENDAR_DAY_TYPES}")
        return v


class CalendarWorkingDaysQuery(BaseModel):
    """Порт Query(start, end) роутера ``GET /calendar/working-days``."""

    start: date
    end: date


class CalendarYearQuery(BaseModel):
    """Порт Query(year) роутера ``GET /calendar/``.

    Границы как у ``TimeMonthlyReportQuery.year``: ответ — 365 строк на год, и
    ``year=0``/``year=999999`` роняли бы ``date(year, 1, 1)`` вместо 422.
    """

    year: int = Field(..., ge=2000, le=2100)


class EmployeeCalendarQuery(BaseModel):
    """Порт Query(start, end) роутера ``GET /employees/{id}/calendar``."""

    start: date
    end: date


# ── docs — порт services/hr/app/api/v1/{documents,mongo_documents}.py ───────
#
# DocumentOut/HRDocumentOut (формы ответов) здесь не описываются — как и
# везде в этом файле, их собирают сериализаторы apps/hr/services/
# document_service.py.

class DocumentCreate(BaseModel):
    """Порт schemas/document.py::DocumentBase + DocumentCreate.

    ``metadata_``/``alias="metadata"`` — буквальный порт: исходник называет
    атрибут ``metadata_`` только из-за резервирования ``metadata`` в
    SQLAlchemy ``DeclarativeBase`` (см. models.py::Document docstring); здесь
    это сохранено на уровне wire-контракта (клиент шлёт JSON-ключ
    ``"metadata"``), хотя модель Django поле называет просто ``metadata``.
    """

    employee_id: int
    title: str = Field(..., max_length=255)
    doc_type: str = Field(..., max_length=50)
    file_path: str = Field(..., max_length=500)
    file_size: int = Field(..., gt=0)
    mime_type: str = Field(default="application/octet-stream", max_length=100)
    metadata_: dict | None = Field(default=None, alias="metadata")
    uploaded_by: int

    model_config = {"populate_by_name": True}


class DocumentPatch(BaseModel):
    """Тело ``PATCH /documents/{id}/`` — сверх контракта порта.

    Исходник правку документа не поддерживал (только create/get/delete), но
    фронт всегда показывал диалог редактирования. Редактируем метаданные
    карточки, а не сам файл: ``description`` уезжает в JSONB ``metadata``
    (колонки под него нет), ``title``/``doc_type`` — обычные колонки.
    """

    title: str | None = Field(default=None, max_length=255)
    doc_type: str | None = Field(default=None, max_length=50)
    description: str | None = None


class DocumentListQuery(BaseModel):
    """Порт Query(page, limit) роутера ``GET /documents/``."""

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=200)


# Схемы ex-Mongo документов (HRDocType/HRDocumentCreate/HRDocumentUpdate/
# MongoDocumentListQuery) удалены вместе с маршрутами /mongo-documents/* —
# см. комментарий в views.py.


# ── pmo — порт services/hr/app/api/v1/pmo.py (схемы были inline в роутере) ──

PMOStatusLiteral = Literal["active", "suspended", "closed"]
PMOMembershipTypeLiteral = Literal["permanent", "assigned", "consulting"]


class PMOCreate(BaseModel):
    name: str = Field(..., max_length=200)
    code: str = Field(..., max_length=50)
    description: str | None = None
    head_employee_id: int | None = None
    status: PMOStatusLiteral = "active"


class PMOUpdate(BaseModel):
    """Порт PMOUpdate — все поля опциональны. В отличие от остальных *Update
    схем этого файла, вьюха применяет патч через ``exclude_none`` (буквально
    как исходник роутера: ``body.model_dump(exclude_none=True)``), не
    ``exclude_unset`` — тот же PATCH-контракт, что у Department/Position/…"""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    head_employee_id: int | None = None
    status: PMOStatusLiteral | None = None


class PMOMemberAdd(BaseModel):
    employee_id: int
    membership_type: PMOMembershipTypeLiteral = "permanent"
    position_in_pmo: str | None = Field(default=None, max_length=200)
    allocation_percent: int = Field(default=100, ge=0, le=100)
    is_primary: bool = False
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> "PMOMemberAdd":
        if self.from_date and self.to_date and self.to_date < self.from_date:
            raise ValueError("to_date must be >= from_date")
        return self


class PMOMemberUpdate(BaseModel):
    """Порт MemberUpdate — все поля опциональны, патч через ``exclude_unset``
    (буквально исходник: ``body.model_dump(exclude_unset=True)``, В ОТЛИЧИЕ
    от MemberAdd/PMOUpdate/остальных *Update схем этого файла, которые
    используют ``exclude_none``) — сервис вызывающая сторона обязана
    вызывать ``model_dump(exclude_unset=True)``, не ``exclude_none``."""

    employee_id: int | None = None
    membership_type: PMOMembershipTypeLiteral | None = None
    position_in_pmo: str | None = Field(default=None, max_length=200)
    allocation_percent: int | None = Field(default=None, ge=0, le=100)
    is_primary: bool | None = None
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> "PMOMemberUpdate":
        if self.from_date and self.to_date and self.to_date < self.from_date:
            raise ValueError("to_date must be >= from_date")
        return self


# ── employee_card — порт services/hr/app/schemas/employee_card.py +
# employee_card_groups.py (Т-2 карточка сотрудника) ─────────────────────────
#
# Секции PATCH /card/t2 сериализуют денежные поля СТРОКОЙ (Decimal -> str) —
# та же форма, что читает EmployeeCardT2Patch исходника; сама валюта/точность
# проверяется сервисом (employee_card_t2_service.upsert), не схемой.

class CardFinancial(BaseModel):
    salary: str | None = None
    bonus: str | None = None
    bank_account: str | None = None


class CardPersonal(BaseModel):
    passport_data: str | None = None
    inn: str | None = None
    birth_date: date | None = None
    birth_place: str | None = None
    citizenship: str | None = None


class EmployeeCardT2Patch(BaseModel):
    financial: CardFinancial | None = None
    personal: CardPersonal | None = None


class EmployeeCreateRequest(EmployeeCreate):
    """Тело ``POST /employees/`` — колонки Employee + опциональный блок Т-2.

    Отдельная схема, а не поле в ``EmployeeCreate``: сервис
    ``employee_service.create_employee`` разворачивает схему в
    ``Employee.objects.create(**data.model_dump())``, и лишний ключ там
    фатален. Вьюха пересобирает чистый ``EmployeeCreate`` перед вызовом
    сервиса.
    """

    card_t2: EmployeeCardT2Patch | None = None


class EmployeeUpdateRequest(EmployeeUpdate):
    """Тело ``PUT|PATCH /employees/{id}/`` — то же для правки."""

    card_t2: EmployeeCardT2Patch | None = None


class EducationItem(BaseModel):
    institution: str = ""
    degree: str = ""
    field: str = ""
    year_from: int | None = None
    year_to: int | None = None


class ExperienceItem(BaseModel):
    org: str = ""
    position: str = ""
    date_from: date | None = None
    date_to: date | None = None
    note: str = ""


class RelativeItem(BaseModel):
    relation: str = ""
    full_name: str = ""
    birth_date: date | None = None
    note: str = ""


class EmployeeGroupsIn(BaseModel):
    """Порт схемы ``EmployeeGroups`` исходника (``employee_card_groups.py``).

    Переименовано в ``EmployeeGroupsIn`` (не ``EmployeeGroups``) только чтобы
    не тенить уже существующую ``apps.hr.models.EmployeeGroups`` (JSONB-
    модель под-модуля docs) — тело схемы идентично исходнику 1:1.
    """

    education: list[EducationItem] = []
    experience: list[ExperienceItem] = []
    relatives: list[RelativeItem] = []


# ═══════════════════════════════════════════════════════════════════════════
#  final: share_links + department_files + audit + internal — порт
#  services/hr/app/schemas/{shareable_link (inline в роутере),
#  department_file}.py + query-параметры audit.py/internal.py.
# ═══════════════════════════════════════════════════════════════════════════

ShareLinkTypeLiteral = Literal["one_time", "time_limited", "permanent_with_expiry"]
ShareLinkLanguageLiteral = Literal["ru", "en"]
ShareLinkTargetTypeLiteral = Literal["org", "employee"]


class ShareLinkCreate(BaseModel):
    """Порт ``share_links.py::LinkCreate`` (схема объявлена inline в роутере
    исходника, не в отдельном schemas-модуле — сюда переносится буквально)."""

    label: str | None = Field(default=None, max_length=200)
    viewer_label: str | None = Field(default=None, max_length=64)
    watermark_text: str | None = Field(default=None, max_length=128)
    max_level: int = Field(default=3, ge=1, le=10)
    default_language: ShareLinkLanguageLiteral = "ru"
    visible_units: list[int] | None = None
    link_type: ShareLinkTypeLiteral = "one_time"
    expires_at: datetime | None = None
    # target_type='employee' требует target_employee_id (проверка в сервисе —
    # схема сама по себе не может выразить conditional-required буквально
    # как исходник, который тоже проверяет это в роутере, не в pydantic).
    target_type: ShareLinkTargetTypeLiteral = "org"
    target_employee_id: int | None = None


class DepartmentFileFolderCreate(BaseModel):
    """Порт schemas/department_file.py::DepartmentFileFolderCreate."""

    department: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=255)


class DepartmentQuery(BaseModel):
    """Query-параметр ``department`` — GET /department-file-folders/."""

    department: int = Field(..., ge=1)


class DepartmentFileListQuery(BaseModel):
    """Query-параметры GET /department-files/."""

    folder: int = Field(..., ge=1)
    file_folder: int | None = Field(default=None, ge=1)
    root_only: bool = False


class DepartmentFileSearchQuery(BaseModel):
    """Query-параметры GET /department-files/search/."""

    q: str = Field(..., min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


class AuditLogQuery(BaseModel):
    """Query-параметры GET /logs/ (порт audit.py — Query-параметры роутера)."""

    entity_type: str | None = None
    entity_id: int | None = None
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=500)
