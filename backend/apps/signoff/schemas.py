"""Pydantic-схемы HTTP-слоя аппки ``signoff``.

``api_view`` валидирует тело запроса схемой из ``body=`` и сериализует
возвращённую схему в ответ (см. ``htqweb/http.py``).

Соглашение по PATCH-схемам общее для репозитория: все поля
``Optional[...] = None``, и ``None`` означает «поле не пришло», а не
«обнулить».
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.signoff.models import (
    ApproverKind,
    ProcessState,
    Quorum,
    StageState,
    TaskState,
)
from apps.signoff.services.conditions import OPS

_ORM = ConfigDict(from_attributes=True)


# ── Условия ветвления ───────────────────────────────────────────────────

class Predicate(BaseModel):
    """Один предикат условия этапа.

    Форму проверяет схема, СМЫСЛ — ``conditions.validate`` в сервисе: знать,
    что «страна» бывает только из справочника стран, может лишь предметная
    аппка, а pydantic-схема статична и до её ``fact_fields`` не дотянется.

    ``value`` намеренно ``Any``: тип зависит от поля (id страны — число,
    ``in`` — список), и сузить его здесь, не зная поля, нечем.
    """

    field: str = Field(..., min_length=1, max_length=64)
    op: Literal["eq", "in", "not_in", "gt", "gte", "lt", "lte"] = "eq"
    value: Any = None


# Список операторов выписан в ``Literal`` буквально — pydantic должен видеть
# его статически, чтобы отдать 422 с перечислением допустимых значений и
# попасть в OpenAPI. Сверка с единственным источником правды — здесь же, на
# импорте: разойтись эти два списка не должны.
assert set(Predicate.model_fields["op"].annotation.__args__) == set(OPS), \
    "schemas.Predicate.op разошёлся с conditions.OPS"

Condition = list[Predicate]


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
    каждого: этап без согласующих нельзя исполнить (``engine._approver_ids``
    отказывает на запуске), так что создавать его отдельно от людей значило
    бы штатно проходить через заведомо нерабочее состояние.

    Обязательность списка при этом проверяет валидатор, а не
    ``min_length=1``: у этапа, который согласует инициатор, списка нет по
    определению, и требовать его схемой значило бы заставлять фронтенд
    присылать фиктивного человека.
    """

    order: int = Field(1, ge=1, le=999)
    name: str = Field(..., min_length=1, max_length=200)
    quorum: Quorum = Quorum.ALL
    approver_ids: list[int] = Field(default_factory=list)
    # Пустое условие — «этап нужен всегда»; это и есть поведение всех этапов
    # до появления ветвления, поэтому значение по умолчанию именно такое.
    condition: Condition = Field(default_factory=list)
    is_fallback: bool = False
    approver_kind: ApproverKind = ApproverKind.NAMED
    requires_attachment: bool = False

    @model_validator(mode="after")
    def _approvers_match_kind(self):
        if len(set(self.approver_ids)) != len(self.approver_ids):
            raise ValueError("согласующие в этапе повторяются")
        # Смысл сочетаний — в route_service._check_approver_kind; здесь
        # проверяется ровно то, что видно из схемы: список либо нужен, либо
        # неуместен. Дубль осознанный — 422 на форме понятнее, чем 409 из
        # сервиса, а сервис обязан защищаться и без схемы (его зовёт и
        # django-admin).
        if self.approver_kind == ApproverKind.NAMED and not self.approver_ids:
            raise ValueError("нужен хотя бы один согласующий")
        if self.approver_kind != ApproverKind.NAMED and self.approver_ids:
            raise ValueError(
                "у этапа с этим видом согласующих список не заполняется")
        return self


class StageUpdate(BaseModel):
    order: Optional[int] = Field(None, ge=1, le=999)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    quorum: Optional[Quorum] = None
    # None — «не трогать список»; пустой список запрещён отдельной проверкой
    # в сервисе, чтобы не молча получить неисполнимый этап.
    approver_ids: Optional[list[int]] = None
    # А здесь пустой список — законное «снять условие»: отличить его от «не
    # трогать» позволяет exclude_unset во вьюхе (см. StageDetailView.patch).
    condition: Optional[Condition] = None
    is_fallback: Optional[bool] = None
    # Переключение на «инициатора» стирает названных согласующих само —
    # присылать вместе с ним ``approver_ids: []`` не нужно (и непустой список
    # вместе с ним сервис отвергнет как противоречие).
    approver_kind: Optional[ApproverKind] = None
    requires_attachment: Optional[bool] = None


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
    condition: Condition = Field(default_factory=list)
    is_fallback: bool = False
    approver_kind: ApproverKind = ApproverKind.NAMED
    requires_attachment: bool = False
    # Пустой у этапа, который согласует инициатор: конкретный человек станет
    # известен только на запуске процесса.
    approvers: list[ApproverRead]


class CoverageGap(BaseModel):
    """Значения справочника, под которые в группе нет ветки.

    Подсказка редактору маршрута: попади в эту дыру объект — запуск
    согласования откажет (``engine._select_stages``). Показывается заранее,
    чтобы дыру закрыл администратор, а не обнаружил пользователь.
    """

    order: int
    field: str
    label: str
    missing: list[dict]


class RouteRead(BaseModel):
    id: int
    subject_type: str
    name: str
    is_active: bool
    stages: list[StageRead]
    # Считаются только для карточки одного маршрута — в списке этих полей
    # нет (см. route_service.serialize_route).
    coverage_gaps: Optional[list[CoverageGap]] = None
    # Подпись инициатора стоит не в последней группе: движок завершит процесс
    # раньше, чем до неё дойдёт очередь смысла. Предупреждение, не запрет —
    # см. route_service.initiator_stage_not_last.
    initiator_stage_not_last: Optional[bool] = None
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
    # Приложенный к решению документ. ``file_url`` подписанная и живёт
    # недолго, поэтому её нет в ответах без ``enrich`` — и её может не быть
    # даже там, если media выключен (см. attachments.file_url).
    file_id: Optional[str] = None
    file_url: Optional[str] = None


class ProcessStageRead(BaseModel):
    id: int
    order: int
    name: str
    quorum: str
    state: StageState
    # Снимок условия, по которому этап попал в процесс. ``matched_by``
    # различает «этап был безусловным» и «сработало иначе» — у обоих условие
    # пустое, и без этого поля они в карточке неразличимы.
    condition: Condition = Field(default_factory=list)
    matched_by: str = "always"
    # Снимок «этапа подписи» на момент запуска: ``approver_kind`` объясняет,
    # почему на этапе один человек и именно этот, ``requires_attachment``
    # — рабочее поле, его читает engine.act на каждом решении.
    approver_kind: ApproverKind = ApproverKind.NAMED
    requires_attachment: bool = False
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
    # Факты, по которым выбирались ветки, на момент запуска — ответ на
    # вопрос «почему согласуют именно эти люди» через год после запуска.
    subject_facts: dict = Field(default_factory=dict)
    # Карточка предметного объекта — из describe() его аппки. signoff не
    # умеет её построить сам и не должен.
    subject_title: Optional[str] = None
    subject_url: Optional[str] = None
    # Имя инициатора (из apps.users) — только в обогащённой карточке; сосед
    # через interface получает по-прежнему один initiator_id.
    initiator_name: Optional[str] = None


# ── Решения ─────────────────────────────────────────────────────────────

class Decision(BaseModel):
    # ``rework`` — «вернуть на доработку»: круг закрывается так же, как на
    # отказе, но объект остаётся правимым (``models.ApprovalState``).
    decision: str = Field(..., pattern="^(approve|reject|rework)$")
    comment: str = Field("", max_length=2000)


class Rework(BaseModel):
    """Возврат на доработку по уже закрытому кругу (``POST /processes/:id/rework``).

    Комментарий необязателен схемой — как и у решения. Требовать его
    формой значило бы отказывать 422 «проверьте поля» там, где на самом деле
    нечего проверять; настаивает на объяснении интерфейс, где его и видно.
    """

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
    # Решение по этому запросу требует приложенного PDF — видно в очереди, а
    # не только в диалоге решения.
    requires_attachment: bool = False
    file_id: Optional[str] = None
    initiator_id: Optional[int]
    created_at: datetime


class FieldOption(BaseModel):
    value: Any
    label: str = ""


class SubjectField(BaseModel):
    """Факт объекта, по которому разрешено ветвить маршрут.

    Приходит из ``fact_fields()`` предметной аппки — signoff этот список не
    придумывает и не хранит. ``options`` заполнены только у ``choice``: это
    справочник, и редактор рисует по нему выпадающий список вместо поля ввода.
    """

    key: str
    label: str = ""
    type: str = "string"
    options: list[FieldOption] = Field(default_factory=list)


class SubjectRead(BaseModel):
    """Согласуемый тип — для настройки маршрута."""

    subject_type: str
    label: str
    has_active_route: bool
    # Пустой список — тип не поддерживает ветвление (аппка не объявила
    # fact_fields); редактор в этом случае условий не показывает.
    fields: list[SubjectField] = Field(default_factory=list)
