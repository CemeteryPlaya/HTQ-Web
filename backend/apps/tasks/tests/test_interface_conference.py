"""Контракт `apps.tasks.interface` для аппки conference.

Соседу нужны ровно два ответа: «какое событие обслуживает эту комнату» и
«какие конференции у человека на сегодня». Модели наружу не отдаются.
"""

import datetime as dt

import pytest
from django.utils import timezone

from apps.tasks import interface
from apps.tasks.models import CalendarEvent, CalendarEventParticipant, EventException

ORGANISER = 7
INVITEE = 8
OUTSIDER = 9


def _event(room_id: str, *, start=None, invitees=(), creator=ORGANISER) -> CalendarEvent:
    start = start or timezone.now()
    event = CalendarEvent.objects.create(
        title="Планёрка", start_at=start, end_at=start + dt.timedelta(hours=1),
        event_type="conference", conference_room_id=room_id, creator_id=creator,
        is_all_day=False,
    )
    for user_id in invitees:
        CalendarEventParticipant.objects.create(event=event, user_id=user_id)
    return event


@pytest.mark.django_db
def test_event_for_room_returns_invitees_with_creator():
    _event("room-1", invitees=[INVITEE])

    payload = interface.get_conference_event_for_room("room-1")

    assert payload["room_id"] == "room-1"
    assert sorted(payload["invitee_ids"]) == sorted([ORGANISER, INVITEE])
    assert payload["creator_id"] == ORGANISER


@pytest.mark.django_db
def test_event_for_unknown_room_is_none():
    assert interface.get_conference_event_for_room("nope") is None


@pytest.mark.django_db
def test_user_events_include_invitations_and_own():
    today = timezone.localdate()
    _event("room-own", invitees=[])
    _event("room-invited", invitees=[INVITEE], creator=OUTSIDER)

    mine = interface.list_user_conference_events(
        INVITEE, date_from=today, date_to=today)

    assert [row["room_id"] for row in mine] == ["room-invited"]


@pytest.mark.django_db
def test_admin_sees_every_conference_of_the_day():
    today = timezone.localdate()
    _event("room-a")
    _event("room-b", creator=OUTSIDER)

    everything = interface.list_user_conference_events(
        None, date_from=today, date_to=today, include_all=True)

    assert len(everything) == 2


@pytest.mark.django_db
def test_cancelled_occurrence_is_hidden():
    today = timezone.localdate()
    event = _event("room-cancelled", invitees=[INVITEE])
    EventException.objects.create(event=event, exception_date=today,
                                  is_cancelled=True)

    assert interface.list_user_conference_events(
        INVITEE, date_from=today, date_to=today) == []


@pytest.mark.django_db
def test_events_of_other_days_are_out_of_range():
    tomorrow = timezone.localdate() + dt.timedelta(days=1)
    _event("room-tomorrow", start=timezone.now() + dt.timedelta(days=1),
           invitees=[INVITEE])

    today = timezone.localdate()
    assert interface.list_user_conference_events(
        INVITEE, date_from=today, date_to=today) == []
    assert len(interface.list_user_conference_events(
        INVITEE, date_from=tomorrow, date_to=tomorrow)) == 1
