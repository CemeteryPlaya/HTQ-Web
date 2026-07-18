"""Calendar API endpoints."""

import datetime as _dt
from datetime import date, timedelta
from typing import Annotated

import httpx
import jwt as _jwt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import TokenPayload, get_current_user
from app.core.settings import settings
from app.db import get_db

_log = structlog.get_logger()
from app.models.calendar import CalendarEvent, CalendarEventParticipant, EventException
from app.models.notification import Notification
from app.models.sequence import ProductionDay
from app.models.task import Task
from app.models.user_replica import User as UserReplica
from app.schemas.calendar import (
    CalendarEventCreate,
    CalendarEventResponse,
    CalendarEventUpdate,
    EventExceptionBase,
    EventExceptionResponse,
    ProductionDayResponse,
    ProductionDayUpdate,
    RsvpUpdate,
)
from app.services.production_calendar import base_day_type, base_note, iter_calendar_days

router = APIRouter(prefix="/calendar", tags=["calendar"])
production_router = APIRouter(prefix="/production-calendar", tags=["production-calendar"])


def _participants_to_info(
    event: CalendarEvent, users: dict[int, UserReplica]
) -> list[dict]:
    """Hydrate participant ids with task_users replica info when present."""
    out: list[dict] = []
    for p in event.participants:
        u = users.get(p.user_id)
        full_name = ""
        email = None
        if u is not None:
            full_name = f"{u.first_name} {u.last_name}".strip() or u.username
            email = u.email or None
        out.append(
            {
                "user_id": p.user_id,
                "full_name": full_name,
                "email": email,
                # task_users replica doesn't carry avatars yet — placeholder so
                # the frontend can always rely on the key existing.
                "avatar_url": None,
                "rsvp_status": p.rsvp_status or "pending",
            }
        )
    return out


def _event_to_timeline_item(
    event: CalendarEvent, users: dict[int, UserReplica] | None = None
) -> dict:
    """Build the timeline item the SPA renders.

    The shape is intentionally close to (but not identical to) the
    response model — it carries denormalised display fields like
    ``creator_name`` and the legacy ``creator`` / ``department`` keys
    that the existing widget consumes.
    """
    users = users or {}
    creator = event.creator_id or 0
    creator_user = users.get(event.creator_id) if event.creator_id else None
    creator_name = (
        f"{creator_user.first_name} {creator_user.last_name}".strip()
        or creator_user.username
        if creator_user
        else ""
    )
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description or "",
        "event_type": event.event_type,
        "creator": creator,
        "creator_id": creator,
        "creator_name": creator_name,
        "department": event.department_id,
        "department_id": event.department_id,
        "department_name": None,
        "start_at": event.start_at.isoformat() if event.start_at else None,
        "end_at": event.end_at.isoformat() if event.end_at else None,
        "is_all_day": event.is_all_day,
        "rrule": None,
        "color": event.color,
        "conference_room_id": event.conference_room_id,
        "is_global": event.is_global,
        "participants": _participants_to_info(event, users),
        "exceptions": [
            {
                "id": exc.id,
                "event": exc.event_id,
                "original_date": exc.exception_date.isoformat(),
                "is_cancelled": exc.is_cancelled,
            }
            for exc in event.exceptions
        ],
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


def _visibility_clause(user_id: int | None, department_id: int | None = None):
    """Events visible to a given user.

    A user sees an event if any of:
      - it's company-wide (``is_global``),
      - they authored it,
      - they're in the participants table,
      - it's a department event for a department they belong to.

    The department branch preserves the pre-participants semantics so
    sotrudniki of «Финансовый отдел» keep seeing department events
    posted by their head, even when no explicit invite was issued.
    """
    if user_id is None:
        return CalendarEvent.is_global.is_(True)
    clauses = [
        CalendarEvent.is_global.is_(True),
        CalendarEvent.creator_id == user_id,
        CalendarEvent.id.in_(
            select(CalendarEventParticipant.event_id).where(
                CalendarEventParticipant.user_id == user_id
            )
        ),
    ]
    if department_id is not None:
        clauses.append(
            and_(
                CalendarEvent.event_type == "department",
                CalendarEvent.department_id == department_id,
            )
        )
    return or_(*clauses)


async def _current_user_department(
    db: AsyncSession, user_id: int | None
) -> int | None:
    """Look up the caller's department from the local replica.

    Used to scope department-only events. Returns ``None`` if the
    replica doesn't know the user (which only happens before pub/sub
    catches up).
    """
    if not user_id:
        return None
    row = await db.execute(
        select(UserReplica.department_id).where(UserReplica.id == user_id)
    )
    return row.scalar_one_or_none()


def _is_event_editor(event: CalendarEvent, current_user: TokenPayload) -> bool:
    """Author OR admin/HR can mutate the event."""
    user_id = getattr(current_user, "user_id", None)
    if user_id and event.creator_id == user_id:
        return True
    return bool(getattr(current_user, "is_admin", False) or getattr(current_user, "is_staff", False))


async def _hydrate_users_for_events(
    db: AsyncSession, events: list[CalendarEvent]
) -> dict[int, UserReplica]:
    """Look up creator + participant ids in the task_users replica.

    Returns ``{user_id: User}`` for every id we found a replica row for.
    Ids missing from the replica simply won't get a name in the response.
    """
    ids: set[int] = set()
    for e in events:
        if e.creator_id:
            ids.add(e.creator_id)
        for p in e.participants:
            ids.add(p.user_id)
    if not ids:
        return {}
    result = await db.execute(select(UserReplica).where(UserReplica.id.in_(ids)))
    return {u.id: u for u in result.scalars().all()}


async def _replace_participants(
    db: AsyncSession, event_id: int, user_ids: list[int]
) -> None:
    """Idempotently set the participant list. Empty list clears."""
    existing = await db.execute(
        select(CalendarEventParticipant).where(
            CalendarEventParticipant.event_id == event_id
        )
    )
    by_id: dict[int, CalendarEventParticipant] = {
        row.user_id: row for row in existing.scalars().all()
    }
    target = set(user_ids)
    # Remove stale
    for uid, row in by_id.items():
        if uid not in target:
            await db.delete(row)
    # Add missing
    for uid in target:
        if uid not in by_id:
            db.add(CalendarEventParticipant(event_id=event_id, user_id=uid))


def _task_to_timeline_item(task: Task) -> dict:
    return {
        "id": task.id,
        "key": task.key,
        "summary": task.summary,
        "task_type": task.task_type,
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


@router.get("/timeline/")
async def calendar_timeline(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """Return task and calendar items for the SPA calendar widget."""
    range_start = start or date.today().replace(day=1)
    range_end = end or (range_start + timedelta(days=31))
    if range_start > range_end:
        raise HTTPException(status_code=400, detail="start must be before end")
    if (range_end - range_start).days > 370:
        raise HTTPException(status_code=400, detail="Date range is too large")

    user_id = getattr(current_user, "user_id", None)
    department_id = await _current_user_department(db, user_id)
    # Inclusive day range — events that touch any moment of the
    # window should appear. We compare on raw timestamptz columns
    # against the day boundaries.
    window_start = _dt.datetime.combine(
        range_start, _dt.time.min, tzinfo=_dt.timezone.utc
    )
    window_end = _dt.datetime.combine(
        range_end, _dt.time.max, tzinfo=_dt.timezone.utc
    )
    events_result = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.start_at <= window_end,
            CalendarEvent.end_at >= window_start,
            _visibility_clause(user_id, department_id),
        )
        .options(
            selectinload(CalendarEvent.exceptions),
            selectinload(CalendarEvent.participants),
        )
        .order_by(CalendarEvent.start_at.asc())
    )
    events = list(events_result.scalars().all())
    tasks_result = await db.execute(
        select(Task)
        .where(
            Task.is_deleted.is_(False),
            or_(
                and_(
                    Task.start_date.is_not(None),
                    Task.due_date.is_not(None),
                    Task.start_date <= range_end,
                    Task.due_date >= range_start,
                ),
                and_(
                    Task.start_date.is_not(None),
                    Task.due_date.is_(None),
                    Task.start_date >= range_start,
                    Task.start_date <= range_end,
                ),
                and_(
                    Task.due_date.is_not(None),
                    Task.start_date.is_(None),
                    Task.due_date >= range_start,
                    Task.due_date <= range_end,
                ),
            ),
        )
        .order_by(Task.created_at.desc())
    )

    users = await _hydrate_users_for_events(db, events)
    return {
        "tasks": [_task_to_timeline_item(task) for task in tasks_result.scalars().all()],
        "events": [_event_to_timeline_item(event, users) for event in events],
    }


def _event_to_response_dict(
    event: CalendarEvent, users: dict[int, UserReplica]
) -> dict:
    """Plain-dict form of a CalendarEventResponse.

    We build the dict explicitly instead of ``model_validate(event)`` because
    the ORM ``CalendarEvent.participants`` relation yields
    ``CalendarEventParticipant`` rows, which pydantic can't auto-coerce into
    the ``CalendarEventParticipantInfo`` schema. Doing it by hand also keeps
    the JSON shape one place to look at.
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
            {
                "id": exc.id,
                "event_id": exc.event_id,
                "exception_date": exc.exception_date,
                "is_cancelled": exc.is_cancelled,
            }
            for exc in event.exceptions
        ],
        "participants": _participants_to_info(event, users),
    }


async def _build_event_response(db: AsyncSession, event_id: int) -> dict:
    """Load an event with all relations + hydrated participant info."""
    result = await db.execute(
        select(CalendarEvent)
        .where(CalendarEvent.id == event_id)
        .options(
            selectinload(CalendarEvent.exceptions),
            selectinload(CalendarEvent.participants),
        )
    )
    event = result.scalar_one()
    users = await _hydrate_users_for_events(db, [event])
    return _event_to_response_dict(event, users)


async def _notify_invitees(
    db: AsyncSession,
    *,
    event: CalendarEvent,
    actor_id: int | None,
    recipient_ids: set[int],
    verb: str,
) -> None:
    """Insert Notification rows for invitees of an event.

    Skips the actor (you don't notify yourself) and ids missing from the
    ``task_users`` replica (the FK on Notification.recipient_id would 23503).
    The ``verb`` argument controls the human-readable phrasing; the
    structured target reference uses ``target_type='calendar_event'`` so
    the history UI can build a deep link without parsing the verb.
    """
    targets = {uid for uid in recipient_ids if uid and uid != actor_id}
    if not targets:
        return
    known = await db.execute(
        select(UserReplica.id).where(UserReplica.id.in_(targets))
    )
    known_ids = {row for (row,) in known.all()}
    if not known_ids:
        return
    title_short = (event.title or "")[:140]
    if verb == "calendar_invited":
        readable = f"пригласил(а) на событие «{title_short}»"
    elif verb == "calendar_updated":
        readable = f"обновил(а) событие «{title_short}»"
    else:
        readable = f"{verb}: «{title_short}»"
    for uid in known_ids:
        db.add(
            Notification(
                recipient_id=uid,
                actor_id=actor_id,
                task_id=None,
                target_type="calendar_event",
                target_id=event.id,
                verb=readable,
            )
        )


@router.get("/", response_model=list[CalendarEventResponse])
async def list_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
    department_id: int | None = None,
):
    """List calendar events visible to the caller."""
    user_id = getattr(current_user, "user_id", None)
    my_dept = await _current_user_department(db, user_id)
    stmt = (
        select(CalendarEvent)
        .options(
            selectinload(CalendarEvent.exceptions),
            selectinload(CalendarEvent.participants),
        )
        .where(_visibility_clause(user_id, my_dept))
    )
    if department_id is not None:
        stmt = stmt.where(
            (CalendarEvent.department_id == department_id) | (CalendarEvent.is_global.is_(True))
        )
    result = await db.execute(stmt)
    events = list(result.scalars().all())
    users = await _hydrate_users_for_events(db, events)
    return [_event_to_response_dict(ev, users) for ev in events]


@router.post("/", response_model=CalendarEventResponse, status_code=201)
async def create_event(
    data: CalendarEventCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Create a new calendar event.

    The author is automatically added to the participants set with
    ``rsvp_status='accepted'`` so the event is visible on their own
    calendar even if they don't tick themselves in the picker. Invitees
    start with ``pending`` and receive a Notification.
    """
    payload = data.model_dump()
    participants = payload.pop("participant_user_ids", []) or []
    creator_id = getattr(current_user, "user_id", None)
    # Mirror legacy is_global from event_type for the (still-present)
    # column so old consumers keep filtering correctly.
    if payload.get("event_type") == "common":
        payload["is_global"] = True
    event = CalendarEvent(**payload, creator_id=creator_id)
    db.add(event)
    await db.flush()
    invitee_ids = {int(uid) for uid in participants if uid}
    invitee_ids.discard(creator_id or 0)
    target_ids = set(invitee_ids)
    if creator_id:
        target_ids.add(creator_id)
    await _replace_participants_with_status(
        db, event.id, target_ids, accepted_author_id=creator_id
    )
    await _notify_invitees(
        db,
        event=event,
        actor_id=creator_id,
        recipient_ids=invitee_ids,
        verb="calendar_invited",
    )
    await db.commit()
    return await _build_event_response(db, event.id)


@router.patch("/{event_id}/", response_model=CalendarEventResponse)
async def update_event(
    event_id: int,
    data: CalendarEventUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Update a calendar event. Author or admin only."""
    result = await db.execute(
        select(CalendarEvent)
        .where(CalendarEvent.id == event_id)
        .options(
            selectinload(CalendarEvent.exceptions),
            selectinload(CalendarEvent.participants),
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if not _is_event_editor(event, current_user):
        raise HTTPException(status_code=403, detail="Only the author can edit this event")

    update_data = data.model_dump(exclude_unset=True)
    participants = update_data.pop("participant_user_ids", None)
    if update_data.get("event_type") == "common":
        update_data["is_global"] = True
    elif update_data.get("event_type") in {"personal", "department", "conference"}:
        update_data["is_global"] = False
    for k, v in update_data.items():
        setattr(event, k, v)

    previously_invited = {p.user_id for p in event.participants}

    if participants is not None:
        target_ids = {int(uid) for uid in participants if uid}
        if event.creator_id:
            target_ids.add(event.creator_id)
        await _replace_participants_with_status(
            db, event.id, target_ids, accepted_author_id=event.creator_id
        )
        newly_invited = {
            uid
            for uid in target_ids
            if uid not in previously_invited and uid != event.creator_id
        }
        if newly_invited:
            await _notify_invitees(
                db,
                event=event,
                actor_id=getattr(current_user, "user_id", None),
                recipient_ids=newly_invited,
                verb="calendar_invited",
            )

    await db.commit()
    return await _build_event_response(db, event.id)


@router.delete("/{event_id}/", status_code=204)
async def delete_event(
    event_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Delete a calendar event. Author or admin only."""
    result = await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if not _is_event_editor(event, current_user):
        raise HTTPException(status_code=403, detail="Only the author can delete this event")

    await db.delete(event)
    await db.commit()


@router.post("/{event_id}/rsvp/", response_model=CalendarEventResponse)
async def rsvp_event(
    event_id: int,
    data: RsvpUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Respond to a calendar invite.

    Caller must already be in the participants list (i.e. invited). The
    author can also "respond" but typically stays ``accepted``.
    """
    user_id = getattr(current_user, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    row_q = await db.execute(
        select(CalendarEventParticipant).where(
            CalendarEventParticipant.event_id == event_id,
            CalendarEventParticipant.user_id == user_id,
        )
    )
    row = row_q.scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=403,
            detail="You are not invited to this event",
        )
    row.rsvp_status = data.status
    db.add(row)
    await db.commit()
    return await _build_event_response(db, event_id)


async def _replace_participants_with_status(
    db: AsyncSession,
    event_id: int,
    user_ids: set[int],
    *,
    accepted_author_id: int | None,
) -> None:
    """Like ``_replace_participants`` but seeds rsvp_status.

    The author lands as ``accepted`` (implicit attendance); other new rows
    arrive as ``pending``. Existing rows keep whatever status the invitee
    already chose — switching a user out and back in is intentionally
    treated as a fresh invite.
    """
    existing = await db.execute(
        select(CalendarEventParticipant).where(
            CalendarEventParticipant.event_id == event_id
        )
    )
    by_id: dict[int, CalendarEventParticipant] = {
        row.user_id: row for row in existing.scalars().all()
    }
    for uid, row in by_id.items():
        if uid not in user_ids:
            await db.delete(row)
    for uid in user_ids:
        if uid in by_id:
            continue
        db.add(
            CalendarEventParticipant(
                event_id=event_id,
                user_id=uid,
                rsvp_status="accepted" if uid == accepted_author_id else "pending",
            )
        )


class CalendarUserOption(BaseModel):
    """Compact user record for the event participant picker."""

    id: int
    full_name: str
    email: str


async def _fetch_user_options_from_user_service(
    current_user: TokenPayload, query: str | None, limit: int
) -> list[CalendarUserOption]:
    """Proxy ``user-service /api/users/v1/users/options/`` with a short-lived
    internal JWT.

    Used as a fallback when ``task_users`` is empty (replica not seeded yet),
    so the picker is never empty in practice.
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    internal = _jwt.encode(
        {
            "user_id": getattr(current_user, "user_id", 0) or 0,
            "username": getattr(current_user, "username", "") or "",
            "email": getattr(current_user, "email", "") or "",
            "is_staff": getattr(current_user, "is_staff", False),
            "is_superuser": getattr(current_user, "is_superuser", False),
            "is_admin": getattr(current_user, "is_admin", False),
            "token_type": "access",
            "iat": now,
            "exp": now + _dt.timedelta(minutes=2),
            "iss": settings.jwt_issuer,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    url = f"{settings.user_service_url}/api/users/v1/users/options/"
    params: dict[str, str] = {"limit": str(limit)}
    if query:
        params["query"] = query
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {internal}"},
            )
    except httpx.HTTPError as exc:
        _log.warning("calendar_user_options_proxy_failed", err=str(exc))
        return []
    if resp.status_code != 200:
        _log.warning(
            "calendar_user_options_proxy_status", status=resp.status_code
        )
        return []
    data = resp.json() if isinstance(resp.json(), list) else []
    return [
        CalendarUserOption(
            id=int(item.get("id")),
            full_name=str(item.get("full_name") or ""),
            email=str(item.get("email") or ""),
        )
        for item in data
        if item.get("id") is not None
    ]


@router.get("/users-options/", response_model=list[CalendarUserOption])
async def list_user_options(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
    query: str | None = Query(default=None, description="Optional substring filter"),
    limit: int = Query(default=200, ge=1, le=500),
):
    """Return active users for the calendar event participant picker.

    Reads the local ``task_users`` replica first (cheap, no network). If the
    replica is empty — which happens in fresh dev databases until the
    user-service Redis pub/sub catches up — falls back to the user-service
    ``/users/options/`` endpoint over HTTP so the picker is always populated.
    """
    stmt = select(UserReplica).where(UserReplica.is_active.is_(True))
    if query:
        like = f"%{query.lower()}%"
        from sqlalchemy import func

        stmt = stmt.where(
            or_(
                func.lower(UserReplica.first_name).like(like),
                func.lower(UserReplica.last_name).like(like),
                func.lower(UserReplica.email).like(like),
                func.lower(UserReplica.username).like(like),
            )
        )
    stmt = stmt.order_by(UserReplica.last_name.asc(), UserReplica.first_name.asc()).limit(limit)
    result = await db.execute(stmt)
    users = list(result.scalars().all())

    if users:
        return [
            CalendarUserOption(
                id=u.id,
                full_name=f"{u.first_name} {u.last_name}".strip() or u.username,
                email=u.email or "",
            )
            for u in users
        ]

    # Replica empty — go to user-service. The result is intentionally NOT
    # cached locally here: a follow-up cron / pub-sub subscriber owns the
    # replica refresh, and we don't want this endpoint to silently grow a
    # second source of truth.
    return await _fetch_user_options_from_user_service(current_user, query, limit)


@router.post("/{event_id}/exceptions/", response_model=EventExceptionResponse, status_code=201)
async def create_event_exception(
    event_id: int,
    data: EventExceptionBase,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Add an exception to a calendar event."""
    result = await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Event not found")
        
    exc = EventException(event_id=event_id, **data.model_dump())
    db.add(exc)
    await db.commit()
    await db.refresh(exc)
    return exc


@router.delete("/exceptions/{exception_id}/", status_code=204)
async def delete_event_exception(
    exception_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Remove an exception from a calendar event."""
    result = await db.execute(select(EventException).where(EventException.id == exception_id))
    exc = result.scalar_one_or_none()
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")
        
    await db.delete(exc)
    await db.commit()


async def _get_calendar_overrides(
    db: AsyncSession,
    start: date,
    end: date,
) -> dict[date, ProductionDay]:
    result = await db.execute(
        select(ProductionDay).where(
            ProductionDay.date >= start,
            ProductionDay.date <= end,
        )
    )
    return {day.date: day for day in result.scalars().all()}


async def _recalculate_stored_year(db: AsyncSession, year: int) -> None:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    overrides = await _get_calendar_overrides(db, start, end)
    for item in iter_calendar_days(start, end, overrides):
        stored = overrides.get(item["date"])
        if stored:
            stored.working_days_since_epoch = int(item["working_days_since_epoch"])


@production_router.get("/", response_model=list[ProductionDayResponse])
async def list_production_days(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
    date_gte: date | None = Query(None, alias="date__gte"),
    date_lte: date | None = Query(None, alias="date__lte"),
):
    """List production calendar days.

    The generated baseline uses Kazakhstan weekends and official 2026 holidays.
    Stored rows act as manual overrides.
    """
    start = date_gte or date.today().replace(day=1)
    end = date_lte or (start + timedelta(days=31))
    if start > end:
        raise HTTPException(status_code=400, detail="date__gte must be before date__lte")
    if (end - start).days > 370:
        raise HTTPException(status_code=400, detail="Date range is too large")

    overrides = await _get_calendar_overrides(db, date(start.year, 1, 1), end)
    return list(iter_calendar_days(start, end, overrides))


@production_router.patch("/{target_date}/", response_model=ProductionDayResponse)
async def update_production_day(
    target_date: date,
    data: ProductionDayUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Create or update a production calendar day override."""
    result = await db.execute(select(ProductionDay).where(ProductionDay.date == target_date))
    day = result.scalar_one_or_none()
    if not day:
        day = ProductionDay(
            date=target_date,
            day_type=base_day_type(target_date),
            note=base_note(target_date),
            working_days_since_epoch=0,
        )
        db.add(day)

    day.day_type = data.day_type
    day.note = data.note if data.note is not None else base_note(target_date)
    await db.flush()
    await _recalculate_stored_year(db, target_date.year)
    await db.commit()
    await db.refresh(day)
    return day
