"""HTTP-контракт очереди заявок и назначения подтверждающего (спека §10).

План: docs/superpowers/plans/2026-08-25-hr-identity-sync.md, задача 8.
"""
from __future__ import annotations

import datetime
import json

import pytest
from django.test import Client

from apps.hr.models import (
    Department, Employee, IdentityApprover, IdentityChangeRequest, Position,
)
from apps.hr.services import identity_request_service as svc
from apps.hr.tests.conftest import auth_headers, make_user

BASE = "/api/hr/v1/identity-requests"
APPROVER = "/api/hr/v1/identity-approver/"


def _hr_auth(title: str, weight: int, email: str):
    """HR-сотрудник нужного уровня: уровень считается из должности."""
    dep = Department.objects.create(name=f"HR-{weight}", path=f"hr{weight}")
    pos = Position.objects.create(title=title, department=dep, weight=weight)
    user = make_user(email)
    Employee.objects.create(
        email=email, department=dep, position=pos, user_id=user.id,
        hire_date=datetime.date(2024, 1, 9), first_name="Х", last_name="Р",
    )
    return user, auth_headers(user)


@pytest.fixture
def senior_auth(db):
    return _hr_auth("Senior HR Manager", 30, "hr-senior-api@htq.test")[1]


@pytest.fixture
def lead_auth(db):
    return _hr_auth("HR Director", 40, "hr-lead-api@htq.test")[1]


@pytest.fixture
def stranger_auth(db):
    user = make_user("stranger@htq.test")
    return auth_headers(user)


@pytest.fixture
def approver_auth(db, account):
    """Назначенный подтверждающий — им же владеет карточка сотрудника."""
    IdentityApprover.objects.create(pk=1, user_id=account.id)
    return auth_headers(account)


@pytest.fixture
def pending_request(db, employee, approver_auth, fallback_log_mode):
    _, request = svc.capture(employee, {"first_name": "Иннокентий"}, actor_id=1)
    return request


# ── доступ ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt():
    assert Client().get(f"{BASE}/").status_code == 401


@pytest.mark.django_db
def test_list_is_visible_to_hr_with_view_permission(senior_auth, pending_request):
    res = Client().get(f"{BASE}/", **senior_auth)

    assert res.status_code == 200
    assert [row["id"] for row in res.json()] == [pending_request.id]


@pytest.mark.django_db
def test_list_for_approver_contains_own_requests(approver_auth, pending_request):
    res = Client().get(f"{BASE}/", **approver_auth)

    assert res.status_code == 200
    assert [row["id"] for row in res.json()] == [pending_request.id]


@pytest.mark.django_db
def test_stranger_sees_empty_queue(stranger_auth, pending_request):
    res = Client().get(f"{BASE}/", **stranger_auth)

    assert res.status_code == 200
    assert res.json() == []


# ── карточка заявки ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_detail_shows_stale_snapshot(approver_auth, pending_request, account):
    # владелец успел измениться, пока заявка ждала
    account.first_name = "Совсем другое"
    account.save()

    res = Client().get(f"{BASE}/{pending_request.id}/", **approver_auth)

    assert res.status_code == 200
    row = next(f for f in res.json()["fields"] if f["field"] == "first_name")
    assert row["is_stale"] is True
    assert row["account_value_now"] == "Совсем другое"


@pytest.mark.django_db
def test_detail_unknown_is_404(approver_auth):
    assert Client().get(f"{BASE}/999999/", **approver_auth).status_code == 404


@pytest.mark.django_db
def test_detail_forbidden_for_stranger(stranger_auth, pending_request):
    res = Client().get(f"{BASE}/{pending_request.id}/", **stranger_auth)
    assert res.status_code == 403


# ── решение ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_decide_requires_approver(stranger_auth, pending_request):
    res = Client().post(
        f"{BASE}/{pending_request.id}/decide",
        data=json.dumps({"decisions": {"first_name": "apply"}}),
        content_type="application/json", **stranger_auth,
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_hr_view_permission_alone_does_not_allow_deciding(senior_auth, pending_request):
    """Вести очередь и решать — разные права (спека §9)."""
    res = Client().post(
        f"{BASE}/{pending_request.id}/decide",
        data=json.dumps({"decisions": {"first_name": "apply"}}),
        content_type="application/json", **senior_auth,
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_decide_applies(approver_auth, pending_request, account):
    res = Client().post(
        f"{BASE}/{pending_request.id}/decide",
        data=json.dumps({"decisions": {"first_name": "apply"}}),
        content_type="application/json", **approver_auth,
    )

    assert res.status_code == 200
    account.refresh_from_db()
    assert account.first_name == "Иннокентий"


@pytest.mark.django_db
def test_incomplete_decision_is_422(approver_auth, employee, fallback_log_mode):
    _, request = svc.capture(
        employee, {"first_name": "И", "phone": "+7 777 000-00-00"}, actor_id=1,
    )
    res = Client().post(
        f"{BASE}/{request.id}/decide",
        data=json.dumps({"decisions": {"first_name": "apply"}}),
        content_type="application/json", **approver_auth,
    )
    assert res.status_code == 422


@pytest.mark.django_db
def test_second_decide_is_409(approver_auth, pending_request):
    body = json.dumps({"decisions": {"first_name": "apply"}})
    Client().post(f"{BASE}/{pending_request.id}/decide", data=body,
                  content_type="application/json", **approver_auth)
    res = Client().post(f"{BASE}/{pending_request.id}/decide", data=body,
                        content_type="application/json", **approver_auth)
    assert res.status_code == 409


# ── подтверждающий ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_approver_change_requires_manage_permission(senior_auth, account):
    res = Client().put(APPROVER, data=json.dumps({"user_id": account.id}),
                       content_type="application/json", **senior_auth)
    assert res.status_code == 403


@pytest.mark.django_db
def test_approver_change_by_lead(lead_auth, account):
    res = Client().put(APPROVER, data=json.dumps({"user_id": account.id}),
                       content_type="application/json", **lead_auth)

    assert res.status_code == 200
    assert IdentityApprover.objects.get(pk=1).user_id == account.id


@pytest.mark.django_db
def test_approver_can_be_cleared(lead_auth, account):
    Client().put(APPROVER, data=json.dumps({"user_id": account.id}),
                 content_type="application/json", **lead_auth)

    res = Client().put(APPROVER, data=json.dumps({"user_id": None}),
                       content_type="application/json", **lead_auth)

    assert res.status_code == 200
    assert IdentityApprover.objects.get(pk=1).user_id is None


@pytest.mark.django_db
def test_approver_must_exist(lead_auth):
    res = Client().put(APPROVER, data=json.dumps({"user_id": 999999}),
                       content_type="application/json", **lead_auth)
    assert res.status_code == 422


@pytest.mark.django_db
def test_approver_get_returns_current(lead_auth, account):
    Client().put(APPROVER, data=json.dumps({"user_id": account.id}),
                 content_type="application/json", **lead_auth)

    res = Client().get(APPROVER, **lead_auth)

    assert res.status_code == 200
    assert res.json()["user_id"] == account.id
    assert res.json()["user"]["email"] == account.email


# ── ответ на правку карточки ────────────────────────────────────────────────

@pytest.mark.django_db
def test_update_response_says_the_change_went_to_approval(
        lead_auth, employee, approver_auth, fallback_log_mode):
    """Правка идентичности обязана быть отличима от обычного сохранения.

    Поля идентичности не пишутся в карточку сразу — они уходят заявкой
    владельцу аккаунта. Строка сотрудника при этом возвращается ПРЕЖНЕЙ, и без
    отдельного признака в ответе клиент не может отличить «сохранено» от
    «отправлено на подтверждение»: форма закрывается, значение не меняется,
    ошибки нет — правка выглядит пропавшей. Ровно так это и выглядело у
    заказчика при первой живой проверке.
    """
    res = Client().put(
        f"/api/hr/v1/employees/{employee.id}/",
        data=json.dumps({"phone": "+7 777 000-11-22"}),
        content_type="application/json", **lead_auth,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["identity_request"]["status"] == IdentityChangeRequest.Status.PENDING
    assert [f["field"] for f in body["identity_request"]["fields"]] == ["phone"]
    # Карточка намеренно не изменилась: значение появится после подтверждения.
    employee.refresh_from_db()
    assert employee.phone != "+7 777 000-11-22"


@pytest.mark.django_db
def test_update_of_non_identity_field_has_no_request_key(
        lead_auth, employee, approver_auth, fallback_log_mode):
    """Трудовые поля применяются сразу — заявке взяться неоткуда."""
    res = Client().put(
        f"/api/hr/v1/employees/{employee.id}/",
        data=json.dumps({"status": "suspended"}),
        content_type="application/json", **lead_auth,
    )

    assert res.status_code == 200
    assert "identity_request" not in res.json()


# ── право менять напрямую (hr.identity.force) ───────────────────────────────

def _force_auth(email: str = "hr-force@htq.test"):
    """HR-должность с явно выданным правом обхода подтверждения."""
    dep = Department.objects.create(name="HR-force", path="hrforce")
    pos = Position.objects.create(
        title="Кадровик с правом обхода", department=dep, weight=35,
        # Полный набор для правки чужой карточки: без view/view.all сотрудник
        # другого отдела просто не находится, и тест падал бы на 404, ничего не
        # сказав о самом праве обхода.
        permissions={"hr_level": "senior",
                     "permissions": ["hr.employees.view", "hr.employees.view.all",
                                     "hr.employees.edit", "hr.identity.force"]},
    )
    user = make_user(email)
    Employee.objects.create(
        email=email, department=dep, position=pos, user_id=user.id,
        hire_date=datetime.date(2024, 1, 9), first_name="Ф", last_name="О",
    )
    return auth_headers(user)


@pytest.mark.django_db
def test_force_permission_writes_identity_straight_to_the_card(
        employee, approver_auth, fallback_log_mode):
    res = Client().put(
        f"/api/hr/v1/employees/{employee.id}/",
        data=json.dumps({"phone": "+7 777 000-11-22"}),
        content_type="application/json", **_force_auth(),
    )

    assert res.status_code == 200
    assert "identity_request" not in res.json()
    employee.refresh_from_db()
    assert employee.phone == "+7 777 000-11-22"
    assert not IdentityChangeRequest.objects.filter(
        employee=employee, status=IdentityChangeRequest.Status.PENDING).exists()


@pytest.mark.django_db
def test_force_edit_supersedes_a_pending_request(
        employee, approver_auth, fallback_log_mode):
    """Иначе подтверждение старой заявки вернуло бы прежнее значение поверх нового."""
    svc.capture(employee, {"phone": "+7 700 111-11-11"}, actor_id=1)

    Client().put(
        f"/api/hr/v1/employees/{employee.id}/",
        data=json.dumps({"phone": "+7 777 000-11-22"}),
        content_type="application/json", **_force_auth(),
    )

    request = IdentityChangeRequest.objects.get(employee=employee)
    assert request.status == IdentityChangeRequest.Status.REJECTED
    assert "hr.identity.force" in request.decision_note


@pytest.mark.django_db
def test_force_edit_leaves_other_pending_fields_alone(
        employee, approver_auth, fallback_log_mode):
    """Снимается только то поле, которое записали напрямую."""
    svc.capture(employee, {"phone": "+7 700 111-11-11", "bio": "Прораб"}, actor_id=1)

    Client().put(
        f"/api/hr/v1/employees/{employee.id}/",
        data=json.dumps({"phone": "+7 777 000-11-22"}),
        content_type="application/json", **_force_auth(),
    )

    request = IdentityChangeRequest.objects.get(employee=employee)
    assert request.status == IdentityChangeRequest.Status.PENDING
    assert [f.field for f in request.fields.all()] == ["bio"]


@pytest.mark.django_db
def test_without_the_permission_the_edit_still_goes_to_approval(
        lead_auth, employee, approver_auth, fallback_log_mode):
    """Право не входит ни в один уровень — даже lead идёт через подтверждение."""
    res = Client().put(
        f"/api/hr/v1/employees/{employee.id}/",
        data=json.dumps({"phone": "+7 777 000-11-22"}),
        content_type="application/json", **lead_auth,
    )

    assert res.json()["identity_request"]["status"] == IdentityChangeRequest.Status.PENDING


def test_force_key_is_not_part_of_any_level():
    from apps.hr.permissions import IDENTITY_FORCE, LEVEL_PRESETS

    assert not any(IDENTITY_FORCE in preset for preset in LEVEL_PRESETS.values())
