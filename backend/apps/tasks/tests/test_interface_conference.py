"""Контракт `apps.tasks.interface` для аппки conference.

Соседу нужны ровно два ответа: «какое событие обслуживает эту комнату» и
«какие конференции у человека в периоде». Модели наружу не отдаются.
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


def _day_window(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """Границы суток ``day`` как МОМЕНТЫ (UTC) — то, что теперь принимает
    ``list_user_conference_events``. Тестам самой ``tasks`` не нужен пояс
    платформы (это знание закрыто в ``apps.conference.services.
    platform_time`` соседней аппки) — интерфейс timezone-агностичен, ему
    достаточно любых aware-границ, а UTC здесь ничем не хуже.
    """
    start = dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc)
    return start, start + dt.timedelta(days=1)


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
    period_start, period_end = _day_window(today)
    _event("room-own", invitees=[])
    _event("room-invited", invitees=[INVITEE], creator=OUTSIDER)

    mine = interface.list_user_conference_events(
        INVITEE, period_start=period_start, period_end=period_end)

    assert [row["room_id"] for row in mine] == ["room-invited"]


@pytest.mark.django_db
def test_admin_sees_every_conference_of_the_day():
    today = timezone.localdate()
    period_start, period_end = _day_window(today)
    _event("room-a")
    _event("room-b", creator=OUTSIDER)

    everything = interface.list_user_conference_events(
        None, period_start=period_start, period_end=period_end, include_all=True)

    assert len(everything) == 2


@pytest.mark.django_db
def test_cancelled_occurrence_is_hidden():
    today = timezone.localdate()
    period_start, period_end = _day_window(today)
    event = _event("room-cancelled", invitees=[INVITEE])
    EventException.objects.create(event=event, exception_date=today,
                                  is_cancelled=True)

    assert interface.list_user_conference_events(
        INVITEE, period_start=period_start, period_end=period_end) == []


@pytest.mark.django_db
def test_events_of_other_days_are_out_of_range():
    today = timezone.localdate()
    tomorrow = today + dt.timedelta(days=1)
    _event("room-tomorrow", start=timezone.now() + dt.timedelta(days=1),
           invitees=[INVITEE])

    today_start, today_end = _day_window(today)
    tomorrow_start, tomorrow_end = _day_window(tomorrow)

    assert interface.list_user_conference_events(
        INVITEE, period_start=today_start, period_end=today_end) == []
    assert len(interface.list_user_conference_events(
        INVITEE, period_start=tomorrow_start, period_end=tomorrow_end)) == 1


@pytest.mark.django_db
def test_event_crossing_the_window_boundary_is_included():
    """Регресс на найденный ревью баг: старый фильтр брал ``__date`` полей
    события — а Django вычисляет ``__date`` в АКТИВНОМ поясе, которого в
    проекте нет (``timezone.activate()`` нигде не вызывается), то есть
    фактически в UTC. Если бы фильтр по-прежнему сравнивал даты, а не
    моменты, событие, чей конец лежит РОВНО на границе окна (``end_at ==
    period_end``), либо событие, чьё начало лежит РОВНО на левой границе,
    вело бы себя по-другому в зависимости от того, где эта дата на самом
    деле физически проходит. Момент фиксирован — тест не должен зависеть от
    времени запуска.
    """
    period_start = dt.datetime(2026, 8, 26, 0, 0, tzinfo=dt.timezone.utc)
    period_end = period_start + dt.timedelta(days=1)

    # Начинается ровно в начале окна — должно попасть (intersection, не
    # строгое "после").
    _event("room-left-edge", start=period_start, invitees=[INVITEE])
    # Начинается за минуту до конца окна — должно попасть.
    _event("room-right-edge", start=period_end - dt.timedelta(minutes=1),
           invitees=[INVITEE])
    # Начинается ровно в момент, когда окно уже закрылось — НЕ должно
    # попасть (конец периода — эксклюзивная граница).
    _event("room-after", start=period_end, invitees=[INVITEE])

    rows = interface.list_user_conference_events(
        INVITEE, period_start=period_start, period_end=period_end)

    assert sorted(row["room_id"] for row in rows) == [
        "room-left-edge", "room-right-edge"]
