"""Contract tests for ``/api/tasks/v1/calendar/*`` and
``/api/tasks/v1/production-calendar/*``.

Mirrors ``services/task/app/api/v1/calendar.py``. Visibility and the
production-calendar counter get the most attention: the first decides who
sees what, the second feeds deadline arithmetic.
"""

import datetime as dt
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone

from apps.tasks.models import (
    CalendarEvent, CalendarEventParticipant, EventException, Notification,
    ProductionDay, Task,
)

from .helpers import BASE, admin_token, auth, patch_json, post_json, token

USER = 7
OTHER = 42
CAL = f"{BASE}/calendar"
PROD = f"{BASE}/production-calendar"


def _mk_event(**over) -> CalendarEvent:
    start = over.pop("start_at", timezone.now() + dt.timedelta(days=1))
    fields = {"title": "Событие", "start_at": start,
              "end_at": start + dt.timedelta(hours=1), "creator_id": USER}
    fields.update(over)
    return CalendarEvent.objects.create(**fields)


# ── visibility ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_calendar_requires_auth():
    assert Client().get(f"{CAL}/").status_code == 401


@pytest.mark.django_db
def test_author_sees_their_own_event():
    event = _mk_event(creator_id=USER)
    resp = Client().get(f"{CAL}/", **auth())
    assert [e["id"] for e in resp.json()] == [event.id]


@pytest.mark.django_db
def test_global_event_is_visible_to_everyone():
    event = _mk_event(creator_id=OTHER, is_global=True)
    assert [e["id"] for e in Client().get(f"{CAL}/", **auth()).json()] == [event.id]


@pytest.mark.django_db
def test_someone_elses_private_event_is_invisible():
    _mk_event(creator_id=OTHER)
    assert Client().get(f"{CAL}/", **auth()).json() == []


@pytest.mark.django_db
def test_invited_participant_sees_the_event():
    event = _mk_event(creator_id=OTHER)
    CalendarEventParticipant.objects.create(event=event, user_id=USER)
    assert [e["id"] for e in Client().get(f"{CAL}/", **auth()).json()] == [event.id]


@pytest.mark.django_db
def test_department_event_is_visible_to_that_department():
    event = _mk_event(creator_id=OTHER, event_type="department",
                      department_id=3)
    with patch("apps.tasks.services.hydration.hr_interface.get_employee_brief",
               return_value={"id": USER, "department_id": 3}):
        resp = Client().get(f"{CAL}/", **auth())
    assert [e["id"] for e in resp.json()] == [event.id]


@pytest.mark.django_db
def test_department_branch_drops_out_when_hr_cannot_answer():
    """hr is a stub, so the department grant is unavailable — the caller must
    see LESS, never more."""
    _mk_event(creator_id=OTHER, event_type="department", department_id=3)
    assert Client().get(f"{CAL}/", **auth()).json() == []


@pytest.mark.django_db
def test_event_reachable_two_ways_is_listed_once():
    event = _mk_event(creator_id=USER, is_global=True)
    CalendarEventParticipant.objects.create(event=event, user_id=USER)
    assert len(Client().get(f"{CAL}/", **auth()).json()) == 1


# ── create / update / delete ────────────────────────────────────────────

def _create_body(**over) -> dict:
    start = timezone.now() + dt.timedelta(days=1)
    body = {"title": "Планёрка", "start_at": start.isoformat(),
            "end_at": (start + dt.timedelta(hours=1)).isoformat()}
    body.update(over)
    return body


@pytest.mark.django_db
def test_create_event_adds_the_author_as_accepted():
    resp = post_json(Client(), f"{CAL}/", _create_body(), **auth())
    assert resp.status_code == 201
    participants = {p["user_id"]: p["rsvp_status"]
                    for p in resp.json()["participants"]}
    assert participants == {USER: "accepted"}


@pytest.mark.django_db
def test_create_event_invites_and_notifies():
    resp = post_json(Client(), f"{CAL}/",
                     _create_body(participant_user_ids=[11, 12]), **auth())
    participants = {p["user_id"]: p["rsvp_status"]
                    for p in resp.json()["participants"]}
    assert participants == {USER: "accepted", 11: "pending", 12: "pending"}

    recipients = set(Notification.objects.values_list("recipient_id", flat=True))
    assert recipients == {11, 12}          # the author is not notified
    note = Notification.objects.first()
    assert note.target_type == "calendar_event"
    assert "пригласил(а) на событие" in note.verb


@pytest.mark.django_db
def test_common_event_type_forces_is_global():
    resp = post_json(Client(), f"{CAL}/", _create_body(event_type="common"),
                     **auth())
    assert resp.json()["is_global"] is True


@pytest.mark.django_db
def test_end_before_start_is_rejected():
    start = timezone.now() + dt.timedelta(days=1)
    resp = post_json(Client(), f"{CAL}/", {
        "title": "X", "start_at": start.isoformat(),
        "end_at": (start - dt.timedelta(hours=1)).isoformat()}, **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_update_event_requires_author_or_admin():
    event = _mk_event(creator_id=OTHER, is_global=True)
    assert patch_json(Client(), f"{CAL}/{event.id}/", {"title": "hijack"},
                      **auth()).status_code == 403
    # an admin may edit anyone's event
    assert patch_json(Client(), f"{CAL}/{event.id}/", {"title": "ok"},
                      **auth(admin_token())).status_code == 200


@pytest.mark.django_db
def test_switching_event_type_away_from_common_clears_is_global():
    event = _mk_event(event_type="common", is_global=True)
    resp = patch_json(Client(), f"{CAL}/{event.id}/",
                      {"event_type": "personal"}, **auth())
    assert resp.json()["is_global"] is False


@pytest.mark.django_db
def test_updating_participants_notifies_only_the_newly_invited():
    event = _mk_event()
    CalendarEventParticipant.objects.create(event=event, user_id=11,
                                            rsvp_status="accepted")
    resp = patch_json(Client(), f"{CAL}/{event.id}/",
                      {"participant_user_ids": [11, 12]}, **auth())
    assert resp.status_code == 200
    assert set(Notification.objects.values_list("recipient_id",
                                                flat=True)) == {12}
    # an existing invitee keeps the answer they already gave
    statuses = {p["user_id"]: p["rsvp_status"]
                for p in resp.json()["participants"]}
    assert statuses[11] == "accepted"


@pytest.mark.django_db
def test_omitting_participants_leaves_them_alone():
    """``None`` means "do not touch"; an empty list is what clears them."""
    event = _mk_event()
    CalendarEventParticipant.objects.create(event=event, user_id=11)
    patch_json(Client(), f"{CAL}/{event.id}/", {"title": "New"}, **auth())
    assert event.participants.count() == 1


@pytest.mark.django_db
def test_delete_event_requires_author_or_admin():
    event = _mk_event(creator_id=OTHER, is_global=True)
    assert Client().delete(f"{CAL}/{event.id}/", **auth()).status_code == 403
    assert Client().delete(f"{CAL}/{event.id}/",
                           **auth(admin_token())).status_code == 204
    assert not CalendarEvent.objects.filter(pk=event.id).exists()


@pytest.mark.django_db
def test_missing_event_is_404():
    assert patch_json(Client(), f"{CAL}/999/", {"title": "x"},
                      **auth()).status_code == 404
    assert Client().delete(f"{CAL}/999/", **auth()).status_code == 404


# ── rsvp ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_rsvp_updates_the_callers_row():
    event = _mk_event(creator_id=OTHER, is_global=True)
    CalendarEventParticipant.objects.create(event=event, user_id=USER)
    resp = post_json(Client(), f"{CAL}/{event.id}/rsvp/",
                     {"status": "declined"}, **auth())
    assert resp.status_code == 200
    statuses = {p["user_id"]: p["rsvp_status"]
                for p in resp.json()["participants"]}
    assert statuses[USER] == "declined"


@pytest.mark.django_db
def test_rsvp_without_an_invite_is_403():
    event = _mk_event(creator_id=OTHER, is_global=True)
    assert post_json(Client(), f"{CAL}/{event.id}/rsvp/",
                     {"status": "accepted"}, **auth()).status_code == 403


@pytest.mark.django_db
def test_rsvp_rejects_an_unknown_status():
    event = _mk_event()
    assert post_json(Client(), f"{CAL}/{event.id}/rsvp/",
                     {"status": "maybe"}, **auth()).status_code == 422


# ── exceptions ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_and_delete_event_exception():
    event = _mk_event()
    resp = post_json(Client(), f"{CAL}/{event.id}/exceptions/",
                     {"exception_date": "2026-04-01"}, **auth())
    assert resp.status_code == 201
    assert resp.json()["is_cancelled"] is True
    exc_id = resp.json()["id"]

    assert Client().delete(f"{CAL}/exceptions/{exc_id}/",
                           **auth()).status_code == 204
    assert not EventException.objects.filter(pk=exc_id).exists()


@pytest.mark.django_db
def test_exception_on_a_missing_event_is_404():
    assert post_json(Client(), f"{CAL}/999/exceptions/",
                     {"exception_date": "2026-04-01"},
                     **auth()).status_code == 404


@pytest.mark.django_db
def test_exceptions_appear_on_the_event_payload():
    event = _mk_event()
    EventException.objects.create(event=event,
                                  exception_date=dt.date(2026, 4, 1))
    body = Client().get(f"{CAL}/", **auth()).json()[0]
    assert body["exceptions"][0]["exception_date"] == "2026-04-01"


# ── timeline ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_timeline_returns_tasks_and_events():
    Task.objects.create(key="TASK-1", summary="В работе",
                        start_date=dt.date(2026, 4, 2),
                        due_date=dt.date(2026, 4, 5))
    start = dt.datetime(2026, 4, 3, 10, tzinfo=dt.timezone.utc)
    _mk_event(start_at=start)
    resp = Client().get(f"{CAL}/timeline/?start=2026-04-01&end=2026-04-30",
                        **auth())
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tasks"]) == 1
    assert len(body["events"]) == 1
    # legacy display keys the existing widget reads
    assert body["events"][0]["creator"] == USER
    assert body["events"][0]["rrule"] is None
    assert body["tasks"][0]["task_type"] == "task"


@pytest.mark.django_db
def test_timeline_excludes_tasks_outside_the_window():
    Task.objects.create(key="TASK-1", summary="Далеко",
                        start_date=dt.date(2026, 1, 2),
                        due_date=dt.date(2026, 1, 5))
    body = Client().get(f"{CAL}/timeline/?start=2026-04-01&end=2026-04-30",
                        **auth()).json()
    assert body["tasks"] == []


@pytest.mark.django_db
def test_timeline_rejects_an_inverted_or_huge_range():
    assert Client().get(f"{CAL}/timeline/?start=2026-05-01&end=2026-04-01",
                        **auth()).status_code == 400
    assert Client().get(f"{CAL}/timeline/?start=2020-01-01&end=2026-04-01",
                        **auth()).status_code == 400


# ── users-options (documented gap) ──────────────────────────────────────

@pytest.mark.django_db
def test_participant_picker_reports_the_missing_interface_contract():
    """Marker test for the §7 gap: the route answers 501 with a message
    naming what is required, rather than an empty list that would be
    mistaken for "no colleagues found". Replace this test when
    ``apps.users.interface.search_user_options`` is agreed and implemented."""
    resp = Client().get(f"{CAL}/users-options/?query=ив", **auth())
    assert resp.status_code == 501
    assert "search_user_options" in resp.json()["detail"]


# ── production calendar ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_production_calendar_generates_the_kz_baseline():
    resp = Client().get(f"{PROD}/?date__gte=2026-01-01&date__lte=2026-01-08",
                        **auth())
    assert resp.status_code == 200
    by_date = {row["date"]: row for row in resp.json()}
    assert by_date["2026-01-01"]["day_type"] == "holiday"
    assert by_date["2026-01-01"]["note"] == "Новый год"
    assert by_date["2026-01-07"]["day_type"] == "holiday"
    # 3 Jan 2026 is a Saturday
    assert by_date["2026-01-03"]["day_type"] == "weekend"
    assert by_date["2026-01-05"]["day_type"] == "working"


@pytest.mark.django_db
def test_working_day_counter_only_advances_on_working_days():
    resp = Client().get(f"{PROD}/?date__gte=2026-01-01&date__lte=2026-01-09",
                        **auth())
    counters = {row["date"]: row["working_days_since_epoch"]
                for row in resp.json()}
    # 1, 2 holiday; 3, 4 weekend; 5 is the first working day of 2026
    assert counters["2026-01-02"] == 0
    assert counters["2026-01-05"] == 1
    assert counters["2026-01-06"] == 2


@pytest.mark.django_db
def test_production_day_override_is_stored_and_recounted():
    resp = patch_json(Client(), f"{PROD}/2026-01-05/",
                      {"day_type": "holiday", "note": "Локальный выходной"},
                      **auth())
    assert resp.status_code == 200
    assert resp.json()["day_type"] == "holiday"
    assert ProductionDay.objects.filter(date=dt.date(2026, 1, 5)).exists()

    # The whole year's stored counters are re-stamped, because the deadline
    # arithmetic reads them.
    listing = Client().get(f"{PROD}/?date__gte=2026-01-01&date__lte=2026-01-09",
                           **auth()).json()
    counters = {row["date"]: row["working_days_since_epoch"]
                for row in listing}
    assert counters["2026-01-05"] == 0    # no longer a working day
    assert counters["2026-01-06"] == 1


@pytest.mark.django_db
def test_override_restores_the_holiday_note_when_none_is_given():
    resp = patch_json(Client(), f"{PROD}/2026-01-01/",
                      {"day_type": "working"}, **auth())
    assert resp.json()["note"] == "Новый год"


@pytest.mark.django_db
def test_production_calendar_rejects_a_bad_range_and_date():
    assert Client().get(f"{PROD}/?date__gte=2026-05-01&date__lte=2026-04-01",
                        **auth()).status_code == 400
    assert patch_json(Client(), f"{PROD}/not-a-date/", {"day_type": "working"},
                      **auth()).status_code == 422


@pytest.mark.django_db
def test_stored_override_survives_a_second_edit():
    client = Client()
    patch_json(client, f"{PROD}/2026-01-05/", {"day_type": "holiday"}, **auth())
    resp = patch_json(client, f"{PROD}/2026-01-05/", {"day_type": "short"},
                      **auth())
    assert resp.json()["day_type"] == "short"
    assert ProductionDay.objects.filter(date=dt.date(2026, 1, 5)).count() == 1
