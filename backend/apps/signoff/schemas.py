"""Pydantic-схемы HTTP-слоя аппки ``signoff``.

``api_view`` валидирует тело запроса схемой из ``body=`` и сериализует
возвращённую схему в ответ (см. ``htqweb/http.py``).

Соглашение по PATCH-схемам общее для репозитория: все поля
``Optional[...] = None``, и ``None`` означает «поле не пришло», а не
«обнулить».
"""

from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from apps.signoff.models import (
    ApproverKind,
    ProcessState,
    Quorum,
    StageState,
    TaskState,
)
from apps.signoff.services.conditions import OPS

# Ключ объекта согласования. Хранится и отдаётся строкой
# (ApprovalProcess.subject_id): документы модуля БЗО адресуются UUID.
# Целое от старых клиентов принимается и приводится к строке — контракт ручек
# предметных аппок не ломается.
SubjectId = Annotated[str, BeforeValidator(str), StringConstraints(min_length=1, max_length=64)]

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

class PositionRefIn(BaseModel):
    """Должность парой (БЗО, B8.1): ``company`` — слаг вышестоящей компании,
    в штате которой должность; пусто — своя компания."""

    company: str = Field("", max_length=32)
    position_id: int


class RouteFlags(BaseModel):
    """Флаги маршрута (мастер-план БЗО, D-21) — все выключены по умолчанию.
    «Роли» здесь — HR-должности, как у согласующих этапов."""

    forbid_self_approval: bool = False
    reject_comment_min: int = Field(0, ge=0, le=500)
    lazy_resolution: bool = False
    skip_unmatched_groups: bool = False
    no_executor_notify_position_ids: list[int] = Field(default_factory=list, max_length=20)
    escalation_position_id: Optional[int] = None
    self_skip_notify_position_ids: list[int] = Field(default_factory=list, max_length=20)
    # B8.1: должности вышестоящих компаний для тех же ролей и решение «прямо
    # из холдинга» (живой флаг, в снимок процесса не копируется).
    escalation_position_company: str = Field("", max_length=32)
    no_executor_notify_foreign: list[PositionRefIn] = Field(default_factory=list, max_length=20)
    self_skip_notify_foreign: list[PositionRefIn] = Field(default_factory=list, max_length=20)
    allow_direct_decisions: bool = False


class RouteCreate(RouteFlags):
    subject_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=200)
    is_active: bool = True
    # Область внутри типа (``ApprovalRoute.scope``); пустая — весь тип.
    scope: str = Field("", max_length=64)


class RouteUpdate(BaseModel):
    """Патч: применяются только присланные поля (``exclude_unset``)."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    is_active: Optional[bool] = None
    forbid_self_approval: Optional[bool] = None
    reject_comment_min: Optional[int] = Field(None, ge=0, le=500)
    lazy_resolution: Optional[bool] = None
    skip_unmatched_groups: Optional[bool] = None
    no_executor_notify_position_ids: Optional[list[int]] = Field(None, max_length=20)
    escalation_position_id: Optional[int] = None
    self_skip_notify_position_ids: Optional[list[int]] = Field(None, max_length=20)
    escalation_position_company: Optional[str] = Field(None, max_length=32)
    no_executor_notify_foreign: Optional[list[PositionRefIn]] = Field(None, max_length=20)
    self_skip_notify_foreign: Optional[list[PositionRefIn]] = Field(None, max_length=20)
    allow_direct_decisions: Optional[bool] = None


class PositionBrief(BaseModel):
    id: int
    title: str = ""
    # Компания должности (B8.1): пусто — своя; название — для подписи.
    company: str = ""
    company_name: Optional[str] = None


class StageCreate(BaseModel):
    """Этап маршрута вместе со списком HR-должностей.

    ``position_ids`` принимается прямо здесь, а не отдельным запросом на
    каждого: этап без должностей нельзя исполнить (``engine._approver_ids``
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
    position_ids: list[int] = Field(default_factory=list)
    # Должности парами, в том числе вышестоящих компаний (B8.1); складываются
    # с ``position_ids`` своей компании.
    positions: list[PositionRefIn] = Field(default_factory=list)
    # Пустое условие — «этап нужен всегда»; это и есть поведение всех этапов
    # до появления ветвления, поэтому значение по умолчанию именно такое.
    condition: Condition = Field(default_factory=list)
    is_fallback: bool = False
    approver_kind: ApproverKind = ApproverKind.POSITION
    # Для ``users`` — учётные записи поимённо; для ``subject`` — ключ из
    # ``approver_fields`` типа. Сочетания с видом проверяет сервис
    # (``route_service._check_approver_kind``).
    user_ids: list[int] = Field(default_factory=list)
    approver_key: str = Field("", max_length=64)
    requires_attachment: bool = False
    requires_comment: bool = False
    votes_option: bool = False
    # Что этап требует от ОБЪЕКТА (ключ из ``requirement_fields`` типа) —
    # проверяет сервис, как и ключ согласующих.
    requirement_key: str = Field("", max_length=64)

    @model_validator(mode="after")
    def _roles_match_kind(self):
        if len(set(self.position_ids)) != len(self.position_ids):
            raise ValueError("должности в этапе повторяются")
        if len({(ref.company, ref.position_id) for ref in self.positions}) != len(self.positions):
            raise ValueError("должности в этапе повторяются")
        if len(set(self.user_ids)) != len(self.user_ids):
            raise ValueError("согласующие в этапе повторяются")
        # Смысл сочетаний — в route_service._check_approver_kind; здесь
        # проверяется ровно то, что видно из схемы: список либо нужен, либо
        # неуместен. Дубль осознанный — 422 на форме понятнее, чем 409 из
        # сервиса, а сервис обязан защищаться и без схемы (его зовёт и
        # django-admin).
        has_positions = bool(self.position_ids or self.positions)
        if self.approver_kind == ApproverKind.POSITION and not has_positions:
            raise ValueError("нужна хотя бы одна должность")
        if self.approver_kind != ApproverKind.POSITION and has_positions:
            raise ValueError(
                "у этапа с этим видом согласующих должности не заполняются")
        if self.approver_kind == ApproverKind.USERS and not self.user_ids:
            raise ValueError("нужен хотя бы один согласующий")
        if self.approver_kind == ApproverKind.SUBJECT and not self.approver_key:
            raise ValueError("укажите, кого объект назначает согласующим")
        return self


class StageUpdate(BaseModel):
    order: Optional[int] = Field(None, ge=1, le=999)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    quorum: Optional[Quorum] = None
    # None — «не трогать список»; пустой список запрещён отдельной проверкой
    # в сервисе, чтобы не молча получить неисполнимый этап.
    position_ids: Optional[list[int]] = None
    # Пары (B8.1). Прислано хоть одно из двух — список должностей этапа
    # заменяется целиком их суммой.
    positions: Optional[list[PositionRefIn]] = None
    # А здесь пустой список — законное «снять условие»: отличить его от «не
    # трогать» позволяет exclude_unset во вьюхе (см. StageDetailView.patch).
    condition: Optional[Condition] = None
    is_fallback: Optional[bool] = None
    # Переключение на «инициатора» стирает названных согласующих само —
    # присылать вместе с ним ``approver_ids: []`` не нужно (и непустой список
    # вместе с ним сервис отвергнет как противоречие).
    approver_kind: Optional[ApproverKind] = None
    user_ids: Optional[list[int]] = None
    approver_key: Optional[str] = Field(None, max_length=64)
    requires_attachment: Optional[bool] = None
    requires_comment: Optional[bool] = None
    votes_option: Optional[bool] = None
    requirement_key: Optional[str] = Field(None, max_length=64)


class StageUserRead(BaseModel):
    user_id: int
    full_name: str = ""
    is_active: bool = True


class ApproverFieldRead(BaseModel):
    """Ключ «назначает объект» — что предметная аппка умеет спросить у объекта."""

    key: str
    label: str = ""


class RoleRead(BaseModel):
    position_id: int
    # Компания должности (B8.1): пусто — своя.
    company: str = ""
    company_name: Optional[str] = None
    title: str = ""
    department_name: Optional[str] = None
    is_active: bool = True


class StageRead(BaseModel):
    id: int
    order: int
    name: str
    quorum: str
    condition: Condition = Field(default_factory=list)
    is_fallback: bool = False
    approver_kind: ApproverKind = ApproverKind.POSITION
    requires_attachment: bool = False
    requires_comment: bool = False
    votes_option: bool = False
    # Настройка двух других видов: люди поимённо (с именами для редактора)
    # и ключ «назначает объект» с подписью из ``approver_fields``.
    user_ids: list[int] = Field(default_factory=list)
    users: list[StageUserRead] = Field(default_factory=list)
    approver_key: str = ""
    approver_label: Optional[str] = None
    requirement_key: str = ""
    requirement_label: Optional[str] = None
    # Пустой у этапа, который согласует инициатор: конкретный человек станет
    # известен только на запуске процесса.
    roles: list[RoleRead]


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
    scope: str = ""
    scope_label: Optional[str] = None
    name: str
    is_active: bool
    # Флаги маршрута (D-21) и подписи их должностей.
    forbid_self_approval: bool = False
    reject_comment_min: int = 0
    lazy_resolution: bool = False
    skip_unmatched_groups: bool = False
    no_executor_notify_position_ids: list[int] = Field(default_factory=list)
    escalation_position_id: Optional[int] = None
    self_skip_notify_position_ids: list[int] = Field(default_factory=list)
    no_executor_notify_positions: list[PositionBrief] = Field(default_factory=list)
    escalation_position: Optional[PositionBrief] = None
    self_skip_notify_positions: list[PositionBrief] = Field(default_factory=list)
    # B8.1: компания должности эскалации, получатели из вышестоящих компаний,
    # решение «прямо из холдинга» и допускает ли его тип документа вообще.
    escalation_position_company: str = ""
    no_executor_notify_foreign: list[PositionRefIn] = Field(default_factory=list)
    self_skip_notify_foreign: list[PositionRefIn] = Field(default_factory=list)
    allow_direct_decisions: bool = False
    cross_company_decisions: bool = False
    stages: list[StageRead]
    # Схема области — только в карточке одного маршрута (редактор): по каким
    # фактам ветвить и какие ключи «назначает объект» предлагать.
    fields: Optional[list["SubjectField"]] = None
    approver_fields: Optional[list[ApproverFieldRead]] = None
    requirement_fields: Optional[list[ApproverFieldRead]] = None
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
    subject_id: SubjectId
    initiator_id: Optional[int] = None
    # None — область назовёт сама предметная аппка (``Subject.scope_of``).
    scope: Optional[str] = Field(None, max_length=64)


class TaskRead(BaseModel):
    id: int
    user_id: int
    position_id: Optional[int] = None
    # Компания должности (B8.1): пусто — своя; подпись — «ФД · Hi-Tech Group»
    # (только в обогащённой карточке). ``also_positions`` — остальные
    # должности этапа, которые закрывает эта же задача.
    position_company: str = ""
    position_label: Optional[str] = None
    also_positions: list[dict] = Field(default_factory=list)
    full_name: str = ""
    state: TaskState
    comment: str
    acted_at: Optional[datetime]
    # Приложенный к решению документ. ``file_url`` подписанная и живёт
    # недолго, поэтому её нет в ответах без ``enrich`` — и её может не быть
    # даже там, если media выключен (см. attachments.file_url).
    file_id: Optional[str] = None
    file_url: Optional[str] = None
    # Голос за вариант, когда было из чего выбирать (ТЗ §12.4).
    option_key: Optional[str] = None
    option_label: Optional[str] = None


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
    # почему на этапе один человек и именно этот, ``requires_attachment`` и
    # ``requires_comment`` — рабочие поля, их читает engine.act на каждом
    # решении.
    approver_kind: ApproverKind = ApproverKind.POSITION
    role_ids: list[int] = Field(default_factory=list)
    # Все должности этапа парами ``{company, position_id}`` (B8.1).
    role_refs: list[dict] = Field(default_factory=list)
    user_ids: list[int] = Field(default_factory=list)
    approver_key: str = ""
    requires_attachment: bool = False
    requires_comment: bool = False
    votes_option: bool = False
    requirement_key: str = ""
    requirement_label: Optional[str] = None
    # Когда этап стал активным — «Сейчас у … с …» (B1.3).
    activated_at: Optional[datetime] = None
    decided_at: Optional[datetime]
    tasks: list[TaskRead]


class ProcessRead(BaseModel):
    id: int
    subject_type: str
    subject_id: SubjectId
    scope: str = ""
    state: ProcessState
    initiator_id: Optional[int]
    current_order: Optional[int]
    created_at: datetime
    finished_at: Optional[datetime]
    stages: list[ProcessStageRead]
    # Факты, по которым выбирались ветки, на момент запуска — ответ на
    # вопрос «почему согласуют именно эти люди» через год после запуска.
    subject_facts: dict = Field(default_factory=dict)
    # Флаги маршрута на момент запуска (D-21); у процессов до флагов пусто.
    route_flags: dict = Field(default_factory=dict)
    # Карточка предметного объекта — из describe() его аппки. signoff не
    # умеет её построить сам и не должен.
    subject_title: Optional[str] = None
    subject_url: Optional[str] = None
    # Имя инициатора (из apps.users) — только в обогащённой карточке; сосед
    # через interface получает по-прежнему один initiator_id.
    initiator_name: Optional[str] = None
    # Варианты для решения «согласовать» у идущего процесса: исходный
    # документ и его альтернативы. Пусто или один — выбирать не из чего.
    options: list[dict] = Field(default_factory=list)


# ── Решения ─────────────────────────────────────────────────────────────

class Decision(BaseModel):
    # ``rework`` — «вернуть на доработку»: круг закрывается так же, как на
    # отказе, но объект остаётся правимым (``models.ApprovalState``).
    decision: str = Field(..., pattern="^(approve|reject|rework)$")
    comment: str = Field("", max_length=2000)
    # Ключ варианта из ``ProcessRead.options`` — обязателен у «согласовать»,
    # когда вариантов больше одного.
    option_key: str = Field("", max_length=64)


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
    subject_id: SubjectId
    subject_title: Optional[str]
    subject_url: Optional[str]
    stage_name: str
    # Положение шага в маршруте («этап 2 из 4») — прогресс для того, у кого
    # в маршруте несколько этапов подряд.
    stage_order: int
    stage_count: int
    quorum: str
    # Решение по этому запросу требует приложенного PDF и/или пояснения —
    # видно в очереди, а не только в диалоге решения.
    requires_attachment: bool = False
    requires_comment: bool = False
    requirement_label: Optional[str] = None
    file_id: Optional[str] = None
    initiator_id: Optional[int]
    created_at: datetime


class CompanyBrief(BaseModel):
    """Компания строки очереди или карточки (B8.1). ``url`` — её адрес для
    перехода (``companies.public_url``); пусто, если корень не настроен."""

    slug: str
    subdomain: Optional[str] = None
    name: str = ""
    url: Optional[str] = None
    current: bool = False


class InboxAllItem(InboxItem):
    """Строка единой очереди «Ждёт меня» по всем компаниям (B8.1).

    ``can_enter`` — у человека есть членство в компании задачи, и «Открыть»
    переведёт его туда; ``direct_allowed`` — задачу можно решить прямо
    отсюда (флаг маршрута), а если нет — ``direct_blocker`` объясняет почему.
    ``process_path`` — где решать на адресе компании задачи."""

    company: Optional[CompanyBrief] = None
    can_enter: bool = True
    direct_allowed: bool = False
    direct_blocker: Optional[str] = None
    process_path: str = ""


class SummaryColumn(BaseModel):
    key: str
    label: str = ""
    align: Optional[str] = None


class SummaryLines(BaseModel):
    columns: list[SummaryColumn] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)
    total: Optional[dict] = None


class SubjectSummary(BaseModel):
    """Сводка документа для решения из вышестоящей компании (``Subject.summary``):
    поля шапки и таблица позиций — готовыми строками."""

    fields: list[dict] = Field(default_factory=list)
    lines: Optional[SummaryLines] = None


class ForeignProcessRead(ProcessRead):
    """Карточка процесса дочерней компании, открытая из холдинга (B8.1)."""

    company: CompanyBrief
    summary: Optional[SubjectSummary] = None
    my_task_id: Optional[int] = None
    direct_allowed: bool = False
    direct_blocker: Optional[str] = None
    # Есть членство в компании документа — «Открыть в компании» её откроет.
    can_enter: bool = False


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


class ScopeRead(BaseModel):
    scope: str
    label: str = ""
    has_active_route: bool = False


class SubjectRead(BaseModel):
    """Согласуемый тип — для настройки маршрута."""

    subject_type: str
    label: str
    has_active_route: bool
    # Пустой список — тип не поддерживает ветвление (аппка не объявила
    # fact_fields); редактор в этом случае условий не показывает.
    fields: list[SubjectField] = Field(default_factory=list)
    # Области типа (``Subject.scopes``): у типов без областей пусто, и
    # маршрут заводится на весь тип.
    scopes: list[ScopeRead] = Field(default_factory=list)
    approver_fields: list[ApproverFieldRead] = Field(default_factory=list)
    requirement_fields: list[ApproverFieldRead] = Field(default_factory=list)


class BatchDecisionItem(BaseModel):
    """Элемент массового решения — со своим комментарием и вариантом голоса
    (мастер-план БЗО, B1.3)."""

    task_id: int
    decision: str = Field(..., pattern="^(approve|reject|rework)$")
    comment: str = Field("", max_length=2000)
    option_key: str = Field("", max_length=64)


class BatchDecision(BaseModel):
    """Решения по нескольким запросам сразу — «одобрить всё выбранное».

    Прежняя форма — одно решение и один комментарий на все ``task_ids``;
    новая — ``items``, у каждого своё. Ровно одна из двух."""

    task_ids: Optional[list[int]] = Field(None, min_length=1, max_length=100)
    decision: Optional[str] = Field(None, pattern="^(approve|reject|rework)$")
    comment: str = Field("", max_length=2000)
    items: Optional[list[BatchDecisionItem]] = Field(None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _one_shape(self):
        if self.items is not None:
            if self.task_ids is not None:
                raise ValueError("Передайте либо items, либо task_ids с decision")
            return self
        if not self.task_ids or not self.decision:
            raise ValueError("Нужны items или task_ids вместе с decision")
        return self

    def as_items(self) -> list[dict]:
        if self.items is not None:
            return [item.model_dump() for item in self.items]
        return [{"task_id": task_id, "decision": self.decision, "comment": self.comment}
                for task_id in self.task_ids]


class BatchDecisionResult(BaseModel):
    task_id: int
    ok: bool
    error: Optional[str] = None
