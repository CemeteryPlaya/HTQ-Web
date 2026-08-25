"""Сводный экран: что сегодня и что идёт прямо сейчас."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.conference.models import ConferenceSession
from apps.tasks.models import CalendarEvent, CalendarEventParticipant

from .conftest import BASE, auth_header


def _event(room_id: str, *, creator_id: int, invitees=()) -> CalendarEvent:
    start = timezone.now()
    event = CalendarEvent.objects.create(
        title="Планёрка", start_at=start, end_at=start + timedelta(hours=1),
        event_type="conference", conference_room_id=room_id,
        creator_id=creator_id, is_all_day=False)
    for user_id in invitees:
        CalendarEventParticipant.objects.create(event=event, user_id=user_id)
    return event


def _session(room_id: str, *, event_id=None, ended=False) -> ConferenceSession:
    start = timezone.now()
    return ConferenceSession.objects.create(
        room_id=room_id, title="Планёрка", created_by_id=1,
        created_by_name="кто-то", started_at=start,
        ended_at=start + timedelta(minutes=10) if ended else None,
        duration_sec=600 if ended else None,
        expires_at=start + timedelta(days=25), calendar_event_id=event_id)


@pytest.mark.django_db
def test_scheduled_event_without_session(client, organiser):
    _event("room-1", creator_id=organiser.pk)

    body = client.get(f"{BASE}/overview", **auth_header(organiser)).json()

    assert [row["status"] for row in body["today"]] == ["scheduled"]
    assert body["today"][0]["session_id"] is None
    assert body["active"] == []


@pytest.mark.django_db
def test_live_event_appears_in_both_blocks(client, organiser):
    event = _event("room-2", creator_id=organiser.pk)
    session = _session("room-2", event_id=event.pk)

    body = client.get(f"{BASE}/overview", **auth_header(organiser)).json()

    assert body["today"][0]["status"] == "live"
    assert body["today"][0]["session_id"] == session.pk
    assert [row["id"] for row in body["active"]] == [session.pk]


@pytest.mark.django_db
def test_finished_event_is_not_active(client, organiser):
    event = _event("room-3", creator_id=organiser.pk)
    _session("room-3", event_id=event.pk, ended=True)

    body = client.get(f"{BASE}/overview", **auth_header(organiser)).json()

    assert body["today"][0]["status"] == "finished"
    assert body["active"] == []


@pytest.mark.django_db
def test_ad_hoc_meeting_is_active_but_not_in_today(client, organiser):
    session = _session("ad-hoc")
    session.created_by_id = organiser.pk
    session.save(update_fields=["created_by_id"])

    body = client.get(f"{BASE}/overview", **auth_header(organiser)).json()

    assert body["today"] == []
    assert [row["id"] for row in body["active"]] == [session.pk]


@pytest.mark.django_db
def test_outsider_sees_nothing(client, organiser, outsider):
    event = _event("room-4", creator_id=organiser.pk)
    _session("room-4", event_id=event.pk)

    body = client.get(f"{BASE}/overview", **auth_header(outsider)).json()

    assert body["today"] == []
    assert body["active"] == []


@pytest.mark.django_db
def test_admin_sees_every_meeting(client, organiser, admin_user):
    event = _event("room-5", creator_id=organiser.pk)
    _session("room-5", event_id=event.pk)

    body = client.get(f"{BASE}/overview", **auth_header(admin_user)).json()

    assert len(body["today"]) == 1
    assert len(body["active"]) == 1


@pytest.mark.django_db
def test_room_reopened_after_finish_shows_the_live_session(client, organiser):
    """Комнату закрыли и открыли повторно — у события две сессии.

    session_service.start_session переиспользует открытую сессию только
    пока она не завершена, поэтому одно и то же calendar_event_id может
    встретиться у двух строк ConferenceSession за день. Блок «Сегодня»
    обязан показать статус по ИДУЩЕЙ сессии, а не по первой попавшейся —
    иначе человек увидит «Завершена» на встрече, которая идёт прямо сейчас.
    """
    event = _event("room-6", creator_id=organiser.pk)
    _session("room-6", event_id=event.pk, ended=True)
    live = _session("room-6", event_id=event.pk)

    body = client.get(f"{BASE}/overview", **auth_header(organiser)).json()

    assert body["today"][0]["status"] == "live"
    assert body["today"][0]["session_id"] == live.pk
