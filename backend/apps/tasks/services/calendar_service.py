"""Calendar events, RSVP, exceptions and the production calendar.

Ported from ``services/task/app/api/v1/calendar.py``.

Visibility (``visible_events_q``) is the load-bearing part: a user sees an
event if it is company-wide, they authored it, they are an invited
participant, or it is a department event for their own department. The
department branch predates the participants table and is kept so employees
keep seeing department-wide events posted by their head without an explicit
invite.

Two Р2 consequences:

* the caller's department came from the user replica and now comes from
  ``apps.hr.interface``; when hr cannot answer, the department branch simply
  drops out — the user still sees global, authored and invited events, and
  never *more* than before;
* ``_notify_invitees`` used to filter recipients against the replica because
  ``Notification.recipient_id`` was a FK and an unknown id raised 23503.
  There is no FK any more, so every invitee is notified and an id the users
  app cannot resolve just renders without a name.
"""

from __future__ import annotations

import datetime as dt

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404

from ..models import (
    CalendarEvent, CalendarEventParticipant, EventException, Notification,
    ProductionDay, Task,
)
from . import hydration
from .production_calendar import (WORKING_DAY_TYPES, base_day_type, base_note,
                                  iter_calendar_days)

MAX_RANGE_DAYS = 370


# ── visibility ──────────────────────────────────────────────────────────

def visible_events_q(user_id: int | None, department_id: int | None) -> Q:
    if user_id is None:
        return Q(is_global=True)
    q = (Q(is_global=True)
         | Q(creator_id=user_id)
         | Q(participants__user_id=user_id))
    if department_id is not None:
        q |= Q(event_type="department", department_id=department_id)
    return q


def _is_editor(event: CalendarEvent, token) -> bool:
    """Author OR admin/HR staff may mutate an event."""
    if token.user_id and event.creator_id == token.user_id:
        return True
    return bool(getattr(token, "is_admin", False)
                or getattr(token, "is_staff", False))


# ── response building ───────────────────────────────────────────────────

def _participants_payload(event: CalendarEvent, users: dict[int, dict]) -> list[dict]:
    out = []
    for participant in event.participants.all():
        brief = users.get(participant.user_id)
        out.append({
            "user_id": participant.user_id,
            # "" not None when unresolved — the original produced an empty
            # string from its replica miss and the picker relies on it.
            "full_name": (brief or {}).get("full_name") or "",
            "email": (brief or {}).get("email") or None,
            # The users brief carries no avatar (see hydration.py's known
            # gap); the key exists so the frontend can always read it.
            "avatar_url": hydration.user_avatar(users, participant.user_id),
            "rsvp_status": participant.rsvp_status or "pending",
        })
    return out


def _hydrate_users(events: list[CalendarEvent]) -> dict[int, dict]:
    ids: set[int] = set()
    for event in events:
        if event.creator_id:
            ids.add(event.creator_id)
        for participant in event.participants.all():
            ids.add(participant.user_id)
    return hydration.user_briefs(ids)


def event_payload(event: CalendarEvent, users: dict[int, dict]) -> dict:
    """Plain-dict form of the event response.

    Built by hand rather than from the ORM object because the participant
    rows have to be reshaped into the compact info form — same reason the
    original spelled it out.
    """
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "start_at": event.start_at,
        "end_at": event.end_at,
        "is_all_day": event.is_all_day,
        "event_type": event.event_type,
        "conference_room_id": event.conference_room_id,
        "color": event.color,
        "is_global": event.is_global,
        "department_id": event.department_id,
        "creator_id": event.creator_id,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
        "exceptions": [
            {"id": exc.id, "event_id": exc.event_id,
             "exception_date": exc.exception_date,
             "is_cancelled": exc.is_cancelled}
            for exc in event.exceptions.all()
        ],
        "participants": _participants_payload(event, users),
    }


def _with_relations(qs):
    return qs.prefetch_related("exceptions", "participants")


def build_payloads(events: list[CalendarEvent]) -> list[dict]:
    users = _hydrate_users(events)
    return [event_payload(event, users) for event in events]


def reload_payload(event_id: int) -> dict:
    event = _with_relations(CalendarEvent.objects.filter(pk=event_id)).first()
    if event is None:
        raise Http404("Event not found")
    return build_payloads([event])[0]


# ── queries ─────────────────────────────────────────────────────────────

def caller_department(token) -> int | None:
    return hydration.employee_department_id(token.user_id) if token.user_id \
        else None


def list_events(token, department_id: int | None = None) -> list[CalendarEvent]:
    qs = CalendarEvent.objects.filter(
        visible_events_q(token.user_id, caller_department(token)))
    if department_id is not None:
        qs = qs.filter(Q(department_id=department_id) | Q(is_global=True))
    # distinct(): the participants join multiplies rows for an event the
    # caller is invited to more than one way.
    return list(_with_relations(qs).distinct())


def _task_timeline_item(task: Task) -> dict:
    return {
        "id": task.id,
        "key": task.key,
        "summary": task.summary,
        # Slug, with the original's fallback for an unclassified task.
        "task_type": task.task_type.slug if task.task_type else "task",
        "priority": task.priority,
        "status": task.status,
        "reporter_id": task.reporter_id,
        "assignee_id": task.assignee_id,
        "department_id": task.department_id,
        "department_name": None,
        "project_id": task.project_id,
        "parent_id": task.parent_id,
        "due_date": task.due_date,
        "start_date": task.start_date,
        "effective_start_date": task.start_date,
        "effective_due_date": task.due_date,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _event_timeline_item(event: CalendarEvent, users: dict[int, dict]) -> dict:
    """The widget's shape — close to, but not the same as, the response
    model: it carries display fields (``creator_name``) and the legacy
    ``creator``/``department`` keys the existing component still reads."""
    creator = event.creator_id or 0
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description or "",
        "event_type": event.event_type,
        "creator": creator,
        "creator_id": creator,
        "creator_name": (users.get(event.creator_id) or {}).get("full_name")
        or "" if event.creator_id else "",
        "department": event.department_id,
        "department_id": event.department_id,
        "department_name": None,
        "start_at": event.start_at.isoformat() if event.start_at else None,
        "end_at": event.end_at.isoformat() if event.end_at else None,
        "is_all_day": event.is_all_day,
        # Recurrence was never implemented — the key exists, always null.
        "rrule": None,
        "color": event.color,
        "conference_room_id": event.conference_room_id,
        "is_global": event.is_global,
        "participants": _participants_payload(event, users),
        "exceptions": [
            {"id": exc.id, "event": exc.event_id,
             "original_date": exc.exception_date.isoformat(),
             "is_cancelled": exc.is_cancelled}
            for exc in event.exceptions.all()
        ],
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


def timeline(token, range_start: dt.date, range_end: dt.date) -> dict:
    window_start = dt.datetime.combine(range_start, dt.time.min,
                                       tzinfo=dt.timezone.utc)
    window_end = dt.datetime.combine(range_end, dt.time.max,
                                     tzinfo=dt.timezone.utc)
    events = list(_with_relations(
        CalendarEvent.objects
        .filter(start_at__lte=window_end, end_at__gte=window_start)
        .filter(visible_events_q(token.user_id, caller_department(token)))
        .distinct()
    ).order_by("start_at"))

    # A task shows on the timeline if its date span touches the window; a
    # single-dated task is a point that must fall inside it.
    tasks = list(Task.objects.filter(is_deleted=False).filter(
        Q(start_date__isnull=False, due_date__isnull=False,
          start_date__lte=range_end, due_date__gte=range_start)
        | Q(start_date__isnull=False, due_date__isnull=True,
            start_date__gte=range_start, start_date__lte=range_end)
        | Q(due_date__isnull=False, start_date__isnull=True,
            due_date__gte=range_start, due_date__lte=range_end)
    ).select_related("task_type").order_by("-created_at"))

    users = _hydrate_users(events)
    return {
        "tasks": [_task_timeline_item(task) for task in tasks],
        "events": [_event_timeline_item(event, users) for event in events],
    }


# ── mutations ───────────────────────────────────────────────────────────

def _replace_participants(event: CalendarEvent, user_ids: set[int], *,
                          accepted_author_id: int | None) -> None:
    """Set the participant list, seeding rsvp_status for new rows.

    The author lands as ``accepted`` (implicit attendance); other new rows
    arrive ``pending``. Existing rows keep whatever the invitee chose —
    removing and re-adding someone is deliberately treated as a fresh invite.
    """
    existing = {row.user_id: row for row in event.participants.all()}
    event.participants.exclude(user_id__in=user_ids).delete()
    CalendarEventParticipant.objects.bulk_create([
        CalendarEventParticipant(
            event=event, user_id=uid,
            rsvp_status="accepted" if uid == accepted_author_id else "pending")
        for uid in user_ids if uid not in existing
    ])


_VERB_TEXT = {
    "calendar_invited": "пригласил(а) на событие",
    "calendar_updated": "обновил(а) событие",
}


def _notify_invitees(event: CalendarEvent, *, actor_id: int | None,
                     recipient_ids: set[int], verb: str) -> None:
    targets = {uid for uid in recipient_ids if uid and uid != actor_id}
    if not targets:
        return
    title = (event.title or "")[:140]
    prefix = _VERB_TEXT.get(verb)
    readable = f"{prefix} «{title}»" if prefix else f"{verb}: «{title}»"
    Notification.objects.bulk_create([
        Notification(recipient_id=uid, actor_id=actor_id, task=None,
                     target_type="calendar_event", target_id=event.id,
                     verb=readable)
        for uid in sorted(targets)
    ])


def _sync_is_global(payload: dict) -> None:
    """Keep the legacy ``is_global`` column in step with ``event_type`` so
    old consumers filtering on it stay correct."""
    if payload.get("event_type") == "common":
        payload["is_global"] = True
    elif payload.get("event_type") in {"personal", "department", "conference"}:
        payload["is_global"] = False


@transaction.atomic
def create_event(payload: dict, *, creator_id: int | None) -> int:
    participants = payload.pop("participant_user_ids", None) or []
    if payload.get("event_type") == "common":
        payload["is_global"] = True
    event = CalendarEvent.objects.create(**payload, creator_id=creator_id)

    invitees = {int(uid) for uid in participants if uid}
    invitees.discard(creator_id or 0)
    targets = set(invitees)
    if creator_id:
        targets.add(creator_id)
    _replace_participants(event, targets, accepted_author_id=creator_id)
    _notify_invitees(event, actor_id=creator_id, recipient_ids=invitees,
                     verb="calendar_invited")
    return event.id


@transaction.atomic
def update_event(event_id: int, changes: dict, token) -> int:
    event = _with_relations(CalendarEvent.objects.filter(pk=event_id)).first()
    if event is None:
        raise Http404("Event not found")
    if not _is_editor(event, token):
        raise PermissionDenied("Only the author can edit this event")

    participants = changes.pop("participant_user_ids", None)
    _sync_is_global(changes)
    for field, value in changes.items():
        setattr(event, field, value)
    event.save()

    if participants is not None:
        previously = {p.user_id for p in event.participants.all()}
        targets = {int(uid) for uid in participants if uid}
        if event.creator_id:
            targets.add(event.creator_id)
        _replace_participants(event, targets,
                              accepted_author_id=event.creator_id)
        newly = {uid for uid in targets
                 if uid not in previously and uid != event.creator_id}
        if newly:
            _notify_invitees(event, actor_id=token.user_id,
                             recipient_ids=newly, verb="calendar_invited")
    return event.id


def delete_event(event_id: int, token) -> None:
    event = CalendarEvent.objects.filter(pk=event_id).first()
    if event is None:
        raise Http404("Event not found")
    if not _is_editor(event, token):
        raise PermissionDenied("Only the author can delete this event")
    event.delete()


def rsvp(event_id: int, user_id: int, status: str) -> int:
    """Only an invited user may respond. Not being invited is 403, not 404 —
    the original distinguished the two, and the event's existence is not a
    secret from someone who has its id."""
    row = CalendarEventParticipant.objects.filter(event_id=event_id,
                                                  user_id=user_id).first()
    if row is None:
        raise PermissionDenied("You are not invited to this event")
    row.rsvp_status = status
    row.save(update_fields=["rsvp_status"])
    return event_id


def create_exception(event_id: int, *, exception_date: dt.date,
                     is_cancelled: bool) -> EventException:
    if not CalendarEvent.objects.filter(pk=event_id).exists():
        raise Http404("Event not found")
    return EventException.objects.create(event_id=event_id,
                                         exception_date=exception_date,
                                         is_cancelled=is_cancelled)


def delete_exception(exception_id: int) -> None:
    row = EventException.objects.filter(pk=exception_id).first()
    if row is None:
        raise Http404("Exception not found")
    row.delete()


# ── production calendar ─────────────────────────────────────────────────

def _overrides(start: dt.date, end: dt.date) -> dict[dt.date, ProductionDay]:
    return {day.date: day for day in
            ProductionDay.objects.filter(date__gte=start, date__lte=end)}


def list_production_days(start: dt.date, end: dt.date) -> list[dict]:
    """Generated baseline (KZ weekends + 2026 holidays) with stored rows
    acting as manual overrides.

    Overrides are fetched from 1 January so the running working-day counter
    is correct for the first requested day, not just from ``start``.
    """
    return list(iter_calendar_days(start, end,
                                   _overrides(dt.date(start.year, 1, 1), end)))


@transaction.atomic
def update_production_day(target_date: dt.date, *, day_type: str,
                          note: str | None) -> ProductionDay:
    day = ProductionDay.objects.filter(date=target_date).first()
    if day is None:
        day = ProductionDay(date=target_date, working_days_since_epoch=0)
    day.day_type = day_type
    # An explicit note wins; otherwise the holiday's own name is restored.
    day.note = note if note is not None else base_note(target_date)
    day.save()

    _recalculate_year(target_date.year)
    day.refresh_from_db()
    return day


def _recalculate_year(year: int) -> None:
    """Re-stamp ``working_days_since_epoch`` on every stored row of the year.

    Flipping one day between working and holiday shifts the running counter
    for every later stored row, and that counter is what
    ``due_date_from_working_days`` reads — leaving it stale would silently
    mis-compute deadlines.
    """
    start, end = dt.date(year, 1, 1), dt.date(year, 12, 31)
    overrides = _overrides(start, end)
    if not overrides:
        return
    updated = []
    for item in iter_calendar_days(start, end, overrides):
        stored = overrides.get(item["date"])
        if stored is not None:
            stored.working_days_since_epoch = int(
                item["working_days_since_epoch"])
            updated.append(stored)
    ProductionDay.objects.bulk_update(updated, ["working_days_since_epoch"])


def default_day_type(target_date: dt.date) -> str:
    return base_day_type(target_date)


def working_days_between(start: dt.date, end: dt.date) -> int | None:
    """Сколько рабочих дней в отрезке ``start..end`` включительно.

    Живёт здесь, а не в ``sequence_service`` рядом с
    ``due_date_from_working_days``, по одной причине: ``ProductionDay`` — это
    таблица ПЕРЕОПРЕДЕЛЕНИЙ, а не календарь. Базовый календарь считается на
    лету (``iter_calendar_days``), и в обычной базе строк нет вообще. Функция,
    считающая по таблице, вернула бы «календаря нет» почти всегда; считать
    надо тем же способом, что и ``list_production_days`` выше.

    Разность ``working_days_since_epoch`` тоже не годится, хотя была бы
    дешевле: счётчик сбрасывается 1 января (см. докстринг
    ``production_calendar``), и на отрезке через Новый год дал бы
    отрицательное число. Роудмап живёт месяцами, такие отрезки для него —
    норма.

    ``None`` для перевёрнутого отрезка. Он реален: фактические границы
    роудмапа это ``min(start_date)`` и ``max(due_date)`` по его задачам, а у
    задачи может быть заполнено только одно из двух полей.
    """
    if start is None or end is None or end < start:
        return None
    overrides = _overrides(dt.date(start.year, 1, 1), end)
    return sum(1 for day in iter_calendar_days(start, end, overrides)
               if day["day_type"] in WORKING_DAY_TYPES)


def calendar_days_between(start: dt.date, end: dt.date) -> int | None:
    """Сколько КАЛЕНДАРНЫХ дней в отрезке ``start..end`` включительно.

    Пара к ``working_days_between``, а не «упрощённая версия»: на стройке,
    которая идёт 7/7, это и есть правильная мера, а рабочие дни — режим для
    офисных проектов (``Project.use_production_calendar``).

    ``None`` на перевёрнутом отрезке — по той же причине и с тем же смыслом,
    что у соседки: «сравнивать не с чем», а не «ноль дней».
    """
    if start is None or end is None or end < start:
        return None
    return (end - start).days + 1


def days_between(start: dt.date, end: dt.date, *,
                 working: bool) -> int | None:
    """Длительность отрезка в той мере, которую выбрал проект.

    Одна точка входа вместо ``if`` в каждом вызывающем: мера длительности —
    свойство проекта, и разъехаться у плана с фактом она не должна.
    """
    return (working_days_between(start, end) if working
            else calendar_days_between(start, end))
