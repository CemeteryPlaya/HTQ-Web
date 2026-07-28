"""Pydantic-схемы HTTP-слоя аппки ``signoff``.

``api_view`` валидирует тело запроса схемой из ``body=`` и сериализует
возвращённую схему в ответ (см. ``htqweb/http.py``).

Соглашение по PATCH-схемам общее для репозитория: все поля
``Optional[...] = None``, и ``None`` означает «поле не пришло», а не
«обнулить».
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.signoff.models import ProcessState, Quorum, StageState, TaskState

_ORM = ConfigDict(from_attributes=True)


# ── Маршруты ────────────────────────────────────────────────────────────

class RouteCreate(BaseModel):
    subject_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=200)
    is_active: bool = True


class RouteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    is_active: Optional[bool] = None


class StageCreate(BaseModel):
    """Этап маршрута вместе со списком согласующих.

    ``approver_ids`` принимается прямо здесь, а не отдельным запросом на
    каждого: этап без согласующих нельзя исполнить (``engine._resolve_stages``
    отказывает на запуске), так что создавать его отдельно от людей значило
    бы штатно проходить через заведомо нерабочее состояние.
    """

    order: int = Field(1, ge=1, le=999)
    name: str = Field(..., min_length=1, max_length=200)
    quorum: Quorum = Quorum.ALL
    approver_ids: list[int] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _unique_approvers(self):
        if len(set(self.approver_ids)) != len(self.approver_ids):
            raise ValueError("согласующие в этапе повторяются")
        return self


class StageUpdate(BaseModel):
    order: Optional[int] = Field(None, ge=1, le=999)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    quorum: Optional[Quorum] = None
    # None — «не трогать список»; пустой список запрещён отдельной проверкой
    # в сервисе, чтобы не молча получить неисполнимый этап.
    approver_ids: Optional[list[int]] = None


class ApproverRead(BaseModel):
    user_id: int
    # Разворачивается через apps.users.interface — фронтенду нужно показать
    # человека, а не число.
    full_name: str = ""
    is_active: bool = True


class StageRead(BaseModel):
    id: int
    order: int
    name: str
    quorum: str
    approvers: list[ApproverRead]


class RouteRead(BaseModel):
    id: int
    subject_type: str
    name: str
    is_active: bool
    stages: list[StageRead]
    created_at: datetime
    updated_at: datetime


# ── Процессы ────────────────────────────────────────────────────────────

class ProcessStart(BaseModel):
    subject_type: str = Field(..., min_length=1, max_length=64)
    subject_id: int
    initiator_id: Optional[int] = None


class TaskRead(BaseModel):
    id: int
    user_id: int
    full_name: str = ""
    state: TaskState
    comment: str
    acted_at: Optional[datetime]


class ProcessStageRead(BaseModel):
    id: int
    order: int
    name: str
    quorum: str
    state: StageState
    decided_at: Optional[datetime]
    tasks: list[TaskRead]


class ProcessRead(BaseModel):
    id: int
    subject_type: str
    subject_id: int
    state: ProcessState
    initiator_id: Optional[int]
    current_order: Optional[int]
    created_at: datetime
    finished_at: Optional[datetime]
    stages: list[ProcessStageRead]
    # Карточка предметного объекта — из describe() его аппки. signoff не
    # умеет её построить сам и не должен.
    subject_title: Optional[str] = None
    subject_url: Optional[str] = None


# ── Решения ─────────────────────────────────────────────────────────────

class Decision(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    comment: str = Field("", max_length=2000)


class InboxItem(BaseModel):
    """Строка списка «ждёт моего решения»."""

    task_id: int
    process_id: int
    subject_type: str
    subject_id: int
    subject_title: Optional[str]
    subject_url: Optional[str]
    stage_name: str
    quorum: str
    initiator_id: Optional[int]
    created_at: datetime


class SubjectRead(BaseModel):
    """Согласуемый тип — для настройки маршрута."""

    subject_type: str
    label: str
    has_active_route: bool
