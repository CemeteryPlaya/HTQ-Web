"""Связь сессии с событием календаря устанавливается один раз — при старте."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.conference.services import session_service
from apps.tasks.models import CalendarEvent


def _conference_event(room_id: str, creator_id: int = 7) -> CalendarEvent:
    start = timezone.now()
    return CalendarEvent.objects.create(
        title="Планёрка", start_at=start, end_at=start + dt.timedelta(hours=1),
        event_type="conference", conference_room_id=room_id,
        creator_id=creator_id, is_all_day=False,
    )


@pytest.mark.django_db
def test_session_remembers_its_calendar_event():
    event = _conference_event("room-linked")

    session = session_service.start_session(room_id="room-linked")

    assert session.calendar_event_id == event.pk


@pytest.mark.django_db
def test_session_outside_calendar_has_no_event():
    session = session_service.start_session(room_id="ad-hoc-room")

    assert session.calendar_event_id is None


@pytest.mark.django_db
def test_second_start_reuses_the_open_session():
    _conference_event("room-linked")

    first = session_service.start_session(room_id="room-linked")
    second = session_service.start_session(room_id="room-linked")

    assert first.pk == second.pk
