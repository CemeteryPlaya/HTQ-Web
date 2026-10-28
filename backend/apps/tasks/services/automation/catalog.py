"""Каталог автоматизации: триггеры, условия, действия (этап S4, разбор Trello §3).

Каждый элемент — Pydantic-схема параметров с ключом ``type``. Из схем же
собирается ``GET automation/catalog`` для конструктора S5; фразы правил по
ключам строит фронт. ``validate`` проверяет автоматизацию целиком при
сохранении: вид и триггер согласованы, действия допустимы для вида, ссылки на
метки, свои поля и шаблоны чек-листов ЭТОЙ доски и на людей компании живые.
Ссылка, ставшая мёртвой после сохранения, — сбой правила в журнале запусков.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from apps.companies import interface as companies
from htqweb.errors import DomainError
from htqweb.tenancy.context import current_company_or_none

from ...models import AutomationKind, BoardField, BoardFieldType, BoardSettings, Label
from .. import board_fields

MAX_CONDITIONS = 20
MAX_ACTIONS = 20
MAX_PEOPLE = 50

StatusKey = Literal["backlog", "todo", "in_progress", "in_review", "blocked", "done", "cancelled"]
Position = Literal["top", "bottom"]
FieldValue = Union[bool, int, float, str, None]
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class _Spec(BaseModel):
    model_config = {"extra": "forbid"}


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


# ── триггеры правил ─────────────────────────────────────────────────────

class CardCreated(_Spec):
    """Задача создана на доске (в колонке X)."""

    type: Literal["card_created"]
    status: StatusKey | None = None


class Moved(_Spec):
    """Перенесена: из X, в Y, из X в Y или любой перенос."""

    type: Literal["moved"]
    from_status: StatusKey | None = None
    to_status: StatusKey | None = None

    @model_validator(mode="after")
    def _distinct(self) -> "Moved":
        _need(not self.from_status or self.from_status != self.to_status,
              "Колонки «из» и «в» совпадают")
        return self


class StatusMark(_Spec):
    """Отмечена выполненной (в «Готово»), снята отметка (из «Готово»), отменена."""

    type: Literal["completed", "uncompleted", "cancelled"]


class ColumnCount(_Spec):
    """В колонке стало ровно / больше / меньше N карточек."""

    type: Literal["column_count"]
    status: StatusKey
    op: Literal["eq", "gt", "lt"] = "eq"
    count: int = Field(..., ge=0, le=100000)


class LabelEvent(_Spec):
    type: Literal["label_added", "label_removed"]
    label_id: int | None = None


class AttachmentEvent(_Spec):
    # «Вложение удалено» нет: вложения задачи в платформе не удаляются.
    type: Literal["attachment_added"]


class AssigneeEvent(_Spec):
    type: Literal["assignee_added", "assignee_removed"]
    user_id: int | None = None


class SupervisorEvent(_Spec):
    type: Literal["supervisor_set", "supervisor_removed"]


class DueEvent(_Spec):
    """Срок поставлен (был пуст), перенесён (был другой), снят."""

    type: Literal["due_set", "due_changed", "due_removed"]


class ChecklistEvent(_Spec):
    type: Literal["checklist_added", "checklist_completed", "checklist_uncompleted"]
    title: str | None = Field(default=None, max_length=200)


class ItemEvent(_Spec):
    type: Literal["item_checked", "item_unchecked", "item_added"]
    text: str | None = Field(default=None, max_length=500)
    checklist_title: str | None = Field(default=None, max_length=200)


class CommentEvent(_Spec):
    type: Literal["comment_added"]
    match: Literal["any", "starts_with", "contains"] = "any"
    text: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _text_for_match(self) -> "CommentEvent":
        _need(self.match == "any" or self.text.strip(), "Нужен текст для сравнения")
        return self


class FieldEvent(_Spec):
    """Своё поле: задано, очищено, равно значению, флажок отмечен или снят,
    число больше или меньше N."""

    type: Literal["field_changed"]
    field_id: int
    op: Literal["set", "cleared", "equals", "checked", "unchecked", "gt", "lt"] = "set"
    value: FieldValue = None


class FieldsFilledEvent(_Spec):
    type: Literal["fields_filled"]


RuleTrigger = Annotated[Union[
    CardCreated, Moved, StatusMark, ColumnCount, LabelEvent, AttachmentEvent,
    AssigneeEvent, SupervisorEvent, DueEvent, ChecklistEvent, ItemEvent, CommentEvent,
    FieldEvent, FieldsFilledEvent,
], Field(discriminator="type")]

#: Триггеры смены колонки — только у них есть «Запретить перенос» (K-38).
MOVE_TRIGGERS = frozenset({"moved", "completed", "uncompleted", "cancelled"})


# ── «триггеры» кнопок и команд ──────────────────────────────────────────

class CardsScope(_Spec):
    """Над какими карточками доски: колонка и условия автоматизации."""

    status: StatusKey | None = None


class CardButtonTrigger(_Spec):
    type: Literal["card_button"]


class BoardButtonTrigger(_Spec):
    """Кнопка на доске: ``cards`` — над карточками, без него — действия
    уровня доски (создать задачу, сортировать колонку, уведомить)."""

    type: Literal["board_button"]
    cards: CardsScope | None = None


class DueTrigger(_Spec):
    """За N дней до срока (``offset_days`` < 0), в день срока (0), через N
    дней после (> 0); дни календарные или рабочие."""

    type: Literal["due"]
    offset_days: int = Field(default=0, ge=-365, le=365)
    working: bool = False


class ScheduleTrigger(_Spec):
    """Каждый день, по будням, по дням недели (1 — понедельник), N-го числа
    месяца — в ЧЧ:ММ по Алматы."""

    type: Literal["schedule"]
    freq: Literal["daily", "weekdays", "weekly", "monthly"]
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    time: str = "09:00"
    cards: CardsScope | None = None

    @model_validator(mode="after")
    def _shape(self) -> "ScheduleTrigger":
        _need(bool(_TIME.match(self.time)), "Время — ЧЧ:ММ")
        _need(all(1 <= day <= 7 for day in self.weekdays), "Дни недели — от 1 до 7")
        _need(self.freq != "weekly" or bool(self.weekdays), "Выберите дни недели")
        _need(self.freq != "monthly" or self.day_of_month is not None, "Выберите число месяца")
        return self


TRIGGERS_BY_KIND = {
    AutomationKind.RULE: TypeAdapter(RuleTrigger),
    AutomationKind.CARD_BUTTON: TypeAdapter(CardButtonTrigger),
    AutomationKind.BOARD_BUTTON: TypeAdapter(BoardButtonTrigger),
    AutomationKind.DUE: TypeAdapter(DueTrigger),
    AutomationKind.SCHEDULE: TypeAdapter(ScheduleTrigger),
}


# ── условия ─────────────────────────────────────────────────────────────

class InColumn(_Spec):
    type: Literal["in_column"]
    status: StatusKey
    negate: bool = False


class HasLabel(_Spec):
    type: Literal["has_label"]
    label_id: int
    negate: bool = False


class Assigned(_Spec):
    """Назначена: на кого-нибудь, ни на кого, на человека, только на него."""

    type: Literal["assigned"]
    who: Literal["anyone", "nobody", "user", "only_user"] = "anyone"
    user_id: int | None = None

    @model_validator(mode="after")
    def _user(self) -> "Assigned":
        _need(self.who not in ("user", "only_user") or self.user_id is not None,
              "Выберите человека")
        return self


class HasDue(_Spec):
    type: Literal["has_due"]
    negate: bool = False


class DueWindow(_Spec):
    type: Literal["due_window"]
    window: Literal["today", "overdue", "within_days", "this_week", "this_month"]
    days: int | None = Field(default=None, ge=1, le=365)

    @model_validator(mode="after")
    def _days(self) -> "DueWindow":
        _need(self.window != "within_days" or self.days is not None, "Укажите число дней")
        return self


class ChecklistsState(_Spec):
    """Все чек-листы выполнены (есть пункты, и все отмечены) или есть
    невыполненный пункт."""

    type: Literal["checklists_complete", "checklists_incomplete"]


class HasChecklist(_Spec):
    type: Literal["has_checklist"]
    title: str = Field(..., min_length=1, max_length=200)
    negate: bool = False


class TextMatch(_Spec):
    """Название или описание: начинается с, содержит; описание — пустое."""

    type: Literal["title", "description"]
    match: Literal["starts_with", "contains", "empty"]
    text: str = Field(default="", max_length=500)
    negate: bool = False

    @model_validator(mode="after")
    def _shape(self) -> "TextMatch":
        _need(not (self.type == "title" and self.match == "empty"), "Название не бывает пустым")
        _need(self.match == "empty" or self.text.strip(), "Нужен текст для сравнения")
        return self


class FieldCondition(_Spec):
    type: Literal["field"]
    field_id: int
    op: Literal["set", "empty", "equals", "checked", "unchecked", "gt", "lt"] = "set"
    value: FieldValue = None


class FieldsFilledCondition(_Spec):
    type: Literal["fields_filled"]
    negate: bool = False


class ActorCondition(_Spec):
    """Кто сделал: конкретный человек, кто угодно кроме него, автоматизация,
    человек (не автоматизация)."""

    type: Literal["actor"]
    op: Literal["is", "is_not", "automation", "person"]
    user_id: int | None = None

    @model_validator(mode="after")
    def _user(self) -> "ActorCondition":
        _need(self.op not in ("is", "is_not") or self.user_id is not None, "Выберите человека")
        return self


Condition = Annotated[Union[
    InColumn, HasLabel, Assigned, HasDue, DueWindow, ChecklistsState, HasChecklist,
    TextMatch, FieldCondition, FieldsFilledCondition, ActorCondition,
], Field(discriminator="type")]


# ── действия ────────────────────────────────────────────────────────────

class MoveAction(_Spec):
    type: Literal["move"]
    status: StatusKey
    position: Position = "bottom"


class RepositionAction(_Spec):
    type: Literal["reposition"]
    position: Position = "top"


class PlainAction(_Spec):
    """Действие без параметров."""

    type: Literal["cancel", "complete", "remove_all_labels", "clear_due", "set_start_today",
                  "clear_start", "check_all", "reset_all", "join_actor", "remove_all_assignees",
                  "watch_actor"]


class BlockAction(_Spec):
    """Запретить перенос (K-38): ответ — 409 с этим текстом."""

    type: Literal["block"]
    message: str = Field(..., min_length=1, max_length=1000)


class LabelAction(_Spec):
    type: Literal["add_label", "remove_label"]
    label_id: int


class CreateTaskAction(_Spec):
    """Создать задачу в колонке доски автоматизации (название с переменными)."""

    type: Literal["create_task"]
    summary: str = Field(..., min_length=1, max_length=500)
    status: Literal["backlog", "todo"] = "todo"


class CopyTaskAction(_Spec):
    """Скопировать задачу (название, описание, метки, чек-листы) в колонку."""

    type: Literal["copy_task"]
    summary: str = Field(default="{cardname}", min_length=1, max_length=500)
    status: Literal["backlog", "todo"] = "todo"


class SetDueAction(_Spec):
    """Срок: сегодня, через N дней (рабочих или календарных), из своего поля-даты."""

    type: Literal["set_due"]
    mode: Literal["today", "in_days", "field"] = "in_days"
    days: int = Field(default=0, ge=0, le=3650)
    working: bool = False
    field_id: int | None = None

    @model_validator(mode="after")
    def _field(self) -> "SetDueAction":
        _need(self.mode != "field" or self.field_id is not None, "Выберите поле-дату")
        return self


class ShiftDueAction(_Spec):
    type: Literal["shift_due"]
    days: int = Field(..., ge=-3650, le=3650)
    working: bool = False

    @model_validator(mode="after")
    def _nonzero(self) -> "ShiftDueAction":
        _need(self.days != 0, "Сдвиг — не ноль дней")
        return self


class AddChecklistAction(_Spec):
    """Чек-лист по шаблону доски (пункты копируются) или пустой."""

    type: Literal["add_checklist"]
    title: str = Field(..., min_length=1, max_length=200)
    template_id: str | None = Field(default=None, max_length=16)


class ItemAction(_Spec):
    type: Literal["add_item", "check_item", "uncheck_item", "remove_item"]
    text: str = Field(..., min_length=1, max_length=500)
    checklist_title: str | None = Field(default=None, max_length=200)


class UserAction(_Spec):
    type: Literal["add_assignee", "remove_assignee"]
    user_id: int


class PickAssigneeAction(_Spec):
    """Назначить исполнителем случайного или следующего по очереди из списка."""

    type: Literal["random_assignee", "round_robin_assignee"]
    user_ids: list[int] = Field(..., min_length=1, max_length=MAX_PEOPLE)


class SupervisorAction(_Spec):
    type: Literal["set_supervisor"]
    who: Literal["user", "actor"] = "user"
    user_id: int | None = None

    @model_validator(mode="after")
    def _user(self) -> "SupervisorAction":
        _need(self.who != "user" or self.user_id is not None, "Выберите человека")
        return self


class RenameAction(_Spec):
    type: Literal["rename"]
    summary: str = Field(..., min_length=1, max_length=500)


class DescriptionAction(_Spec):
    type: Literal["set_description"]
    text: str = Field(default="", max_length=10000)
    mode: Literal["replace", "append"] = "replace"


class CommentAction(_Spec):
    """Комментарий; ``@card`` в тексте — уведомить участников задачи."""

    type: Literal["comment"]
    text: str = Field(..., min_length=1, max_length=5000)


class NotifyAction(_Spec):
    """Уведомить выбранных сотрудников (колокольчик, почта и Telegram — по
    их настройкам центра уведомлений)."""

    type: Literal["notify"]
    user_ids: list[int] = Field(..., min_length=1, max_length=MAX_PEOPLE)
    text: str = Field(..., min_length=1, max_length=1000)


class SetFieldAction(_Spec):
    """Своё поле: значение (у флажка — да или нет); у даты — сегодня или
    через N дней."""

    type: Literal["set_field"]
    field_id: int
    mode: Literal["value", "today", "in_days"] = "value"
    value: FieldValue = None
    days: int = Field(default=0, ge=0, le=3650)
    working: bool = False


class ClearFieldAction(_Spec):
    type: Literal["clear_field"]
    field_id: int


class IncrementFieldAction(_Spec):
    type: Literal["increment_field"]
    field_id: int
    by: float

    @model_validator(mode="after")
    def _nonzero(self) -> "IncrementFieldAction":
        _need(self.by != 0, "Шаг — не ноль")
        return self


class ShiftFieldDateAction(_Spec):
    type: Literal["shift_field_date"]
    field_id: int
    days: int = Field(..., ge=-3650, le=3650)
    working: bool = False

    @model_validator(mode="after")
    def _nonzero(self) -> "ShiftFieldDateAction":
        _need(self.days != 0, "Сдвиг — не ноль дней")
        return self


class SortColumnAction(_Spec):
    """Сортировать колонку доски (кнопка доски и расписание)."""

    type: Literal["sort_column"]
    status: StatusKey
    by: Literal["due", "priority", "title", "created", "field"] = "due"
    field_id: int | None = None
    direction: Literal["asc", "desc"] = "asc"

    @model_validator(mode="after")
    def _field(self) -> "SortColumnAction":
        _need(self.by != "field" or self.field_id is not None, "Выберите поле")
        return self


Action = Annotated[Union[
    MoveAction, RepositionAction, PlainAction, BlockAction, LabelAction, CreateTaskAction,
    CopyTaskAction, SetDueAction, ShiftDueAction, AddChecklistAction, ItemAction, UserAction,
    PickAssigneeAction, SupervisorAction, RenameAction, DescriptionAction, CommentAction,
    NotifyAction, SetFieldAction, ClearFieldAction, IncrementFieldAction, ShiftFieldDateAction,
    SortColumnAction,
], Field(discriminator="type")]

_CONDITIONS = TypeAdapter(list[Condition])
_ACTIONS = TypeAdapter(list[Action])

#: Действия уровня доски — у кнопки доски и расписания без карточек.
BOARD_ACTIONS = frozenset({"create_task", "sort_column", "notify"})
#: Сортировка — только уровня доски: у карточки своей колонки нет смысла.
CARD_ONLY_EXCLUDED = frozenset({"sort_column", "block"})


# ── проверка автоматизации ──────────────────────────────────────────────

def _invalid(message: str, **details) -> DomainError:
    return DomainError("automation_invalid", message, status=422, details=details or None)


def _parse(adapter: TypeAdapter, raw, where: str):
    try:
        return adapter.validate_python(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        place = ".".join(str(part) for part in first.get("loc", ()))
        message = first.get("msg", "Неверное значение").removeprefix("Value error, ")
        raise _invalid(f"{where}: {message}", path=f"{where}.{place}".rstrip(".")) from exc


def _is_card_scope(kind: str, trigger) -> bool:
    """Действия над карточкой (а не уровня доски)."""
    if kind in (AutomationKind.BOARD_BUTTON, AutomationKind.SCHEDULE):
        return trigger.cards is not None
    return True


class _Refs:
    """Ссылки автоматизации: проверяются одним запросом на вид ссылки."""

    def __init__(self, board):
        self.board = board
        self.labels: set[int] = set()
        self.fields: dict[int, list[tuple[str, object]]] = {}
        self.templates: set[str] = set()
        self.users: set[int] = set()

    def field(self, field_id: int, use: str, spec) -> None:
        self.fields.setdefault(field_id, []).append((use, spec))

    def check(self) -> None:
        if self.labels:
            known = set(Label.objects.filter(pk__in=self.labels).values_list("pk", flat=True))
            if missing := sorted(self.labels - known):
                raise _invalid("Метки нет — обновите доску", label_ids=missing)
        if self.fields:
            rows = {field.pk: field for field in BoardField.objects.filter(
                pk__in=list(self.fields), board_kind=self.board.kind, board_id=self.board.id)}
            if missing := sorted(set(self.fields) - set(rows)):
                raise _invalid("Поля нет на этой доске — обновите доску", field_ids=missing)
            for field_id, uses in self.fields.items():
                for use, spec in uses:
                    _check_field_use(rows[field_id], use, spec)
        if self.templates:
            row = BoardSettings.objects.filter(board_kind=self.board.kind,
                                               board_id=self.board.id).first()
            known = {item["id"] for item in board_fields.templates_of(row)}
            if missing := sorted(self.templates - known):
                raise _invalid("Шаблона чек-листа нет на этой доске", template_ids=missing)
        slug = current_company_or_none()
        if self.users and slug:
            members = set(companies.active_member_ids(slug))
            if missing := sorted(self.users - members):
                raise _invalid("Человек не работает в компании", user_ids=missing)


def _check_value(field: BoardField, value) -> None:
    try:
        parsed = board_fields.parse_value(field, value)
    except DomainError as exc:
        raise _invalid(f"Поле «{field.name}»: {exc.message}") from exc
    if parsed is None:
        raise _invalid(f"Поле «{field.name}»: нужно значение")


def _check_field_use(field: BoardField, use: str, spec) -> None:
    """Операция подходит к типу поля, значение — к его типу. ``use`` —
    trigger, condition, set, clear, increment, shift_date, due_from, sort."""
    kind = field.field_type

    def need(condition: bool, what: str) -> None:
        if not condition:
            raise _invalid(f"Поле «{field.name}» — {what}")

    if use in ("trigger", "condition"):
        if spec.op in ("checked", "unchecked"):
            need(kind == BoardFieldType.CHECKBOX, "не флажок")
        elif spec.op in ("gt", "lt"):
            need(kind == BoardFieldType.NUMBER, "не число")
            _check_value(field, spec.value)
        elif spec.op == "equals":
            need(kind != BoardFieldType.CHECKBOX, "флажок сравнивается отметкой")
            _check_value(field, spec.value)
    elif use == "set":
        if spec.mode in ("today", "in_days"):
            need(kind == BoardFieldType.DATE, "не дата")
        elif kind == BoardFieldType.CHECKBOX:
            need(isinstance(spec.value, bool), "флажок: да или нет")
        else:
            _check_value(field, spec.value)
    elif use == "increment":
        need(kind == BoardFieldType.NUMBER, "не число")
    elif use in ("shift_date", "due_from"):
        need(kind == BoardFieldType.DATE, "не дата")


def _collect(refs: _Refs, trigger, conditions, actions) -> None:
    trigger_type = getattr(trigger, "type", "")
    if trigger_type in ("label_added", "label_removed") and trigger.label_id is not None:
        refs.labels.add(trigger.label_id)
    if trigger_type in ("assignee_added", "assignee_removed") and trigger.user_id is not None:
        refs.users.add(trigger.user_id)
    if trigger_type == "field_changed":
        refs.field(trigger.field_id, "trigger", trigger)
    for condition in conditions:
        if condition.type == "has_label":
            refs.labels.add(condition.label_id)
        elif condition.type == "field":
            refs.field(condition.field_id, "condition", condition)
        elif condition.type in ("assigned", "actor") and condition.user_id is not None:
            refs.users.add(condition.user_id)
    for action in actions:
        kind = action.type
        if kind in ("add_label", "remove_label"):
            refs.labels.add(action.label_id)
        elif kind in ("add_assignee", "remove_assignee"):
            refs.users.add(action.user_id)
        elif kind in ("random_assignee", "round_robin_assignee", "notify"):
            refs.users.update(action.user_ids)
        elif kind == "set_supervisor" and action.user_id is not None:
            refs.users.add(action.user_id)
        elif kind == "add_checklist" and action.template_id:
            refs.templates.add(action.template_id)
        elif kind == "set_field":
            refs.field(action.field_id, "set", action)
        elif kind == "clear_field":
            refs.field(action.field_id, "clear", action)
        elif kind == "increment_field":
            refs.field(action.field_id, "increment", action)
        elif kind == "shift_field_date":
            refs.field(action.field_id, "shift_date", action)
        elif kind == "set_due" and action.mode == "field":
            refs.field(action.field_id, "due_from", action)
        elif kind == "sort_column" and action.by == "field":
            refs.field(action.field_id, "sort", action)


def validate(board, kind: str, trigger: dict, conditions: list, actions: list) -> tuple:
    """Автоматизация целиком → нормализованные ``(trigger, conditions,
    actions)``; ошибка — 422 ``automation_invalid`` с местом в ``details``."""
    if kind not in TRIGGERS_BY_KIND:
        raise _invalid("Неизвестный вид автоматизации")
    trigger_spec = _parse(TRIGGERS_BY_KIND[kind], trigger, "trigger")
    if len(conditions) > MAX_CONDITIONS:
        raise _invalid(f"Условий — не больше {MAX_CONDITIONS}")
    if len(actions) > MAX_ACTIONS:
        raise _invalid(f"Действий — не больше {MAX_ACTIONS}")
    if not actions:
        raise _invalid("Добавьте хотя бы одно действие")
    condition_specs = _parse(_CONDITIONS, conditions, "conditions")
    action_specs = _parse(_ACTIONS, actions, "actions")

    card_scope = _is_card_scope(kind, trigger_spec)
    types = [action.type for action in action_specs]
    if "block" in types:
        if kind != AutomationKind.RULE or trigger_spec.type not in MOVE_TRIGGERS:
            raise _invalid("«Запретить перенос» — только у правила на перенос карточки")
        if len(types) != 1:
            raise _invalid("«Запретить перенос» — единственное действие правила")
    if card_scope:
        if wrong := sorted(set(types) & {"sort_column"}):
            raise _invalid("Сортировка колонки — только у кнопки доски и расписания без "
                           "карточек", actions=wrong)
    else:
        if condition_specs:
            raise _invalid("Условия отбирают карточки — выберите колонку карточек")
        if wrong := sorted(set(types) - BOARD_ACTIONS):
            raise _invalid("Это действие — над карточкой: выберите колонку карточек",
                           actions=wrong)

    refs = _Refs(board)
    _collect(refs, trigger_spec, condition_specs, action_specs)
    refs.check()
    return (trigger_spec.model_dump(mode="json"),
            [condition.model_dump(mode="json") for condition in condition_specs],
            [action.model_dump(mode="json") for action in action_specs])


# ── каталог для конструктора ────────────────────────────────────────────

_TRIGGER_GROUPS = {
    "move": (CardCreated, Moved, StatusMark, ColumnCount),
    "changes": (LabelEvent, AttachmentEvent, AssigneeEvent, SupervisorEvent),
    "dates": (DueEvent,),
    "checklists": (ChecklistEvent, ItemEvent),
    "content": (CommentEvent,),
    "fields": (FieldEvent, FieldsFilledEvent),
}
_ACTION_GROUPS = {
    "move": (MoveAction, RepositionAction, BlockAction),
    "labels": (LabelAction,),
    "tasks": (CreateTaskAction, CopyTaskAction),
    "dates": (SetDueAction, ShiftDueAction),
    "checklists": (AddChecklistAction, ItemAction),
    "members": (UserAction, PickAssigneeAction, SupervisorAction),
    "content": (RenameAction, DescriptionAction, CommentAction, NotifyAction),
    "fields": (SetFieldAction, ClearFieldAction, IncrementFieldAction, ShiftFieldDateAction),
    "sort": (SortColumnAction,),
}
_PLAIN_GROUPS = {
    "cancel": "move", "complete": "move", "remove_all_labels": "labels", "clear_due": "dates",
    "set_start_today": "dates", "clear_start": "dates", "check_all": "checklists",
    "reset_all": "checklists", "join_actor": "members", "remove_all_assignees": "members",
    "watch_actor": "members",
}


def _keys(model) -> list[str]:
    return list(model.model_fields["type"].annotation.__args__)


def _entries(groups: dict) -> list[dict]:
    out = []
    for group, models in groups.items():
        for model in models:
            schema = model.model_json_schema()
            for key in _keys(model):
                out.append({"type": key, "group": group, "schema": schema})
    return out


def describe() -> dict:
    """Каталог для конструктора автоматизации (S5)."""
    actions = _entries(_ACTION_GROUPS)
    plain_schema = PlainAction.model_json_schema()
    actions += [{"type": key, "group": group, "schema": plain_schema}
                for key, group in _PLAIN_GROUPS.items()]
    return {
        "triggers": _entries(_TRIGGER_GROUPS),
        "kinds": {str(kind.value): adapter.json_schema() for kind, adapter in TRIGGERS_BY_KIND.items()
                  if kind != AutomationKind.RULE},
        "conditions": [{"type": key, "schema": model.model_json_schema()}
                       for model in Condition.__origin__.__args__ for key in _keys(model)],
        "actions": actions,
        "board_actions": sorted(BOARD_ACTIONS),
        "move_triggers": sorted(MOVE_TRIGGERS),
        "limits": {"conditions": MAX_CONDITIONS, "actions": MAX_ACTIONS, "people": MAX_PEOPLE},
    }
