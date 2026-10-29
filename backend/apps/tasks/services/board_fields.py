"""Свои поля досок и шаблоны чек-листов (решение K-35, канбан, этап S3).

Поле принадлежит доске отдела или проекта — ключ «вид + id», как у настроек
колонок; у личной доски своих полей и шаблонов нет. Поля задачи — поля её
ДОМАШНИХ досок: отдела ``Task.department_id`` и проекта ``Task.project_id``.
Доска вышестоящего отдела показывает карточки поддерева, но свои поля к ним
не применяет: иначе на задачу действовали бы два набора полей (и правил
автоматизации S4).

Определения полей и шаблоны правит администратор доски (K-39,
``board_service.require_admin``), значение — тот, кто ведёт задачу
(``require_soft_edit``). Значение — одна строка ``TaskFieldValue`` на пару
«задача + поле»; у пустого значения строки нет, флажок без отметки — пустой.
Смена значения — строка журнала задачи ``field:<id>`` с прежним и новым
текстом значения (у списка — название варианта, у флажка — ``true``).
Значения полей прежней доски после переноса задачи остаются в базе, но к ней
не применяются, пока она не вернётся.
"""

from __future__ import annotations

import re
import secrets
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import connection, transaction
from django.db.models import Q
from django.http import Http404

from htqweb.errors import DomainError

from .. import schemas
from ..models import (BoardField, BoardFieldType, BoardKind, BoardSettings, Task,
                      TaskActivity, TaskFieldValue)
from . import board_rank
from . import board_service
from . import hydration
from . import ranked
from . import task_scope
from . import task_service
from .automation import events as automation
from .automation.context import Event

FIELD_LIMIT = 50
TEXT_LIMIT = 500
#: Число — ``Decimal(18, 4)``: до 14 знаков до запятой.
NUMBER_LIMIT = Decimal(10) ** 14
_QUANTUM = Decimal("0.0001")
FIELD_PREFIX = "field:"


def journal_key(field_id: int) -> str:
    return f"{FIELD_PREFIX}{field_id}"


# ── домашние доски задачи ──────────────────────────────────────────────

def home_board_keys(task: Task) -> list[tuple[str, int]]:
    keys = []
    if task.department_id:
        keys.append((BoardKind.DEPARTMENT, task.department_id))
    if task.project_id:
        keys.append((BoardKind.PROJECT, task.project_id))
    return keys


def _keys_q(keys) -> Q:
    by_kind: dict[str, set[int]] = {}
    for kind, board_id in keys:
        by_kind.setdefault(kind, set()).add(board_id)
    condition = Q(pk__in=[])
    for kind, ids in by_kind.items():
        condition |= Q(board_kind=kind, board_id__in=sorted(ids))
    return condition


def _require_shared(board) -> None:
    if board.kind == BoardKind.PERSONAL:
        raise DomainError("board_fields_personal",
                          "У личной доски нет своих полей и шаблонов", status=422)


def _new_id(taken: set[str]) -> str:
    """Короткий id варианта списка или шаблона: не меняется при
    переименовании, на него ссылаются значения и автоматизация."""
    while True:
        value = secrets.token_hex(4)
        if value not in taken:
            taken.add(value)
            return value


# ── определения полей ───────────────────────────────────────────────────

def _option(field: BoardField, option_id: str) -> dict | None:
    return next((option for option in field.options or [] if option["id"] == option_id), None)


def field_payload(field: BoardField) -> dict:
    return {
        "id": field.id,
        "board_kind": field.board_kind,
        "board_id": field.board_id,
        "name": field.name,
        "type": field.field_type,
        "options": [{"id": option["id"], "name": option["name"],
                     "color": option.get("color")} for option in field.options or []],
        "show_on_card": field.show_on_card,
        "position": field.position,
    }


def _board_fields(board) -> list[BoardField]:
    return list(BoardField.objects.filter(board_kind=board.kind, board_id=board.id)
                .order_by("position", "id"))


def list_fields(board) -> list[dict]:
    """Поля доски по порядку; видимость доски проверил ``board_service``."""
    _require_shared(board)
    return [field_payload(field) for field in _board_fields(board)]


def _lock(board) -> None:
    """Поля доски правятся по очереди: два новых поля иначе получили бы один
    ранг, а проверка названия пропустила бы оба."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                       [f"tasks.board_fields:{board.kind}:{board.id}"])


def _check_name(board, name: str, exclude: int | None = None) -> None:
    rows = BoardField.objects.filter(board_kind=board.kind, board_id=board.id, name__iexact=name)
    if exclude is not None:
        rows = rows.exclude(pk=exclude)
    if rows.exists():
        raise DomainError("board_field_name_taken", f"Поле «{name}» на доске уже есть",
                          status=409)


def _options_error(message: str) -> DomainError:
    return DomainError("board_field_options", message, status=422)


def _normalize_options(field_type: str, options: list, existing: list[dict]) -> list[dict]:
    """Варианты списка целиком: с ``id`` — прежние (переименование и цвет), без
    — новые. Чужой ``id`` — 422: клиент правил устаревший список."""
    if field_type != BoardFieldType.LIST:
        if options:
            raise _options_error("Варианты бывают только у поля-списка")
        return []
    known = {option["id"] for option in existing}
    taken, used, names, out = set(known), set(), set(), []
    for option in options:
        if option.id is not None:
            if option.id not in known or option.id in used:
                raise _options_error("Список вариантов изменился — обновите настройки доски")
            used.add(option.id)
        if option.name.casefold() in names:
            raise _options_error(f"Вариант «{option.name}» повторяется")
        names.add(option.name.casefold())
        out.append({"id": option.id or _new_id(taken), "name": option.name,
                    "color": option.color})
    return out


@transaction.atomic
def create_field(request, board, data: schemas.BoardFieldIn) -> dict:
    _require_shared(board)
    board_service.require_admin(request, board)
    _lock(board)
    existing = _board_fields(board)
    if len(existing) >= FIELD_LIMIT:
        raise DomainError("board_field_limit", f"На доске не больше {FIELD_LIMIT} полей",
                          status=422)
    _check_name(board, data.name)
    field = BoardField.objects.create(
        board_kind=board.kind, board_id=board.id, name=data.name, field_type=data.type,
        options=_normalize_options(data.type, data.options, []),
        show_on_card=data.show_on_card,
        position=ranked.position_between(existing, None, None, None,
                                         code="board_field_order_stale", what="поля доски"),
        created_by=request.token.user_id)
    return field_payload(field)


def _field(field_id: int) -> BoardField:
    field = BoardField.objects.filter(pk=field_id).first()
    if field is None:
        raise Http404("Field not found")
    return field


def _admin_board(request, field: BoardField):
    """Доска поля — если видна (404 иначе, как несуществующее поле) и
    вызывающий её администратор (403)."""
    board = board_service.resolve(request, field.board_kind, field.board_id)
    board_service.require_admin(request, board)
    return board


def _clear_options(field: BoardField, removed: dict[str, str], actor: int) -> None:
    """Удалённый вариант списка очищает значения с ним — с журналом у каждой
    задачи: значение пропало не по её правке."""
    rows = list(TaskFieldValue.objects.filter(field=field, value_option__in=list(removed)))
    TaskActivity.objects.bulk_create([
        TaskActivity(task_id=row.task_id, actor_id=actor, field_name=journal_key(field.id),
                     old_value=removed[row.value_option], new_value=None)
        for row in rows])
    TaskFieldValue.objects.filter(pk__in=[row.pk for row in rows]).delete()


@transaction.atomic
def update_field(request, field_id: int, data: schemas.BoardFieldPatch) -> dict:
    """Название, варианты списка, «на карточке» и место. Тип не меняется
    (схема его не принимает)."""
    board = _admin_board(request, _field(field_id))
    _lock(board)
    field = BoardField.objects.select_for_update().filter(pk=field_id).first()
    if field is None:                     # удалили, пока ждали блокировку
        raise Http404("Field not found")
    if data.name is not None and data.name != field.name:
        _check_name(board, data.name, exclude=field.pk)
        field.name = data.name
    if data.show_on_card is not None:
        field.show_on_card = data.show_on_card
    if data.options is not None:
        options = _normalize_options(field.field_type, data.options, field.options or [])
        kept = {option["id"] for option in options}
        removed = {option["id"]: option["name"] for option in field.options or []
                   if option["id"] not in kept}
        for option_id, option_name in removed.items():
            # Вариант из настроек автоматизации доски не удаляется (решение L-01).
            _ensure_unused(field, f"Вариант «{option_name}» поля «{field.name}»",
                           field_id=field.pk, option_id=option_id)
        if removed:
            _clear_options(field, removed, request.token.user_id)
        field.options = options
    if data.move:
        field.position = ranked.position_between(
            _board_fields(board), field.id, data.before_id, data.after_id,
            code="board_field_order_stale", what="поля доски")
    field.save()
    if board_rank.needs_rebalance(field.position):
        ranked.respread(_board_fields(board))
        field.refresh_from_db()
    return field_payload(field)


@transaction.atomic
def delete_field(request, field_id: int) -> None:
    """Поле уходит вместе со значениями (каскад); журнал задач не пишется —
    поля больше нет, и называть в ленте нечего."""
    field = _field(field_id)
    _admin_board(request, field)
    # Поле из настроек автоматизации доски не удаляется (решение L-01).
    _ensure_unused(field, f"Поле «{field.name}»", field_id=field.pk)
    field.delete()


def _ensure_unused(field: BoardField, what: str, **ref) -> None:
    from .automation import refs

    refs.ensure_unused(field.board_kind, field.board_id, what, **ref)


# ── значения ────────────────────────────────────────────────────────────

def _number_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def value_json(field: BoardField, row: TaskFieldValue | None):
    """Значение для ответа: текст, число строкой, дата ISO, ``id`` варианта;
    флажок — всегда ``bool``; пустое — ``None``."""
    if field.field_type == BoardFieldType.CHECKBOX:
        return bool(row is not None and row.value_bool)
    if row is None:
        return None
    if field.field_type == BoardFieldType.TEXT:
        return row.value_text or None
    if field.field_type == BoardFieldType.NUMBER:
        return _number_text(row.value_number) if row.value_number is not None else None
    if field.field_type == BoardFieldType.DATE:
        return row.value_date.isoformat() if row.value_date else None
    return row.value_option if _option(field, row.value_option) else None


def _journal_text(field: BoardField, row: TaskFieldValue | None) -> str | None:
    """Текст значения для журнала: у списка — название варианта на момент
    правки, у флажка — ``true``."""
    value = value_json(field, row)
    if field.field_type == BoardFieldType.CHECKBOX:
        return "true" if value else None
    if field.field_type == BoardFieldType.LIST and value is not None:
        return _option(field, value)["name"]
    return value


def _invalid(message: str) -> DomainError:
    return DomainError("board_field_value_invalid", message, status=422)


def parse_value(field: BoardField, raw):
    """Присланное значение → значение столбца; ``None`` — очистить. Им же
    каталог автоматизации проверяет значения полей в правилах."""
    if raw is None:
        return None
    kind = field.field_type
    if kind == BoardFieldType.CHECKBOX:
        if not isinstance(raw, bool):
            raise _invalid("Флажок — да или нет")
        return True if raw else None
    if kind == BoardFieldType.NUMBER:
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            raise _invalid("Значение поля — число")
        # Пробелы (и неразрывные) — разряды, запятая — дробная часть.
        text = re.sub(r"\s+", "", str(raw)).replace(",", ".")
        if not text:
            return None
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise _invalid("Значение поля — число") from exc
        if not number.is_finite() or abs(number) >= NUMBER_LIMIT:
            raise _invalid("Число поля — до 14 знаков до запятой")
        return number.quantize(_QUANTUM, rounding=ROUND_HALF_UP)
    if not isinstance(raw, str):
        raise _invalid("Значение поля — строка")
    text = raw.strip()
    if not text:
        return None
    if kind == BoardFieldType.TEXT:
        if len(text) > TEXT_LIMIT:
            raise _invalid(f"Текст поля — не длиннее {TEXT_LIMIT} символов")
        return text
    if kind == BoardFieldType.DATE:
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise _invalid("Дата поля — ГГГГ-ММ-ДД") from exc
    if _option(field, text) is None:
        raise _invalid("Такого варианта в списке нет — обновите карточку")
    return text


def _store(row: TaskFieldValue, field: BoardField, value) -> None:
    row.value_text, row.value_number, row.value_date = "", None, None
    row.value_bool, row.value_option = None, ""
    column = {
        BoardFieldType.TEXT: "value_text", BoardFieldType.NUMBER: "value_number",
        BoardFieldType.DATE: "value_date", BoardFieldType.CHECKBOX: "value_bool",
        BoardFieldType.LIST: "value_option",
    }[field.field_type]
    setattr(row, column, value)


def _lock_task(task_id: int, request) -> Task:
    """Видимость (404), право вести задачу (403) и блокировка её строки —
    отдельным запросом, как у чек-листов."""
    task = task_service.load_for_action(task_id, request)
    task_service.require_soft_edit(task, request)
    return Task.objects.select_for_update().get(pk=task.pk)


@transaction.atomic
def set_value(request, task_id: int, field_id: int, raw) -> dict:
    """Задать или очистить значение поля задачи. Поле не с домашней доски
    задачи — 404, как несуществующее. Ответ — ``home_boards`` карточки."""
    task = _lock_task(task_id, request)
    field = BoardField.objects.filter(pk=field_id).first()
    if field is None or (field.board_kind, field.board_id) not in home_board_keys(task):
        raise Http404("Field not found")
    scope = task_scope.for_request(request)
    store_value(task, field, parse_value(field, raw), scope.user_id)
    return {"home_boards": home_boards(task, scope)}


def store_value(task: Task, field: BoardField, value, actor: int | None) -> None:
    """Записать разобранное значение (``parse_value``) или очистить (``None``)
    — без проверки прав: её сделал вызывающий (ручка или автоматизация, S4).
    Смена — строка журнала и событие автоматизации ``field_changed``."""
    row = TaskFieldValue.objects.filter(task=task, field=field).first()
    before, before_json = _journal_text(field, row), value_json(field, row)
    if value is None:
        if row is not None:
            row.delete()
            row = None
    else:
        row = row or TaskFieldValue(task=task, field=field)
        _store(row, field, value)
        row.updated_by = actor
        row.save()
    after = _journal_text(field, row)
    if before == after:
        return
    task_service._log(task, actor, journal_key(field.id), before, after)
    automation.emit(Event("field_changed", task.pk, actor, {
        "field_id": field.pk, "field_type": field.field_type, "board_kind": field.board_kind,
        "board_id": field.board_id, "old": before_json, "new": value_json(field, row)}))


# ── шаблоны чек-листов ──────────────────────────────────────────────────

def templates_of(row: BoardSettings | None) -> list[dict]:
    if row is None:
        return []
    return [{"id": item["id"], "title": item["title"], "items": list(item.get("items") or [])}
            for item in row.checklist_templates or []]


def normalize_templates(templates: list, existing: list[dict]) -> list[dict]:
    """Шаблоны доски целиком: с ``id`` — прежние, без — новые (``id`` выдаёт
    сервер). Чужой ``id`` — 422: клиент правил устаревший список."""
    known = {item["id"] for item in existing}
    taken, used, out = set(known), set(), []
    for template in templates:
        if template.id is not None:
            if template.id not in known or template.id in used:
                raise DomainError("checklist_template_unknown",
                                  "Шаблоны изменились — обновите настройки доски", status=422)
            used.add(template.id)
        out.append({"id": template.id or _new_id(taken), "title": template.title,
                    "items": list(template.items)})
    return out


def template_for(task: Task, board_kind: str, board_id: int, template_id: str) -> dict:
    """Шаблон домашней доски задачи; нет такого — 422 (карточка устарела)."""
    if (board_kind, board_id) in home_board_keys(task):
        row = BoardSettings.objects.filter(board_kind=board_kind, board_id=board_id).first()
        for template in templates_of(row):
            if template["id"] == template_id:
                return template
    raise DomainError("checklist_template_unknown",
                      "Шаблона нет на досках задачи — обновите карточку", status=422)


# ── ответы ──────────────────────────────────────────────────────────────

def home_boards(task: Task, scope=None) -> list[dict]:
    """Домашние доски карточки задачи: поля со значениями, шаблоны
    чек-листов и кнопки автоматизации (поле ``home_boards`` карточки).
    ``scope`` — кто смотрит: кнопки — тому, кто вправе вести задачу."""
    from .automation import buttons

    keys = home_board_keys(task)
    if not keys:
        return []
    card_buttons = buttons.card_buttons(task, scope)
    fields = list(BoardField.objects.filter(_keys_q(keys)).order_by("position", "id"))
    values = ({row.field_id: row for row in TaskFieldValue.objects.filter(
        task=task, field_id__in=[field.id for field in fields])} if fields else {})
    settings = {(row.board_kind, row.board_id): row
                for row in BoardSettings.objects.filter(_keys_q(keys))}
    titles = {}
    if task.department_id:
        briefs = hydration.department_briefs([task.department_id])
        titles[(BoardKind.DEPARTMENT, task.department_id)] = hydration.department_name(
            briefs, task.department_id)
    if task.project_id:
        titles[(BoardKind.PROJECT, task.project_id)] = task.project.name
    return [{
        "kind": kind,
        "id": board_id,
        "title": titles.get((kind, board_id)),
        "fields": [field_payload(field) | {"value": value_json(field, values.get(field.id))}
                   for field in fields if (field.board_kind, field.board_id) == (kind, board_id)],
        "checklist_templates": templates_of(settings.get((kind, board_id))),
        "buttons": card_buttons.get((kind, board_id), []),
    } for kind, board_id in keys]


def card_fields(tasks: list[Task]) -> dict[int, list[dict]]:
    """Значки полей «на карточке» для карточек доски — двумя запросами на всю
    доску. Пустые значения и снятые флажки не показываются."""
    keys = {key for task in tasks for key in home_board_keys(task)}
    if not keys:
        return {}
    fields = list(BoardField.objects.filter(_keys_q(keys), show_on_card=True)
                  .order_by("position", "id"))
    if not fields:
        return {}
    by_board: dict[tuple[str, int], list[BoardField]] = {}
    for field in fields:
        by_board.setdefault((field.board_kind, field.board_id), []).append(field)
    values = {(row.task_id, row.field_id): row for row in TaskFieldValue.objects.filter(
        task_id__in=[task.id for task in tasks], field_id__in=[field.id for field in fields])}
    out: dict[int, list[dict]] = {}
    for task in tasks:
        badges = []
        for key in home_board_keys(task):
            for field in by_board.get(key, ()):
                value = value_json(field, values.get((task.id, field.id)))
                if value is None or value is False:
                    continue
                option = _option(field, value) if field.field_type == BoardFieldType.LIST else None
                badges.append({"id": field.id, "name": field.name, "type": field.field_type,
                               "value": value, "option": option})
        if badges:
            out[task.id] = badges
    return out


def journal_fields(field_names) -> dict[int, BoardField]:
    """Поля, названные строками журнала ``field:<id>`` — для ленты карточки."""
    ids = {int(name[len(FIELD_PREFIX):]) for name in field_names
           if name.startswith(FIELD_PREFIX) and name[len(FIELD_PREFIX):].isdigit()}
    return {field.id: field for field in BoardField.objects.filter(pk__in=ids)} if ids else {}
