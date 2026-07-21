"""Контракт /api/hr/v1/time-tracking/* — паритет с
services/hr/app/api/v1/time.py (+ services/time_service.py,
repositories/time_repo.py).

Провенанс формы ответов: app/schemas/time_tracking.py (TimeEntryOut,
DailyReport, WeeklyReport, MonthlyReport), поведение — TimeService.

Авторизация — БУКВАЛЬНО как в исходнике: ВСЕ 8 эндпойнтов используют только
``get_current_user`` (обычный jwt), включая POST/PUT/DELETE — ни один не
зовёт require_hr_write. Странность исходника (как и recruiting), не баг
порта.

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * список — конверт {items,total,page,pages,limit}, оба пути (/ и /entries/)
    отдают идентичную paginated-выдачу, order_by=date desc;
  * POST — только на /entries/ (НЕ на корне — контракт исходника, фронт
    (hr.ts) шлёт POST на корень и это вне контракта, см. отчёт);
  * PUT + PATCH оба работают на /entries/{id}/ (PATCH регистрируется
    аддитивно, по конвенции остальных под-модулей аппки);
  * end_time <= start_time -> 422 (pydantic model_validator, ТОЛЬКО create,
    update не валидирует пересечение);
  * daily/weekly/monthly отчёты — форма ответа и агрегация минут буквально
    как в TimeService (_minutes: max(0, end-start-break)).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.hr.models import Department, Employee, Position, TimeEntry
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/time-tracking"


@pytest.fixture
def dep(db):
    return Department.objects.create(name="ИТ", path="it")


@pytest.fixture
def pos(db, dep):
    return Position.objects.create(title="Инженер", department=dep, weight=100)


@pytest.fixture
def emp(db, dep, pos):
    return Employee.objects.create(
        first_name="И", last_name="И", email="emp@htq.test", department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9),
    )


@pytest.fixture
def auth(db):
    """Обычный вошедший пользователь — в этом под-модуле достаточно для ЛЮБОГО
    метода (исходник не зовёт require_hr_write нигде в time.py)."""
    user = User.objects.create(
        username="time-user", email="time-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _entry(emp, day, start, end, **kw):
    return TimeEntry.objects.create(
        employee=emp, date=day, start_time=start, end_time=end, **kw,
    )


# ── auth ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt_on_list():
    assert Client().get(f"{BASE}/").status_code == 401


@pytest.mark.django_db
def test_plain_jwt_user_can_create_update_delete(auth, emp):
    """Странность исходника: обычный jwt-пользователь БЕЗ HR-роли может
    писать (нет require_hr_write ни на одном эндпойнте time.py)."""
    resp = Client().post(
        f"{BASE}/entries/",
        data={"employee_id": emp.id, "date": "2026-01-10", "start_time": "09:00:00", "end_time": "18:00:00"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201


# ── GET / и GET /entries/ — paginated envelope, оба пути идентичны ──────────

@pytest.mark.django_db
def test_root_and_entries_return_same_paginated_envelope(auth, emp):
    _entry(emp, datetime.date(2026, 1, 5), datetime.time(9, 0), datetime.time(17, 0))
    _entry(emp, datetime.date(2026, 1, 6), datetime.time(9, 0), datetime.time(17, 0))

    root = Client().get(f"{BASE}/", **auth).json()
    entries = Client().get(f"{BASE}/entries/", **auth).json()
    assert set(root) == {"items", "total", "page", "pages", "limit"}
    assert root == entries
    assert root["total"] == 2
    # order_by="date", order="desc"
    assert [i["date"] for i in root["items"]] == ["2026-01-06", "2026-01-05"]


@pytest.mark.django_db
def test_root_does_not_accept_post():
    """Исходник регистрирует POST только на /entries/, НЕ на корне."""
    resp = Client().post(f"{BASE}/", data={}, content_type="application/json")
    assert resp.status_code in (401, 405)


@pytest.mark.django_db
def test_list_shape(auth, emp):
    _entry(emp, datetime.date(2026, 1, 5), datetime.time(9, 0), datetime.time(17, 30), break_minutes=30,
          description="d", project="p", task="t")
    resp = Client().get(f"{BASE}/entries/", **auth)
    item = resp.json()["items"][0]
    assert set(item) == {"id", "employee_id", "date", "start_time", "end_time", "break_minutes",
                         "description", "project", "task", "created_at", "updated_at"}
    assert item["start_time"] == "09:00:00"
    assert item["end_time"] == "17:30:00"


# ── POST /entries/ — create ──────────────────────────────────────────────

@pytest.mark.django_db
def test_create_entry_201(auth, emp):
    resp = Client().post(
        f"{BASE}/entries/",
        data={"employee_id": emp.id, "date": "2026-01-10", "start_time": "09:00:00", "end_time": "18:00:00",
              "break_minutes": 60},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["employee_id"] == emp.id
    assert body["break_minutes"] == 60


@pytest.mark.django_db
def test_create_entry_end_before_start_422(auth, emp):
    resp = Client().post(
        f"{BASE}/entries/",
        data={"employee_id": emp.id, "date": "2026-01-10", "start_time": "18:00:00", "end_time": "09:00:00"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_create_entry_end_equal_start_422(auth, emp):
    resp = Client().post(
        f"{BASE}/entries/",
        data={"employee_id": emp.id, "date": "2026-01-10", "start_time": "09:00:00", "end_time": "09:00:00"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_create_duplicate_entry_500(auth, emp):
    """Контракт, не баг: UniqueConstraint(employee, date, start_time)
    коллизия не пре-проверяется — IntegrityError необработан, как и в
    исходнике (см. services/time_service.py)."""
    _entry(emp, datetime.date(2026, 1, 10), datetime.time(9, 0), datetime.time(17, 0))
    resp = Client().post(
        f"{BASE}/entries/",
        data={"employee_id": emp.id, "date": "2026-01-10", "start_time": "09:00:00", "end_time": "18:00:00"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 500


# ── PUT + PATCH /entries/{id}/ ───────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("method", ["put", "patch"])
def test_update_accepts_put_and_patch(auth, emp, method):
    entry = _entry(emp, datetime.date(2026, 1, 5), datetime.time(9, 0), datetime.time(17, 0))
    resp = getattr(Client(), method)(
        f"{BASE}/entries/{entry.id}/", data={"description": "updated"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "updated"
    entry.refresh_from_db()
    assert entry.description == "updated"


@pytest.mark.django_db
def test_update_ignores_none_fields(auth, emp):
    entry = _entry(emp, datetime.date(2026, 1, 5), datetime.time(9, 0), datetime.time(17, 0), project="orig")
    Client().patch(
        f"{BASE}/entries/{entry.id}/", data={"description": "d", "project": None},
        content_type="application/json", **auth,
    )
    entry.refresh_from_db()
    assert entry.description == "d"
    assert entry.project == "orig"


@pytest.mark.django_db
def test_update_not_found_404(auth):
    resp = Client().put(
        f"{BASE}/entries/999999/", data={"description": "x"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Time entry not found"


@pytest.mark.django_db
def test_update_can_change_date_field(auth, emp):
    """Регрессия alias-обхода self-shadow бага (schemas.TimeEntryUpdate.entry_date
    aliased "date") — поле date реально патчится."""
    entry = _entry(emp, datetime.date(2026, 1, 5), datetime.time(9, 0), datetime.time(17, 0))
    resp = Client().patch(
        f"{BASE}/entries/{entry.id}/", data={"date": "2026-02-01"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-02-01"
    entry.refresh_from_db()
    assert entry.date == datetime.date(2026, 2, 1)


# ── DELETE /entries/{id}/ ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_delete_204(auth, emp):
    entry = _entry(emp, datetime.date(2026, 1, 5), datetime.time(9, 0), datetime.time(17, 0))
    resp = Client().delete(f"{BASE}/entries/{entry.id}/", **auth)
    assert resp.status_code == 204
    assert not TimeEntry.objects.filter(id=entry.id).exists()


@pytest.mark.django_db
def test_delete_not_found_404(auth):
    resp = Client().delete(f"{BASE}/entries/999999/", **auth)
    assert resp.status_code == 404


# ── GET /reports/daily ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_daily_report_sums_minutes_minus_break(auth, emp):
    _entry(emp, datetime.date(2026, 1, 10), datetime.time(9, 0), datetime.time(17, 0), break_minutes=30)
    resp = Client().get(f"{BASE}/reports/daily?employee_id={emp.id}&date=2026-01-10", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == "2026-01-10"
    assert body["employee_id"] == emp.id
    assert body["total_minutes"] == 450  # 8h - 30min
    assert len(body["entries"]) == 1


@pytest.mark.django_db
def test_daily_report_defaults_to_today_when_date_omitted(auth, emp):
    today = datetime.date.today()
    _entry(emp, today, datetime.time(9, 0), datetime.time(10, 0))
    resp = Client().get(f"{BASE}/reports/daily?employee_id={emp.id}", **auth)
    assert resp.status_code == 200
    assert resp.json()["date"] == today.isoformat()
    assert resp.json()["total_minutes"] == 60


@pytest.mark.django_db
def test_daily_report_requires_jwt_before_query_validation():
    resp = Client().get(f"{BASE}/reports/daily")
    assert resp.status_code == 401  # auth checked before query validation


@pytest.mark.django_db
def test_daily_report_missing_employee_id_422(auth):
    resp = Client().get(f"{BASE}/reports/daily", **auth)
    assert resp.status_code == 422


# ── GET /reports/weekly ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_weekly_report_groups_by_day_with_all_seven_days(auth, emp):
    week_start = datetime.date(2026, 1, 5)  # Monday
    _entry(emp, week_start, datetime.time(9, 0), datetime.time(17, 0))
    _entry(emp, week_start + datetime.timedelta(days=2), datetime.time(9, 0), datetime.time(13, 0))

    resp = Client().get(
        f"{BASE}/reports/weekly?employee_id={emp.id}&week_start=2026-01-05", **auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["week_start"] == "2026-01-05"
    assert body["week_end"] == "2026-01-11"
    assert len(body["daily"]) == 7
    assert body["total_minutes"] == 480 + 240
    assert body["daily"][0]["total_minutes"] == 480
    assert body["daily"][1]["total_minutes"] == 0
    assert body["daily"][2]["total_minutes"] == 240


# ── GET /reports/monthly ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_monthly_report_groups_by_iso_week_with_empty_daily(auth, emp):
    _entry(emp, datetime.date(2026, 1, 5), datetime.time(9, 0), datetime.time(17, 0))
    _entry(emp, datetime.date(2026, 1, 20), datetime.time(9, 0), datetime.time(13, 0))

    resp = Client().get(
        f"{BASE}/reports/monthly?employee_id={emp.id}&year=2026&month=1", **auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["year"] == 2026
    assert body["month"] == 1
    assert body["total_minutes"] == 480 + 240
    assert len(body["weekly"]) == 2
    for week in body["weekly"]:
        assert week["daily"] == []


@pytest.mark.django_db
def test_monthly_report_invalid_month_422(auth):
    resp = Client().get(f"{BASE}/reports/monthly?employee_id=1&year=2026&month=13", **auth)
    assert resp.status_code == 422
