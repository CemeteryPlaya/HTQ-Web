"""Контракт GET /api/hr/v1/internal/supervisor — паритет с
services/hr/app/api/v1/internal.py.

S2S-эндпойнт: авторизация — общий секрет в заголовке ``X-Internal-Token``
(НЕ JWT — ``auth=None`` в терминах htqweb.http.api_view), сверяемый с
``INTERNAL_S2S_TOKEN`` (или legacy ``MESSENGER_INTERNAL_TOKEN``) из
окружения. 503, если секрет не сконфигурирован вовсе; 401 при несовпадении.

Логика резолюции — climbs the department ltree-path upward to the nearest
parent department with a manager different from the employee themself
(EmployeeCardService._resolve_manager, уже перенесённая под-модулем
employee_card — переиспользуется буквально, не дублируется).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.hr.models import Department, Employee, Position

BASE = "/api/hr/v1/internal/supervisor"


def _dep(name, path, **kw):
    return Department.objects.create(name=name, path=path, **kw)


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email, user_id, **kw):
    return Employee.objects.create(
        first_name="И", last_name="И", email=email, department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user_id, **kw,
    )


@pytest.fixture(autouse=True)
def internal_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_S2S_TOKEN", "s2s-secret")
    monkeypatch.delenv("MESSENGER_INTERNAL_TOKEN", raising=False)
    return "s2s-secret"


@pytest.mark.django_db
def test_missing_token_configured_gives_503(monkeypatch):
    monkeypatch.delenv("INTERNAL_S2S_TOKEN", raising=False)
    monkeypatch.delenv("MESSENGER_INTERNAL_TOKEN", raising=False)
    resp = Client().get(f"{BASE}?user_id=1")
    assert resp.status_code == 503


@pytest.mark.django_db
def test_wrong_token_401():
    resp = Client().get(f"{BASE}?user_id=1", HTTP_X_INTERNAL_TOKEN="wrong")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_missing_token_header_401():
    resp = Client().get(f"{BASE}?user_id=1")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_no_jwt_required_only_internal_token():
    resp = Client().get(f"{BASE}?user_id=999999", HTTP_X_INTERNAL_TOKEN="s2s-secret")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_unknown_user_returns_null_supervisor():
    resp = Client().get(f"{BASE}?user_id=999999", HTTP_X_INTERNAL_TOKEN="s2s-secret")
    assert resp.json() == {"supervisor_user_id": None}


@pytest.mark.django_db
def test_resolves_department_manager_as_supervisor():
    dep = _dep("ИТ", "it")
    boss_pos = _pos("Начальник", dep, weight=10)
    boss = _emp(dep, boss_pos, "boss@htq.test", user_id=1)
    dep.manager = boss
    dep.save(update_fields=["manager"])

    worker_pos = _pos("Инженер", dep, weight=50)
    _emp(dep, worker_pos, "worker@htq.test", user_id=2)

    resp = Client().get(f"{BASE}?user_id=2", HTTP_X_INTERNAL_TOKEN="s2s-secret")
    assert resp.status_code == 200
    assert resp.json() == {"supervisor_user_id": 1}


@pytest.mark.django_db
def test_climbs_to_parent_when_self_managing_own_department():
    parent = _dep("Компания", "co")
    parent_pos = _pos("Директор", parent, weight=1)
    director = _emp(parent, parent_pos, "director@htq.test", user_id=1)
    parent.manager = director
    parent.save(update_fields=["manager"])

    child = _dep("ИТ", "co.it")
    child_pos = _pos("Начальник ИТ", child, weight=10)
    head = _emp(child, child_pos, "head@htq.test", user_id=2)
    child.manager = head
    child.save(update_fields=["manager"])

    # head manages their own department -> climb to the parent's manager.
    resp = Client().get(f"{BASE}?user_id=2", HTTP_X_INTERNAL_TOKEN="s2s-secret")
    assert resp.json() == {"supervisor_user_id": 1}


@pytest.mark.django_db
def test_missing_user_id_query_param_422():
    resp = Client().get(BASE, HTTP_X_INTERNAL_TOKEN="s2s-secret")
    assert resp.status_code == 422
