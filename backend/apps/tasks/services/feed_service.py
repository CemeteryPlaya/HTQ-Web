"""Лента карточки «Комментарии и события» (мастер-план канбана §6.4, этап S2).

Комментарии и журнал задачи — одной хронологией, новые сверху, страницами по
курсору ``(created_at, вид, id)``: две таблицы с общей сортировкой, поэтому
смещение не годится — новая запись между страницами сдвинула бы его.
``details=0`` — комментарии и ключевые события, ``details=1`` — весь журнал.
Значения журнала гидрируются: id людей и отделов → имена; статусы фронт
переводит сам. Строка своего поля доски (``field:<id>``, этап S3) несёт
``board_field`` — название и тип поля (удалённое — без них). Правка
автоматизации доски (этап S4) несёт ``automation`` — правило и его название;
актор у правила пуст, у кнопки — нажавший. Права — видимость задачи
(``load_for_action``, 404).
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q

from htqweb.errors import DomainError

from ..models import AutomationRule, TaskActivity, TaskComment
from . import board_fields
from . import hydration
from . import task_service

DEFAULT_LIMIT = 30
MAX_LIMIT = 100

#: Ключевые события — видны и без «показать подробности» (§6.4).
KEY_FIELDS = frozenset({
    "status", "transfer", "claim", "checklist_item_checked",
    "access_approved",
})

#: Поля журнала, чьи значения — id пользователей и отделов.
USER_FIELDS = frozenset({"assignee_id", "supervisor_id", "reporter_id", "claim"})
DEPARTMENT_FIELDS = frozenset({"department_id", "transfer"})
#: Запросы доступа: значение — «вид:id запросившего» («own:12»).
ACCESS_FIELDS = frozenset({"access_requested", "access_approved", "access_rejected",
                           "access_cancelled"})

#: Вид записи для курсора: сортировка по убыванию ``(created_at, вид, id)``.
COMMENT, ACTIVITY = "comment", "activity"


def _parse_cursor(raw: str | None) -> tuple[datetime, str, int] | None:
    if not raw:
        return None
    # «+» смещения зоны в адресе без кодирования приходит пробелом.
    raw = raw.replace(" ", "+")
    try:
        stamp, kind, pk = raw.rsplit("~", 2)
        if kind not in (COMMENT, ACTIVITY):
            raise ValueError(kind)
        return datetime.fromisoformat(stamp), kind, int(pk)
    except ValueError as exc:
        raise DomainError("feed_cursor_invalid", "Неверный курсор ленты", status=422) from exc


def _cursor(entry: dict) -> str:
    return f"{entry['created_at'].isoformat()}~{entry['kind']}~{entry['id']}"


def _before(cursor, kind: str) -> Q:
    """Записи СТРОГО раньше курсора в порядке убывания ``(created_at, вид, id)``."""
    if cursor is None:
        return Q()
    stamp, cursor_kind, pk = cursor
    older = Q(created_at__lt=stamp)
    if kind < cursor_kind:
        return older | Q(created_at=stamp)
    if kind == cursor_kind:
        return older | Q(created_at=stamp, pk__lt=pk)
    return older


def _ids(value: str | None) -> int | None:
    """Значение журнала → id (у делегатов — «+12»)."""
    if not value:
        return None
    value = value.lstrip("+")
    return int(value) if value.isdigit() else None


def _requester(value: str | None) -> int | None:
    """Запрос доступа в журнале → id запросившего («own:12» → 12)."""
    return _ids((value or "").partition(":")[2])


def feed(task_id: int, request, *, details: bool, before: str | None,
         limit: int | None) -> dict:
    task_service.load_for_action(task_id, request)                   # невидимая — 404
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    cursor = _parse_cursor(before)

    comments = list(TaskComment.objects.filter(task_id=task_id)
                    .filter(_before(cursor, COMMENT))
                    .order_by("-created_at", "-pk")[:limit + 1])
    activities_qs = TaskActivity.objects.filter(task_id=task_id).filter(_before(cursor, ACTIVITY))
    if not details:
        activities_qs = activities_qs.filter(field_name__in=KEY_FIELDS)
    activities = list(activities_qs.order_by("-created_at", "-pk")[:limit + 1])

    entries = ([{"kind": COMMENT, "row": row, "id": row.pk, "created_at": row.created_at}
                for row in comments]
               + [{"kind": ACTIVITY, "row": row, "id": row.pk, "created_at": row.created_at}
                  for row in activities])
    entries.sort(key=lambda entry: (entry["created_at"], entry["kind"], entry["id"]),
                 reverse=True)
    page, more = entries[:limit], len(entries) > limit

    user_ids, department_ids = set(), set()
    for entry in page:
        row = entry["row"]
        if entry["kind"] == COMMENT:
            user_ids.add(row.author_id)
            continue
        user_ids.add(row.actor_id)
        if row.field_name in USER_FIELDS or row.field_name == "delegates":
            user_ids.update((_ids(row.old_value), _ids(row.new_value)))
        if row.field_name in DEPARTMENT_FIELDS:
            department_ids.update((_ids(row.old_value), _ids(row.new_value)))
        if row.field_name in ACCESS_FIELDS:
            user_ids.add(_requester(row.new_value))
    users = hydration.user_briefs(user_ids)
    departments = hydration.department_briefs(department_ids)
    fields = board_fields.journal_fields(entry["row"].field_name for entry in page
                                         if entry["kind"] == ACTIVITY)
    rule_ids = {entry["row"].via_rule_id for entry in page if entry["row"].via_rule_id}
    rule_names = (dict(AutomationRule.objects.filter(pk__in=rule_ids).values_list("pk", "name"))
                  if rule_ids else {})

    def person(user_id):
        if user_id is None:
            return None
        return {"id": user_id, "name": hydration.user_name(users, user_id),
                "avatar_url": hydration.user_avatar(users, user_id)}

    def label(field: str, value: str | None):
        """Имя за id; остальное фронт показывает как есть или переводит."""
        if field in USER_FIELDS or field == "delegates":
            return hydration.user_name(users, _ids(value))
        if field in DEPARTMENT_FIELDS:
            return hydration.department_name(departments, _ids(value))
        if field in ACCESS_FIELDS:
            return hydration.user_name(users, _requester(value))
        return None

    def automation(rule_id: int | None) -> dict | None:
        # Правку или комментарий сделала автоматизация доски (этап S4, S4b).
        if not rule_id:
            return None
        return {"id": rule_id, "name": rule_names.get(rule_id) or None}

    def board_field(name: str) -> dict | None:
        if not name.startswith(board_fields.FIELD_PREFIX):
            return None
        field_id = _ids(name[len(board_fields.FIELD_PREFIX):])
        found = fields.get(field_id)
        return {"id": field_id, "name": found.name if found else None,
                "type": found.field_type if found else None}

    items = []
    for entry in page:
        row = entry["row"]
        if entry["kind"] == COMMENT:
            items.append({"kind": COMMENT, "id": row.pk, "created_at": row.created_at,
                          "actor": person(row.author_id), "body": row.body,
                          "updated_at": row.updated_at,
                          "automation": automation(row.via_rule_id)})
        else:
            items.append({"kind": ACTIVITY, "id": row.pk, "created_at": row.created_at,
                          "actor": person(row.actor_id), "field": row.field_name,
                          "old": row.old_value, "new": row.new_value,
                          "old_label": label(row.field_name, row.old_value),
                          "new_label": label(row.field_name, row.new_value),
                          "board_field": board_field(row.field_name),
                          "automation": automation(row.via_rule_id)})
    return {"items": items, "next_before": _cursor(page[-1]) if more else None}
