"""Рассылка «встреча началась»: три канала, один раз, мимо того, кто вошёл."""

import datetime as dt
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.conference.services import session_service
from apps.conference.tasks import notify_session_started
from apps.tasks.models import CalendarEvent, CalendarEventParticipant
from apps.users.models import User, UserStatus

ORGANISER = 7
INVITEE = 8


def _event(room_id="room-notify") -> CalendarEvent:
    # Реальные строки пользователей нужны не для FK (event.creator_id и
    # participant.user_id — обычные int, кросс-аппочный FK запрещён), а
    # потому что письмо идёт через apps.users.interface.get_users_brief,
    # которая берёт email из настоящей таблицы User: без строк с этими pk
    # получатель почты был бы неизвестен и письмо тихо не ушло бы.
    User.objects.get_or_create(pk=ORGANISER, defaults={
        "username": "organiser-7", "email": "organiser-7@htq.test",
        "password": "x", "status": UserStatus.ACTIVE})
    User.objects.get_or_create(pk=INVITEE, defaults={
        "username": "invitee-8", "email": "invitee-8@htq.test",
        "password": "x", "status": UserStatus.ACTIVE})

    start = timezone.now()
    event = CalendarEvent.objects.create(
        title="Планёрка", start_at=start, end_at=start + dt.timedelta(hours=1),
        event_type="conference", conference_room_id=room_id,
        creator_id=ORGANISER, is_all_day=False)
    CalendarEventParticipant.objects.create(event=event, user_id=INVITEE)
    return event


@pytest.mark.django_db
def test_all_three_channels_fire():
    _event()
    with patch("apps.conference.tasks.notify_session_started.delay"):
        session = session_service.start_session(room_id="room-notify",
                                                created_by_id=ORGANISER)

    with patch("apps.tasks.interface.push_notification") as bell, \
         patch("apps.messenger.interface.dispatch_notification") as live, \
         patch("apps.conference.tasks.send_mail") as mail:
        notified = notify_session_started(session.pk)

    assert notified == 1
    # Вошедший первым себе уведомления не получает.
    assert bell.call_args.kwargs["recipient_id"] == INVITEE
    assert live.call_args.args[0] == [INVITEE]
    assert live.call_args.args[1]["type"] == "conference_started"
    assert mail.called


@pytest.mark.django_db
def test_broken_mail_does_not_stop_the_others():
    _event()
    with patch("apps.conference.tasks.notify_session_started.delay"):
        session = session_service.start_session(room_id="room-notify",
                                                created_by_id=ORGANISER)

    with patch("apps.tasks.interface.push_notification") as bell, \
         patch("apps.messenger.interface.dispatch_notification") as live, \
         patch("apps.conference.tasks.send_mail", side_effect=OSError("SMTP")):
        notified = notify_session_started(session.pk)

    assert notified == 1
    assert bell.called and live.called


@pytest.mark.django_db
def test_meeting_outside_calendar_notifies_nobody():
    session = session_service.start_session(room_id="ad-hoc")

    with patch("apps.messenger.interface.dispatch_notification") as live:
        assert notify_session_started(session.pk) == 0

    assert not live.called


@pytest.mark.django_db
def test_mail_reports_platform_time_not_utc():
    """Регресс на найденный ревью баг: время в письме было часом UTC под
    хардкоженной подписью «(UTC+5)». Момент — 20:00 UTC, то есть 01:00
    следующего дня по Алматы: если письмо снова начнёт печатать UTC-час,
    "01:00" в теле не появится, а появится "20:00"."""
    _event()
    started = dt.datetime(2026, 8, 25, 20, 0, tzinfo=dt.timezone.utc)
    with patch("apps.conference.tasks.notify_session_started.delay"):
        session = session_service.start_session(room_id="room-notify",
                                                created_by_id=ORGANISER,
                                                started_at=started)

    with patch("apps.tasks.interface.push_notification"), \
         patch("apps.messenger.interface.dispatch_notification"), \
         patch("apps.conference.tasks.send_mail") as mail:
        notify_session_started(session.pk)

    body = mail.call_args.args[1]
    assert "01:00" in body
    assert "(UTC+5)" in body
    assert "20:00" not in body


@pytest.mark.django_db
def test_repeated_start_enqueues_once():
    _event()
    with patch("apps.conference.tasks.notify_session_started.delay") as queued:
        session_service.start_session(room_id="room-notify", created_by_id=ORGANISER)
        session_service.start_session(room_id="room-notify", created_by_id=ORGANISER)

    assert queued.call_count == 1
