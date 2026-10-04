"""Временный исполнитель должности на период (мастер-план БЗО, B1.1, D-22).

Проверяется то, что потребитель — движок согласования — увидит через
``hr.interface``: исполнитель попадает в разрешение должности только в свой
период (границы включительно), только с действующей учётной записью; и HTTP
заведения назначений — права, отказы с понятным текстом.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.hr import interface
from apps.hr.models import ActingAssignment, Department, Employee, EmployeeStatus, Position
from apps.hr.services import acting_service as svc
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1"
DAY = dt.date(2026, 10, 1)


@pytest.fixture
def org(db):
    dep = Department.objects.create(name="Руководство", path="acting")
    return {
        "dep": dep,
        "cfo": Position.objects.create(title="Финансовый директор", department=dep, weight=210),
        "deputy": Position.objects.create(title="Зам. финансового директора", department=dep,
                                          weight=220),
    }


def _person(org, username: str, *, position=None, active_account=True,
            status=EmployeeStatus.ACTIVE) -> Employee:
    user = User.objects.create(
        username=username, email=f"{username}@htq.test", password="x",
        status=UserStatus.ACTIVE if active_account else UserStatus.SUSPENDED)
    return Employee.objects.create(
        user_id=user.pk, first_name=username.capitalize(), last_name="Тестов",
        email=f"emp-{username}@htq.test", department=org["dep"],
        position=position or org["deputy"], hire_date="2024-01-01", status=status)


def _acting(org, employee, *, date_from=DAY, date_to=DAY + dt.timedelta(days=13)):
    return ActingAssignment.objects.create(
        position=org["cfo"], employee=employee, date_from=date_from, date_to=date_to,
        basis="Приказ № 12")


# ── разрешение должности ────────────────────────────────────────────────

def test_acting_holder_joins_the_position_only_within_the_period(org):
    holder = _person(org, "holder", position=org["cfo"])
    acting = _person(org, "acting")
    _acting(org, acting)

    first, last = DAY, DAY + dt.timedelta(days=13)
    for day in (first, last):  # границы включительно
        assert interface.resolve_position_users([org["cfo"].pk], on_date=day) == {
            org["cfo"].pk: [holder.user_id, acting.user_id]}
    for day in (first - dt.timedelta(days=1), last + dt.timedelta(days=1)):
        assert interface.resolve_position_users([org["cfo"].pk], on_date=day) == {
            org["cfo"].pk: [holder.user_id]}


def test_vacant_position_is_covered_by_the_acting_holder(org):
    acting = _person(org, "acting")
    _acting(org, acting)

    assert interface.resolve_position_users([org["cfo"].pk], on_date=DAY) == {
        org["cfo"].pk: [acting.user_id]}
    assert interface.acting_holders(org["cfo"].pk, DAY) == [acting.user_id]
    assert interface.acting_holders(org["cfo"].pk, DAY - dt.timedelta(days=1)) == []


def test_inactive_account_does_not_act(org):
    acting = _person(org, "sleepy", active_account=False)
    _acting(org, acting)

    assert interface.resolve_position_users([org["cfo"].pk], on_date=DAY) == {
        org["cfo"].pk: []}
    assert interface.acting_holders(org["cfo"].pk, DAY) == []


def test_holder_who_also_acts_is_listed_once(org):
    holder = _person(org, "holder", position=org["cfo"])
    _acting(org, holder)

    assert interface.resolve_position_users([org["cfo"].pk], on_date=DAY) == {
        org["cfo"].pk: [holder.user_id]}


def test_default_date_is_today(org, monkeypatch):
    from django.utils import timezone

    acting = _person(org, "acting")
    _acting(org, acting)
    monkeypatch.setattr(timezone, "localdate", lambda *a, **k: DAY)

    assert interface.resolve_position_users([org["cfo"].pk]) == {
        org["cfo"].pk: [acting.user_id]}


# ── правила сервиса ─────────────────────────────────────────────────────

def test_service_refuses_what_could_never_sign(org):
    fired = _person(org, "fired", status=EmployeeStatus.TERMINATED)
    no_account = Employee.objects.create(
        first_name="Без", last_name="Учётки", email="none@htq.test", department=org["dep"],
        position=org["deputy"], hire_date="2024-01-01", status=EmployeeStatus.ACTIVE)
    base = dict(position_id=org["cfo"].pk, date_from=DAY, date_to=DAY, basis="Приказ",
                assigned_by_id=None)

    with pytest.raises(svc.ActingInvalid, match="не работает"):
        svc.create(employee_id=fired.pk, **base)
    with pytest.raises(svc.ActingInvalid, match="нет учётной записи"):
        svc.create(employee_id=no_account.pk, **base)
    with pytest.raises(svc.ActingInvalid, match="раньше даты начала"):
        svc.create(employee_id=_person(org, "ok").pk,
                   **{**base, "date_to": DAY - dt.timedelta(days=1)})
    org["cfo"].is_active = False
    org["cfo"].save(update_fields=["is_active"])
    with pytest.raises(svc.ActingInvalid, match="неактивна"):
        svc.create(employee_id=_person(org, "ok2").pk, **base)


def test_partial_update_rechecks_the_period(org):
    row = svc.create(position_id=org["cfo"].pk, employee_id=_person(org, "a").pk,
                     date_from=DAY, date_to=DAY + dt.timedelta(days=5), basis="Приказ",
                     assigned_by_id=7)

    with pytest.raises(svc.ActingInvalid):
        svc.update(row.pk, date_from=DAY + dt.timedelta(days=10))
    updated = svc.update(row.pk, date_to=DAY + dt.timedelta(days=20), basis="Приказ № 2")
    assert (updated.date_to, updated.basis) == (DAY + dt.timedelta(days=20), "Приказ № 2")


# ── HTTP ────────────────────────────────────────────────────────────────

def _token(company_row, username: str, level: str | None) -> dict:
    from apps.access.tests.helpers import assign

    user = User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=UserStatus.ACTIVE)
    if level:
        assign(company_row, user.pk, "hr", level)
    token = issue_token_pair(user, company_slug=company_row)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_HTQ_COMPANY": company_row}


def test_http_lifecycle_and_rights(org, company_row):
    admin = _token(company_row, "hr-admin", "full")
    reader = _token(company_row, "hr-reader", "read")
    acting = _person(org, "acting")
    body = {"position_id": org["cfo"].pk, "employee_id": acting.pk,
            "date_from": "2026-10-01", "date_to": "2026-10-14", "basis": "Приказ № 12"}
    client = Client()

    denied = client.post(f"{BASE}/acting-assignments", data=body,
                         content_type="application/json", **reader)
    assert denied.status_code == 403
    created = client.post(f"{BASE}/acting-assignments/", data=body,
                          content_type="application/json", **admin)
    assert created.status_code == 201, created.content
    row = created.json()
    assert row["position_title"] == "Финансовый директор"
    assert row["employee_name"] == "Тестов Acting"
    assert row["user_id"] == acting.user_id and row["assigned_by_id"] is not None

    listed = client.get(f"{BASE}/acting-assignments",
                        {"position_id": org["cfo"].pk, "active_on": "2026-10-14"}, **reader)
    assert [item["id"] for item in listed.json()] == [row["id"]]
    outside = client.get(f"{BASE}/acting-assignments", {"active_on": "2026-10-15"}, **reader)
    assert outside.json() == []
    bad = client.get(f"{BASE}/acting-assignments", {"active_on": "15.10.2026"}, **reader)
    assert bad.status_code == 422

    patched = client.patch(f"{BASE}/acting-assignments/{row['id']}",
                           data={"date_to": "2026-10-20"},
                           content_type="application/json", **admin)
    assert patched.status_code == 200 and patched.json()["date_to"] == "2026-10-20"
    reversed_ = client.patch(f"{BASE}/acting-assignments/{row['id']}",
                             data={"date_from": "2026-11-01"},
                             content_type="application/json", **admin)
    assert reversed_.status_code == 422
    assert client.delete(f"{BASE}/acting-assignments/{row['id']}", **admin).status_code == 204
    assert client.delete(f"{BASE}/acting-assignments/{row['id']}", **admin).status_code == 404


def test_http_explains_why_an_employee_cannot_act(org, company_row):
    admin = _token(company_row, "hr-admin", "full")
    fired = _person(org, "fired", status=EmployeeStatus.TERMINATED)

    resp = Client().post(f"{BASE}/acting-assignments", data={
        "position_id": org["cfo"].pk, "employee_id": fired.pk,
        "date_from": "2026-10-01", "date_to": "2026-10-02", "basis": "Приказ"},
        content_type="application/json", **admin)

    assert resp.status_code == 422
    assert "не работает" in resp.json()["detail"]
