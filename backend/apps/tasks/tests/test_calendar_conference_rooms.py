"""Комната видеоконференции принадлежит ровно одному событию календаря.

Правило заказчика «1 событие — 1 комната» держится уникальным индексом, а не
соглашением: по комнате однозначно определяется, кого на встречу звали.
"""

import datetime as dt

import pytest
from django.db.utils import IntegrityError
from django.test import Client
from django.utils import timezone

from apps.tasks.models import CalendarEvent
from apps.tasks.services import calendar_service

from .helpers import BASE, auth, post_json

USER = 7
CAL = f"{BASE}/calendar"


def _payload(**over) -> dict:
    start = timezone.now() + dt.timedelta(hours=1)
    body = {
        "title": "Планёрка",
        "start_at": start.isoformat(),
        "end_at": (start + dt.timedelta(hours=1)).isoformat(),
        "event_type": "conference",
        "is_all_day": False,
    }
    body.update(over)
    return body


@pytest.mark.django_db
def test_conference_event_gets_room_id_when_client_sends_none():
    response = post_json(Client(), f"{CAL}/", _payload(), **auth())

    assert response.status_code == 201
    room_id = response.json()["conference_room_id"]
    assert room_id, "конференции без комнаты не бывает"


@pytest.mark.django_db
def test_taken_room_id_is_refused():
    first = post_json(Client(), f"{CAL}/", _payload(), **auth())
    taken = first.json()["conference_room_id"]

    second = post_json(Client(), f"{CAL}/",
                       _payload(conference_room_id=taken), **auth())

    assert second.status_code == 409


@pytest.mark.django_db
def test_database_refuses_duplicate_room():
    start = timezone.now()
    fields = {"title": "x", "start_at": start, "end_at": start,
              "event_type": "conference", "conference_room_id": "dup-1"}
    CalendarEvent.objects.create(creator_id=USER, **fields)

    with pytest.raises(IntegrityError):
        CalendarEvent.objects.create(creator_id=USER, **fields)


@pytest.mark.django_db
def test_non_conference_events_may_all_have_empty_room():
    start = timezone.now()
    for _ in range(2):
        CalendarEvent.objects.create(title="x", start_at=start, end_at=start,
                                     event_type="personal", creator_id=USER)

    assert CalendarEvent.objects.filter(event_type="personal").count() == 2


@pytest.mark.django_db
def test_allocate_returns_free_id():
    first = calendar_service.allocate_conference_room_id()
    CalendarEvent.objects.create(title="x", start_at=timezone.now(),
                                 end_at=timezone.now(), event_type="conference",
                                 conference_room_id=first, creator_id=USER)

    assert calendar_service.allocate_conference_room_id() != first
