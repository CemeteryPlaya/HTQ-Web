"""Сводный экран конференций: что сегодня и что идёт прямо сейчас.

Два блока собираются из разных источников и намеренно не сводятся в один:
«сегодня» — это план (календарь), «идут сейчас» — факт (открытые сессии).
Встреча, собранная кнопкой «Создать комнату», плана не имеет вовсе и
попадает только во второй блок — придумывать ей плановое время нельзя.
"""

from __future__ import annotations

from django.db.models import Count
from django.utils import timezone

from apps.conference import schemas
from apps.conference.services import access, history_service
from apps.core.services import ServiceDisabled
from htqweb.fallback import fallback


def _today_range():
    today = timezone.localdate()
    return today, today


def _calendar_events(request) -> list[dict]:
    token = getattr(request, "token", None)
    if token is None:
        return []

    from apps.tasks.interface import list_user_conference_events

    date_from, date_to = _today_range()
    return list_user_conference_events(
        token.user_id, date_from=date_from, date_to=date_to,
        include_all=bool(token.is_elevated))


def build(request) -> schemas.OverviewResponse:
    visible = (access.visible_sessions(request)
               .annotate(participant_count=Count("participants", distinct=True)))

    active_rows = list(visible.filter(ended_at__isnull=True).order_by("-started_at"))
    active = [history_service.to_list_item(row) for row in active_rows]

    try:
        events = _calendar_events(request)
    except ServiceDisabled as exc:
        # Предусмотренная деградация: сосед выключен в реестре. Блок
        # «Сегодня» пустеет, но «Идут сейчас» человек всё равно видит по
        # факту участия. expected=True — strict режим разработчика её не
        # роняет.
        fallback("conference.overview.calendar_unavailable", None,
                 reason="календарь недоступен — блок «Сегодня» пуст",
                 expected=True, exc=exc)
        events = []
    except Exception as exc:
        # НЕ предусмотренная деградация: сосед включён, но упал по своей
        # причине. Отдельный site — чтобы не смешивать с expected=True в
        # метрике — и expected=False: под pytest (strict) это осознанно
        # бросит FallbackNotAllowed, чтобы настоящая поломка соседа была
        # громкой, а не тихо растворилась в «сегодня встреч нет».
        fallback("conference.overview.calendar_failed", None,
                 reason="сбой при обращении к календарю — не выключенный сосед, а ошибка",
                 expected=False, exc=exc)
        events = []

    # Сессии по событию — одним запросом, а не по одному на строку.
    by_event = {}
    for row in visible.filter(calendar_event_id__isnull=False).order_by("started_at"):
        by_event.setdefault(row.calendar_event_id, row)

    token = getattr(request, "token", None)
    me = getattr(token, "user_id", None)

    today = []
    for event in events:
        session = by_event.get(event["id"])
        if session is None:
            status = "scheduled"
        elif session.ended_at is None:
            status = "live"
        else:
            status = "finished"
        today.append(schemas.TodayItem(
            event_id=event["id"],
            room_id=event["room_id"],
            title=event["title"],
            start_at=event["start_at"],
            end_at=event["end_at"],
            status=status,
            session_id=session.pk if session else None,
            is_organizer=(event["creator_id"] == me),
            participant_count=getattr(session, "participant_count", 0) if session else 0,
        ))

    return schemas.OverviewResponse(server_time=timezone.now(),
                                    today=today, active=active)
