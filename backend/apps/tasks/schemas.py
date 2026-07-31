"""Pydantic schemas for the tasks domain.

Ported from ``services/task/app/schemas/*.py``. Per PLAN.md §3 the schemas
come across as-is — they ARE the response contract, and the whole point of
the port is that a client cannot tell which backend answered. Where the
original imported a SQLAlchemy enum (``Status``, ``Priority``,
``ProjectStatus``, ``LinkType``, ``AssigneeRole``) this imports the
equivalent ``TextChoices`` from ``apps.tasks.models``; both serialise to the
same string values, so the wire format is unchanged.

Two shape decisions worth stating, because they look like drift and are not:

* ``TaskListResponse``/``TaskDetailResponse`` keep every denormalised
  ``*_name`` field (``assignee_name``, ``department_name``, …). The original
  filled them from SQLAlchemy relationship properties on the replica tables;
  with the replicas gone (Р2) they are filled by
  ``apps.tasks.services.hydration``. Same fields, same nullability — a
  missing user still yields ``None``, exactly as a lagging replica did.
* ``LinkResponse.created_at`` is typed ``str``, not ``datetime``. That is
  what the FastAPI original declares, and pydantic therefore emitted the
  ``str()`` of the datetime rather than an ISO-8601 ``datetime``. Kept
  deliberately: "byte-for-byte" beats "more correct" here.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import (
    AssigneeRole, BlockStatus, ContractorLevel, ContractorStatus,
    EquipmentOwnership, LinkType, Priority, ProjectStatus, ResourceKind,
    RoadmapStatus, SiteStatus, Status, WorkVolumeUnit,
)


# ── common ──────────────────────────────────────────────────────────────

class DateWarning(BaseModel):
    """Date-calculation warning attached to a task response."""

    code: str
    message: str


class ContractorRef(BaseModel):
    """Подрядчик в карточке задачи — только то, что рисует чип."""

    id: int
    name: str


# ── labels ──────────────────────────────────────────────────────────────

class LabelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#808080", pattern=r"^#[0-9A-Fa-f]{6}$")


class LabelUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class LabelResponse(BaseModel):
    id: int
    name: str
    color: str

    model_config = {"from_attributes": True}


# ── task types ──────────────────────────────────────────────────────────

SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


class TaskTypeCreate(BaseModel):
    # Optional — when omitted the service auto-generates it from ``name``
    # (transliterating Cyrillic and de-duplicating).
    slug: str | None = Field(default=None, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#6b7280", max_length=20)
    icon: str | None = Field(default=None, max_length=50)

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if not v:
            return None
        if not SLUG_RE.match(v):
            raise ValueError("Slug must contain only lowercase letters, digits, _ and -")
        return v


class TaskTypeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = Field(None, max_length=20)
    icon: str | None = Field(None, max_length=50)
    # slug is intentionally NOT editable — it is the stable identifier the
    # historical UI and the phase-10 ETL both key on.


class TaskTypeResponse(BaseModel):
    id: int
    slug: str
    name: str
    color: str
    icon: str | None = None
    is_system: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── comments / attachments / activity ───────────────────────────────────

class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Comment body cannot be blank")
        return v


class CommentUpdate(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)


class CommentResponse(BaseModel):
    id: int
    task_id: int
    author_id: int | None = None
    author_name: str | None = None
    body: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AttachmentResponse(BaseModel):
    id: int
    task_id: int
    file_path: str
    filename: str
    uploaded_by_id: int | None = None
    uploaded_by_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityResponse(BaseModel):
    id: int
    task_id: int
    actor_id: int | None = None
    actor_name: str | None = None
    field_name: str
    old_value: str | None = None
    new_value: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── links ───────────────────────────────────────────────────────────────

class LinkCreate(BaseModel):
    source_id: int
    target_id: int
    link_type: LinkType

    @model_validator(mode="after")
    def prevent_self_reference(self) -> "LinkCreate":
        if self.source_id == self.target_id:
            raise ValueError("Task cannot link to itself")
        return self


class LinkResponse(BaseModel):
    id: int
    source_id: int
    target_id: int
    link_type: LinkType
    created_by_id: int | None = None

    source_key: str | None = None
    source_summary: str | None = None
    target_key: str | None = None
    target_summary: str | None = None

    # ``str``, not ``datetime`` — see the module docstring.
    created_at: str

    model_config = {"from_attributes": True}


# ── projects ────────────────────────────────────────────────────────────

# ── contractors (субподрядчики) ─────────────────────────────────────────
#
# Домен новый. Уровень (junior/middle/senior) — свойство ЧЕЛОВЕКА, а не
# организации, и на этом этапе он только хранится: правами он начнёт
# управлять вместе с учётными записями, для которых уже заведено
# ``ContractorWorker.user_id``.


class ContractorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    short_name: str | None = Field(None, max_length=100)
    bin_iin: str | None = Field(None, min_length=12, max_length=12,
                                pattern=r"^\d{12}$")
    contact_person: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=32)
    email: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=500)
    notes: str = Field(default="", max_length=5000)
    status: ContractorStatus = Field(default=ContractorStatus.ACTIVE)


class ContractorUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    short_name: str | None = Field(None, max_length=100)
    bin_iin: str | None = Field(None, min_length=12, max_length=12,
                                pattern=r"^\d{12}$")
    contact_person: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=32)
    email: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=5000)
    status: ContractorStatus | None = None


class ContractorResponse(BaseModel):
    id: int
    name: str
    short_name: str | None = None
    bin_iin: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str
    status: ContractorStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContractorWorkerCreate(BaseModel):
    last_name: str = Field(..., min_length=1, max_length=100)
    first_name: str = Field(..., min_length=1, max_length=100)
    middle_name: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=32)
    email: str | None = Field(None, max_length=255)
    position_title: str | None = Field(None, max_length=200)
    level: ContractorLevel = Field(default=ContractorLevel.JUNIOR)


class ContractorWorkerUpdate(BaseModel):
    last_name: str | None = Field(None, min_length=1, max_length=100)
    first_name: str | None = Field(None, min_length=1, max_length=100)
    middle_name: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=32)
    email: str | None = Field(None, max_length=255)
    position_title: str | None = Field(None, max_length=200)
    level: ContractorLevel | None = None
    is_active: bool | None = None
    # ``user_id`` намеренно НЕ редактируется через API: привязка аккаунта —
    # это выдача доступа, а не правка карточки, и появится она вместе с
    # самим механизмом входа.


class ContractorWorkerResponse(BaseModel):
    id: int
    contractor_id: int
    contractor_name: str
    last_name: str
    first_name: str
    middle_name: str | None = None
    full_name: str
    phone: str | None = None
    email: str | None = None
    position_title: str | None = None
    level: ContractorLevel
    user_id: int | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContractorEngagementCreate(BaseModel):
    contractor_id: int
    project_id: int | None = None
    site_id: int | None = None
    # Привлечение на один пакет работ: «развозку валов отдали субподряду,
    # монтаж делаем сами». Третья стрелка в «Субподряд» на схеме.
    roadmap_id: int | None = None
    contract_no: str | None = Field(None, max_length=64)
    scope: str = Field(default="", max_length=5000)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def target_required(self) -> "ContractorEngagementCreate":
        if (self.project_id is None and self.site_id is None
                and self.roadmap_id is None):
            raise ValueError(
                "Укажите проект, объект или роудмап (хотя бы одно)")
        return self


class ContractorEngagementUpdate(BaseModel):
    project_id: int | None = None
    site_id: int | None = None
    roadmap_id: int | None = None
    contract_no: str | None = Field(None, max_length=64)
    scope: str | None = Field(None, max_length=5000)
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool | None = None


class ContractorEngagementResponse(BaseModel):
    id: int
    contractor_id: int
    contractor_name: str
    project_id: int | None = None
    project_name: str | None = None
    site_id: int | None = None
    site_name: str | None = None
    roadmap_id: int | None = None
    roadmap_name: str | None = None
    contract_no: str | None = None
    scope: str
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── sites (объекты/площадки) ────────────────────────────────────────────
#
# Домен новый: FastAPI-оригинала у него нет, поэтому формы здесь заданы, а
# не воспроизведены. Стиль скопирован с проектов — та же ось планирования.


class SiteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str | None = Field(None, max_length=32)
    description: str = Field(default="", max_length=5000)
    address: str | None = Field(None, max_length=500)
    region: str | None = Field(None, max_length=120)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    status: SiteStatus = Field(default=SiteStatus.ACTIVE)
    color: str = Field(default="#0ea5e9", max_length=20)
    department_id: int | None = None
    manager_id: int | None = None


class SiteUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    code: str | None = Field(None, max_length=32)
    description: str | None = Field(None, max_length=5000)
    address: str | None = Field(None, max_length=500)
    region: str | None = Field(None, max_length=120)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    status: SiteStatus | None = None
    color: str | None = Field(None, max_length=20)
    department_id: int | None = None
    manager_id: int | None = None


class SiteResponse(BaseModel):
    id: int
    name: str
    code: str | None = None
    description: str
    address: str | None = None
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: SiteStatus
    color: str
    department_id: int | None = None
    manager_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VolumeEntry(BaseModel):
    """Одна строка ПЛАНОВОГО объёма работ. Общая для блока и для задачи.

    Факта здесь нет ни у той, ни у другой: он приходит ежедневными отчётами
    (``DailyReport``), у которых есть дата выполнения и автор.
    """

    volume_type_id: int
    planned_quantity: Decimal = Field(..., ge=0, max_digits=12,
                                      decimal_places=2)


class VolumeResponse(BaseModel):
    id: int
    volume_type_id: int
    volume_type_name: str
    unit: WorkVolumeUnit
    planned_quantity: float


class TaskVolumeResponse(VolumeResponse):
    task_id: int
    # Свёртка отчётов задачи, а не колонка: считается на лету.
    completed_quantity: float


class VolumesUpdate(BaseModel):
    """Замена набора объёмов целиком — и у блока, и у задачи."""

    volumes: list[VolumeEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def volume_types_are_unique(self) -> "VolumesUpdate":
        # Иначе последний дубль молча затирал бы предыдущий в
        # ``update_or_create``, и форма показала бы не то, что отправила.
        seen = [v.volume_type_id for v in self.volumes]
        if len(seen) != len(set(seen)):
            raise ValueError("Вид объёма работ указан дважды")
        return self


class SiteBlockCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    code: str | None = Field(None, max_length=32)
    order: int = Field(default=0, ge=0, le=32767)
    status: BlockStatus = Field(default=BlockStatus.PLANNED)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "SiteBlockCreate":
        # Дублирует ck_site_block_dates сознательно — тот же приём, что у
        # EquipmentCreate: здесь это 422 с текстом, а не IntegrityError→500.
        if (self.start_date and self.end_date
                and self.start_date > self.end_date):
            raise ValueError("Дата начала позже даты окончания")
        return self


class SiteBlockUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    code: str | None = Field(None, max_length=32)
    order: int | None = Field(None, ge=0, le=32767)
    status: BlockStatus | None = None
    start_date: date | None = None
    end_date: date | None = None


class SiteBlockResponse(BaseModel):
    id: int
    site_id: int
    name: str
    code: str | None = None
    order: int
    status: BlockStatus
    start_date: date | None = None
    end_date: date | None = None
    volumes: list[VolumeResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BlockVolumeProgressItem(BaseModel):
    volume_type_id: int
    volume_type_name: str
    unit: WorkVolumeUnit
    planned_quantity: float
    completed_quantity: float
    # None, когда план нулевой: делить не на что, и 0% тут значило бы «не
    # начинали», что неправда.
    percent: float | None = None


class BlockProgressResponse(BaseModel):
    block_id: int
    items: list[BlockVolumeProgressItem]
    percent: float | None = None


class ProjectSiteRef(BaseModel):
    """Объект в карточке проекта — не полный ``SiteResponse``.

    Списку проектов нужны только имя и цвет для чипа; тянуть адрес и
    координаты в каждую строку роадмапа незачем.
    """

    id: int
    name: str
    color: str
    status: SiteStatus
    is_primary: bool = False
    start_date: date | None = None
    end_date: date | None = None


class ProjectSitesUpdate(BaseModel):
    """``PUT projects/{id}/sites`` — замена набора целиком."""

    site_ids: list[int] = Field(default_factory=list)
    primary_site_id: int | None = None


class RoadmapCreate(BaseModel):
    """Роудмап — пакет работ на блоке. Проект и блок обязательны.

    Площадки в теле нет: она следует из блока. Проект блоком НЕ задаётся —
    площадка связана с проектами через M2M, и одна площадка обслуживает
    несколько проектов.
    """

    project_id: int
    site_block_id: int
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    status: RoadmapStatus = Field(default=RoadmapStatus.ACTIVE)
    color: str = Field(default="#8b5cf6", max_length=20)
    order: int = Field(default=0, ge=0, le=32767)
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    planned_working_days: int | None = Field(None, ge=0)
    owner_id: int | None = None
    department_id: int | None = None

    @model_validator(mode="after")
    def planned_dates_are_ordered(self) -> "RoadmapCreate":
        if (self.planned_start_date and self.planned_end_date
                and self.planned_start_date > self.planned_end_date):
            raise ValueError("Плановая дата начала позже даты окончания")
        return self


class RoadmapUpdate(BaseModel):
    project_id: int | None = None
    site_block_id: int | None = None
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    status: RoadmapStatus | None = None
    color: str | None = Field(None, max_length=20)
    order: int | None = Field(None, ge=0, le=32767)
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    planned_working_days: int | None = Field(None, ge=0)
    owner_id: int | None = None
    department_id: int | None = None


class RoadmapResponse(BaseModel):
    id: int
    project_id: int
    project_name: str
    site_block_id: int
    site_block_name: str
    # Площадка — производная от блока, но в ответе есть: без неё фронту
    # пришлось бы ходить за блоком ради имени и цвета чипа.
    site_id: int
    site_name: str
    site_color: str
    name: str
    description: str
    status: RoadmapStatus
    color: str
    order: int
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    planned_working_days: int | None = None
    owner_id: int | None = None
    owner_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    task_count: int = 0
    done_count: int = 0
    progress: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduleComparison(BaseModel):
    """Срок: план против факта. ``delta_working_days`` > 0 — не уложились."""

    planned_start_date: date | None = None
    planned_end_date: date | None = None
    planned_working_days: int | None = None
    actual_start_date: date | None = None
    actual_end_date: date | None = None
    actual_working_days: int | None = None
    delta_working_days: int | None = None


class ResourceComparison(BaseModel):
    """Люди или техника: сколько запланировали против того, сколько заняли.

    ``planned`` — ``None``, когда потребность не заводили: это «плана нет»,
    а не «запланировали ноль», и рисовать их одинаково нельзя.
    """

    planned: int | None = None
    actual: int = 0
    delta: int | None = None


class RoadmapMetricsResponse(BaseModel):
    roadmap_id: int
    task_count: int
    done_count: int
    # None, когда задач нет вовсе: «пакет пустой» ≠ «не начинали».
    progress: float | None = None
    schedule: ScheduleComparison
    human: ResourceComparison
    equipment: ResourceComparison


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    status: ProjectStatus = Field(default=ProjectStatus.ACTIVE)
    color: str = Field(default="#3b82f6", max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    owner_id: int | None = None
    department_id: int | None = None
    # False = календарные дни (стройка идёт 7/7), True = рабочие.
    use_production_calendar: bool = False


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    status: ProjectStatus | None = None
    color: str | None = Field(None, max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    owner_id: int | None = None
    department_id: int | None = None
    use_production_calendar: bool | None = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str
    status: ProjectStatus
    color: str
    start_date: date | None
    end_date: date | None
    owner_id: int | None = None
    owner_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    sites: list[ProjectSiteRef] = []
    site_ids: list[int] = []
    use_production_calendar: bool = False
    task_count: int = 0
    done_count: int = 0
    progress: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── tasks ───────────────────────────────────────────────────────────────

class DepartmentRef(BaseModel):
    """Compact department reference for multi-department task responses."""

    id: int
    name: str

    model_config = {"from_attributes": True}


class AssigneeAssignment(BaseModel):
    """One row of the task-assignee junction, as sent by a client."""

    user_id: int
    role: AssigneeRole = AssigneeRole.COLLABORATOR


class AssigneeResponse(BaseModel):
    user_id: int
    role: AssigneeRole
    name: str | None = None
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


class DelegateResponse(BaseModel):
    user_id: int
    name: str | None = None
    avatar_url: str | None = None
    granted_by_id: int | None = None
    granted_by_name: str | None = None
    granted_at: datetime | None = None

    model_config = {"from_attributes": True}


class WatcherResponse(BaseModel):
    user_id: int
    name: str | None = None
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    summary: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    # Type by FK to the registry, or by slug (resolved server-side). The
    # legacy ``task_type`` string is also accepted for backward-compat.
    task_type_id: int | None = None
    task_type: str | None = None
    priority: Priority = Field(default=Priority.MEDIUM)
    status: Status = Field(default=Status.TODO)

    reporter_id: int | None = None
    supervisor_id: int | None = None
    department_id: int | None = None
    # Multi-department. The first id (or ``department_id``) becomes the
    # primary; the full set is persisted in the junction.
    department_ids: list[int] = Field(default_factory=list)
    # None means a standalone task — explicitly chosen in the create dialog.
    project_id: int | None = None
    # Пакет работ. Если прислан, он ЗАДАЁТ проект и объект задачи —
    # присланные рядом project_id/site_id проигрывают ему, а не конфликтуют.
    roadmap_id: int | None = None
    # Объект работ. Если у проекта ровно один объект и site_id не прислан,
    # сервис наследует его; если объект не относится к проекту — 400.
    site_id: int | None = None
    # Блок объекта — «на блок I». Если объект не прислан, он выводится из
    # блока; если блок не принадлежит объекту задачи — 400.
    site_block_id: int | None = None
    # Кто выполняет. Оба None = своя команда.
    contractor_id: int | None = None
    contractor_worker_id: int | None = None
    parent_id: int | None = None

    # If both ``assignee_id`` (legacy) and ``assignees`` arrive, the service
    # builds the final crew by union.
    assignee_id: int | None = None
    assignees: list[AssigneeAssignment] = Field(default_factory=list)

    label_ids: list[int] = Field(default_factory=list)

    progress_percent: int = Field(default=0, ge=0, le=100)
    due_date: date | None = None
    start_date: date | None = None
    estimated_working_days: int | None = None

    @field_validator("summary")
    @classmethod
    def summary_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Summary cannot be blank")
        return v


class TaskUpdate(BaseModel):
    """Partial update. Unset fields are left alone (``exclude_unset``).

    ``assignees`` / ``delegates`` / ``watchers`` have dedicated endpoints and
    are read-only here.
    """

    summary: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    task_type_id: int | None = None
    task_type: str | None = None
    priority: Priority | None = None
    status: Status | None = None

    reporter_id: int | None = None
    assignee_id: int | None = None
    supervisor_id: int | None = None
    department_id: int | None = None
    department_ids: list[int] | None = None
    project_id: int | None = None
    roadmap_id: int | None = None
    site_id: int | None = None
    site_block_id: int | None = None
    contractor_id: int | None = None
    contractor_worker_id: int | None = None
    parent_id: int | None = None

    label_ids: list[int] | None = None

    progress_percent: int | None = Field(None, ge=0, le=100)
    due_date: date | None = None
    start_date: date | None = None
    estimated_working_days: int | None = None


class AssigneesUpdate(BaseModel):
    """Body for PATCH /tasks/{id}/assignees/ — replaces the whole crew."""

    assignees: list[AssigneeAssignment]

    @field_validator("assignees")
    @classmethod
    def at_most_one_primary(cls, v: list[AssigneeAssignment]) -> list[AssigneeAssignment]:
        primaries = [a for a in v if a.role == AssigneeRole.PRIMARY]
        if len(primaries) > 1:
            raise ValueError("At most one assignee may have role=primary")
        return v


class SupervisorUpdate(BaseModel):
    user_id: int | None = None


class DelegateCreate(BaseModel):
    user_id: int


class ProgressUpdate(BaseModel):
    percent: int = Field(..., ge=0, le=100)


class TaskListResponse(BaseModel):
    """Compact task response for list views."""

    id: int
    key: str
    summary: str
    # ``task_type`` carries the slug of the related registry row;
    # ``task_type_id`` is the FK for clients that edit by id.
    task_type_id: int | None = None
    task_type: str = "task"
    task_type_name: str | None = None
    task_type_color: str | None = None
    priority: Priority
    status: Status
    progress_percent: int = 0

    reporter_id: int | None = None
    reporter_name: str | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    supervisor_id: int | None = None
    supervisor_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    department_ids: list[int] = []
    departments: list[DepartmentRef] = []
    project_id: int | None = None
    project_name: str | None = None
    project_color: str | None = None
    roadmap_id: int | None = None
    roadmap_name: str | None = None
    roadmap_color: str | None = None
    site_id: int | None = None
    site_name: str | None = None
    site_color: str | None = None
    site_block_id: int | None = None
    site_block_name: str | None = None
    contractor_id: int | None = None
    contractor_name: str | None = None
    # Унаследованный с роудмапа/площадки/проекта, если своего нет.
    # None = своя команда.
    effective_contractor: ContractorRef | None = None
    contractor_worker_id: int | None = None
    contractor_worker_name: str | None = None
    parent_id: int | None = None
    parent_key: str | None = None

    assignees: list[AssigneeResponse] = []
    labels: list[LabelResponse] = []
    due_date: date | None = None
    start_date: date | None = None
    effective_start_date: date | None = None
    effective_due_date: date | None = None
    date_warnings: list[DateWarning] = []
    completed_at: datetime | None = None

    subtask_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskDetailResponse(BaseModel):
    """Detailed task response with nested data."""

    id: int
    key: str
    summary: str
    description: str
    task_type_id: int | None = None
    task_type: str = "task"
    task_type_name: str | None = None
    task_type_color: str | None = None
    priority: Priority
    status: Status
    progress_percent: int = 0

    reporter_id: int | None = None
    reporter_name: str | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    supervisor_id: int | None = None
    supervisor_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    department_ids: list[int] = []
    departments: list[DepartmentRef] = []
    project_id: int | None = None
    project_name: str | None = None
    project_color: str | None = None
    roadmap_id: int | None = None
    roadmap_name: str | None = None
    roadmap_color: str | None = None
    site_id: int | None = None
    site_name: str | None = None
    site_color: str | None = None
    site_block_id: int | None = None
    site_block_name: str | None = None
    contractor_id: int | None = None
    contractor_name: str | None = None
    # Унаследованный с роудмапа/площадки/проекта, если своего нет.
    # None = своя команда.
    effective_contractor: ContractorRef | None = None
    contractor_worker_id: int | None = None
    contractor_worker_name: str | None = None
    parent_id: int | None = None
    parent_key: str | None = None

    assignees: list[AssigneeResponse] = []
    delegates: list[DelegateResponse] = []
    watchers: list[WatcherResponse] = []

    labels: list[LabelResponse] = []
    label_ids: list[int] = Field(default=[], description="Write-only label IDs")

    due_date: date | None = None
    start_date: date | None = None
    effective_start_date: date | None = None
    effective_due_date: date | None = None
    date_warnings: list[DateWarning] = []
    completed_at: datetime | None = None

    volumes: list[TaskVolumeResponse] = []

    comments: list[CommentResponse] = []
    attachments: list[AttachmentResponse] = []
    subtasks: list["TaskListResponse"] = []
    activities: list[ActivityResponse] = []
    outgoing_links: list[LinkResponse] = []
    incoming_links: list[LinkResponse] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_type: dict[str, int]
    by_department: list[dict]
    by_project: list[dict]
    by_site: list[dict]
    by_assignee: list[dict]
    created_per_day: list[dict]
    resolved_per_day: list[dict]


# ── notifications ───────────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    """``target_type`` + ``target_id`` is the canonical "click here"
    reference; the frontend maps the type to a route, so the backend stays
    free of UI knowledge. ``task_key`` is filled when the row references a
    task (legacy ``task_id`` FK OR ``target_type='task'``) so the dropdown
    can show «В задаче: ABC-123» without a second roundtrip."""

    id: int
    recipient_id: int
    actor_id: int | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    verb: str
    task_id: int | None = None
    task_key: str | None = None
    target_type: str | None = None
    target_id: int | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationsPage(BaseModel):
    items: list[NotificationResponse]
    total: int
    page: int
    pages: int
    limit: int
    unread_total: int


# ── gantt / equipment / assignments ─────────────────────────────────────

class GanttTask(BaseModel):
    """One bar in the report Gantt. Flat list; hierarchy via ``parent``."""

    id: str
    key: str
    text: str
    start_date: date | None = None
    end_date: date | None = None
    progress: float = 0.0
    status: str
    parent: str | None = None
    assignees: list[str] = []


class ReportsGanttResponse(BaseModel):
    tasks: list[GanttTask]


class AllocatedTask(BaseModel):
    task_id: str
    key: str
    title: str
    start_date: date | None = None
    end_date: date | None = None
    progress: float = 0.0
    status: str
    allocation: int = 100


class ResourceRow(BaseModel):
    resource_id: str                 # e.g. "emp_8" / "eq_3"
    resource_kind: str               # "employee" | "equipment"
    resource_name: str
    meta: dict = Field(default_factory=dict)
    allocated_tasks: list[AllocatedTask] = []


class ResourceGanttResponse(BaseModel):
    range: dict
    resources: list[ResourceRow]


class ReferenceRowCreate(BaseModel):
    """Общая форма для плоских справочников: типы техники, роли, виды объёмов.

    ``slug`` необязателен — сервис сгенерирует его из имени тем же
    транслитератором, что и у типов задач, так что «Вилопогрузчик»
    превращается в ``vilopogruzchik``, а не в пустую строку.
    """

    name: str = Field(..., min_length=1, max_length=100)
    slug: str | None = Field(None, min_length=1, max_length=50)


class ReferenceRowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    is_active: bool | None = None


class ReferenceRowResponse(BaseModel):
    id: int
    slug: str
    name: str
    is_active: bool


class VolumeTypeCreate(ReferenceRowCreate):
    unit: WorkVolumeUnit = Field(default=WorkVolumeUnit.PIECE)


class VolumeTypeUpdate(ReferenceRowUpdate):
    unit: WorkVolumeUnit | None = None


class VolumeTypeResponse(ReferenceRowResponse):
    unit: WorkVolumeUnit


class EquipmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    inventory_no: str | None = Field(None, max_length=50)
    # Два пути к одной категории: ``category_id`` — выпадающий список,
    # ``category`` строкой — легаси-путь опубликованного контракта, который
    # фронт использует до сих пор. При обоих заполненных выигрывает id.
    category: str | None = Field(None, max_length=100)
    category_id: int | None = None
    ownership: EquipmentOwnership = Field(default=EquipmentOwnership.OWN)
    contractor_id: int | None = None

    @model_validator(mode="after")
    def contractor_required_for_contractor_owned(self) -> "EquipmentCreate":
        # Дублирует ck_equipment_contractor_owner сознательно: здесь это 422
        # с человеческим текстом, а не IntegrityError, ставший 500.
        if (self.ownership == EquipmentOwnership.CONTRACTOR
                and self.contractor_id is None):
            raise ValueError("Для техники подрядчика укажите подрядчика")
        return self


class EquipmentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    inventory_no: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=100)
    category_id: int | None = None
    is_active: bool | None = None
    ownership: EquipmentOwnership | None = None
    contractor_id: int | None = None


class EquipmentResponse(BaseModel):
    id: int
    name: str
    inventory_no: str | None = None
    # Строкой — как в оригинальном контракте; за ней теперь справочник, и
    # ``category_id`` рядом отдаёт его строку для выпадающего списка.
    category: str | None = None
    category_id: int | None = None
    is_active: bool
    ownership: EquipmentOwnership
    contractor_id: int | None = None
    contractor_name: str | None = None

    model_config = {"from_attributes": True}


class DailyReportCreate(BaseModel):
    """Ежедневный отчёт: сколько сделали и КОГДА.

    ``volume_type_id`` необязателен: когда у задачи один вид работ, сервис
    подставляет его сам (``daily_report_service.resolve_volume_type``), и
    форма не спрашивает очевидное. При нескольких видах отказывает — угадать
    нельзя.
    """

    volume_type_id: int | None = None
    work_date: date
    quantity: Decimal = Field(..., ge=0, max_digits=12, decimal_places=2)
    headcount: int | None = Field(None, ge=0, le=32767)
    comment: str = Field(default="", max_length=5000)


class DailyReportUpdate(BaseModel):
    # Поле принимается, но менять его нельзя: сервис отвечает 422 с
    # объяснением. Молча выбрасывать его из схемы было бы хуже — клиент
    # получал бы 200 и думал, что вид работ сменился.
    volume_type_id: int | None = None
    work_date: date | None = None
    quantity: Decimal | None = Field(None, ge=0, max_digits=12,
                                     decimal_places=2)
    headcount: int | None = Field(None, ge=0, le=32767)
    comment: str | None = Field(None, max_length=5000)


class DailyReportResponse(BaseModel):
    id: int
    task_id: int
    task_key: str
    volume_type_id: int
    volume_type_name: str
    unit: WorkVolumeUnit
    author_id: int | None = None
    author_name: str | None = None
    # Дата ВЫПОЛНЕНИЯ работ. Не путать с created_at — датой заполнения:
    # отчёт за пятницу заполняют в понедельник, и по дням раскладывается
    # именно work_date.
    work_date: date
    quantity: float
    headcount: int | None = None
    comment: str
    current_revision: int
    created_at: datetime
    updated_at: datetime


class DailyReportBoardVolume(BaseModel):
    """Плановый объём строки сводки вместе с фактом НА ОТЧЁТНУЮ ДАТУ."""

    volume_type_id: int
    volume_type_name: str
    unit: WorkVolumeUnit
    planned_quantity: float
    completed_quantity: float


class DailyReportBoardRow(BaseModel):
    """Задача в сводке ежедневки: где она, сколько осталось, что уже сдано.

    Контекст (объект, блок, пакет) отдаётся строкой, а не идентификатором:
    прораб на этой странице не переходит по ссылкам, он смотрит, куда какая
    цифра идёт, и текст здесь дешевле лишнего запроса за именами.
    """

    task_id: int
    key: str
    summary: str
    status: Status
    project_name: str | None = None
    site_name: str | None = None
    site_block_name: str | None = None
    roadmap_id: int | None = None
    roadmap_name: str | None = None
    due_date: date | None = None
    volumes: list[DailyReportBoardVolume] = Field(default_factory=list)
    # Отчёты именно за выбранную дату. Их может быть несколько: за день
    # бывает несколько смен, и они складываются.
    reports: list[DailyReportResponse] = Field(default_factory=list)


class DailyReportRevisionResponse(BaseModel):
    id: int
    report_id: int
    revision_no: int
    work_date: date
    quantity: float
    headcount: int | None = None
    comment: str
    edited_by_id: int | None = None
    edited_by_name: str | None = None
    edited_at: datetime


class SCurvePoint(BaseModel):
    """Точка S-кривой: накопительные план и факт на дату.

    Оба поля nullable и означают разное. ``plan_cum`` = None — плановых
    дат или объёмов нет, линию плана рисовать не из чего. ``fact_cum`` =
    None — точка ПОСЛЕ отчётной даты: факта там физически нет, и обрыв
    линии честнее её продолжения по горизонтали.
    """

    date: date
    plan_cum: float | None = None
    fact_cum: float | None = None


class PlanFactNode(BaseModel):
    """Узел дерева план/факт. Одна форма на все уровни иерархии.

    Рекурсивная: ``children`` содержит узлы того же типа. Уровень назван в
    ``kind`` (``project``/``site``/``block``/``roadmap``/``task``), а не
    выражен пятью разными схемами — правила расчёта у всех одни, и пять
    почти одинаковых моделей разъехались бы.

    Про ``None`` в числах: он означает «сравнивать не с чем», а не ноль.
    ``plan_pct`` без плановых дат, ``spi`` без плана, ``forecast_end`` при
    нулевом темпе — всё это законные состояния, и подменять их нулём
    значило бы объявить работу просроченной там, где её просто не
    планировали.
    """

    kind: Literal["project", "site", "block", "roadmap", "task"]
    id: int
    name: str

    plan_start_date: date | None = None
    plan_end_date: date | None = None
    plan_pct: float | None = None
    fact_pct: float | None = None
    # Отношение факта к плану. < 0.95 — warning, < 0.90 — critical.
    spi: float | None = None
    # Прогноз по ФАКТИЧЕСКОМУ темпу и по плановому. Разница между ними —
    # цена бездействия.
    forecast_end: date | None = None
    forecast_end_plan_rate: date | None = None
    lag_days: int | None = None
    lag_pct: float | None = None
    flags: list[str] = Field(default_factory=list)

    # Правило взвешивания детей в среднем родителя — возвращается, потому
    # что это предметное решение, а не деталь реализации.
    weighting: str | None = None
    children: list["PlanFactNode"] = Field(default_factory=list)
    series: list[SCurvePoint] = Field(default_factory=list)

    # Поля уровня задачи.
    key: str | None = None
    status: str | None = None
    planned_quantity: float | None = None
    fact_quantity: float | None = None
    rate_per_day: float | None = None
    rate_window_days: int | None = None
    required_rate_ratio: float | None = None
    # Поля уровня роудмапа/проекта.
    task_count: int | None = None
    use_production_calendar: bool | None = None


class EquipmentEngagedRow(BaseModel):
    """Категория техники на дату D: сколько нужно и сколько выделено."""

    category_id: int | None = None
    category_name: str | None = None
    planned: int = 0
    assigned: int = 0


class EquipmentUsageRow(BaseModel):
    """Интервал занятости конкретной машины — строка истории."""

    allocation_id: int
    equipment_id: int
    equipment_name: str
    inventory_no: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    task_id: int | None = None
    task_key: str | None = None
    task_summary: str | None = None
    roadmap_id: int | None = None
    date_from: date
    date_to: date
    days: int


class EquipmentUsageResponse(BaseModel):
    engaged_on: date
    engaged: list[EquipmentEngagedRow]
    history: list[EquipmentUsageRow]


class AssignmentCreate(BaseModel):
    """Именное назначение ресурса на задачу ИЛИ на роудмап.

    ``task_id`` остался необязательным-по-факту, но не по типу: он был
    обязательным в опубликованном контракте, и старый клиент, шлющий только
    его, обязан продолжать работать. Валидатор ниже требует ровно одну цель.
    """

    task_id: int | None = None
    roadmap_id: int | None = None
    requirement_id: int | None = None
    employee_id: int | None = None
    equipment_id: int | None = None
    role: str | None = Field(None, max_length=100)
    allocation: int = Field(100, ge=0, le=100)

    @model_validator(mode="after")
    def exactly_one_target(self) -> "AssignmentCreate":
        if (self.task_id is None) == (self.roadmap_id is None):
            raise ValueError("Укажите ровно одно: task_id или roadmap_id")
        return self


class ResourceRequirementCreate(BaseModel):
    """Потребность количеством: «2 человека», «2 кары».

    ``work_role_id`` и ``equipment_category_id`` необязательны: «нужно
    2 человека, роль не важна» — законный план. Поле «не своего» вида
    сервис обнуляет сам, поэтому переключение вида в форме не ошибка.
    """

    task_id: int | None = None
    roadmap_id: int | None = None
    kind: ResourceKind
    work_role_id: int | None = None
    equipment_category_id: int | None = None
    quantity: int = Field(1, ge=1, le=32767)
    start_date: date | None = None
    end_date: date | None = None
    note: str | None = Field(None, max_length=255)

    @model_validator(mode="after")
    def exactly_one_target(self) -> "ResourceRequirementCreate":
        if (self.task_id is None) == (self.roadmap_id is None):
            raise ValueError("Укажите ровно одно: task_id или roadmap_id")
        if (self.start_date and self.end_date
                and self.start_date > self.end_date):
            raise ValueError("Дата начала позже даты окончания")
        return self


class ResourceRequirementUpdate(BaseModel):
    kind: ResourceKind | None = None
    work_role_id: int | None = None
    equipment_category_id: int | None = None
    quantity: int | None = Field(None, ge=1, le=32767)
    start_date: date | None = None
    end_date: date | None = None
    note: str | None = Field(None, max_length=255)


class ResourceRequirementResponse(BaseModel):
    id: int
    task_id: int | None = None
    roadmap_id: int | None = None
    kind: ResourceKind
    work_role_id: int | None = None
    work_role_name: str | None = None
    equipment_category_id: int | None = None
    equipment_category_name: str | None = None
    quantity: int
    # Сколько мест уже закрыто именными назначениями: «2 кары, назначена 1».
    filled: int = 0
    start_date: date | None = None
    end_date: date | None = None
    note: str | None = None


class AssignmentResponse(BaseModel):
    id: int
    # Стал nullable вместе с переездом назначений на два уровня. Старый
    # клиент, читающий только задачные назначения, разницы не видит.
    task_id: int | None = None
    roadmap_id: int | None = None
    requirement_id: int | None = None
    employee_id: int | None = None
    equipment_id: int | None = None
    role: str | None = None
    allocation: int

    model_config = {"from_attributes": True}


# ── calendar ────────────────────────────────────────────────────────────

EventType = Literal["personal", "department", "common", "conference"]
RsvpStatus = Literal["pending", "accepted", "declined"]
DayType = Literal["working", "weekend", "holiday", "short"]


class EventExceptionBase(BaseModel):
    exception_date: date
    is_cancelled: bool = True


class EventExceptionResponse(EventExceptionBase):
    id: int
    event_id: int

    model_config = {"from_attributes": True}


class CalendarEventBase(BaseModel):
    title: str
    description: str | None = None
    # Precise timestamps. For all-day events the form sends midnight in the
    # user's local tz with ``is_all_day=True``; the UI hides the time.
    start_at: datetime
    end_at: datetime
    is_all_day: bool = True
    event_type: EventType = "personal"
    conference_room_id: str | None = None
    color: str | None = None
    is_global: bool = False
    department_id: int | None = None


class CalendarEventCreate(CalendarEventBase):
    # Users to invite besides the creator. The event then appears on each of
    # their calendars without needing ``is_global``.
    participant_user_ids: list[int] = []

    @field_validator("end_at")
    @classmethod
    def end_after_start(cls, v: datetime, info):
        start = info.data.get("start_at")
        if start is not None and v < start:
            raise ValueError("end_at must be >= start_at")
        return v


class CalendarEventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    is_all_day: bool | None = None
    event_type: EventType | None = None
    conference_room_id: str | None = None
    color: str | None = None
    is_global: bool | None = None
    department_id: int | None = None
    # ``None`` means "do not touch participants"; an empty list clears them.
    participant_user_ids: list[int] | None = None


class CalendarEventParticipantInfo(BaseModel):
    user_id: int
    full_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    rsvp_status: RsvpStatus = "pending"


class CalendarEventResponse(CalendarEventBase):
    id: int
    created_at: datetime
    updated_at: datetime
    creator_id: int | None = None
    exceptions: list[EventExceptionResponse] = []
    participants: list[CalendarEventParticipantInfo] = []

    model_config = {"from_attributes": True}


class RsvpUpdate(BaseModel):
    status: RsvpStatus


class ProductionDayUpdate(BaseModel):
    day_type: DayType
    note: str | None = None


class ProductionDayResponse(BaseModel):
    date: date
    day_type: DayType
    working_days_since_epoch: int
    note: str | None = None

    model_config = {"from_attributes": True}
