"""Контракт /api/hr/v1/{vacancies,applications}/* — паритет с
services/hr/app/api/v1/{vacancies,applications}.py.

Провенанс формы ответов: app/schemas/vacancy.py (VacancyOut), app/schemas/
application.py (ApplicationOut), app/schemas/common.py (PaginatedResponse),
поведение — app/services/recruitment_service.py.

Авторизация (docs/plans/2026-07-20-hr-domain.md, под-модуль hr-recruiting):
ВСЕ 13 эндпойнтов — ``get_current_user`` исходника (обычный jwt), БЕЗ
``require_hr_write``/``admin=True`` — в отличие от positions/org, запись
вакансий/откликов не защищена coarse-гейтом is_elevated в исходнике. Это
странность исходника, не баг порта.

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * список — конверт PaginatedResponse {items,total,page,pages,limit};
  * PUT + PATCH оба работают на /{id}/ (PATCH — то, что реально шлёт фронт);
  * DELETE /vacancies/{id}/ — НЕ физическое удаление, closed-статус + closed_at;
  * POST /applications/ с несуществующим vacancy_id -> 404 "Vacancy not found",
    НЕ 422;
  * /applications/archive/ — литеральный роут ДО /{id}/, documents всегда [],
    т.к. модель Document ещё не перенесена (hr-docs, отдельная задача);
  * change_status пишет notes только если truthy (пустая строка не затирает).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.hr.models import Application, Department, Employee, Position, Vacancy
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

VBASE = "/api/hr/v1/vacancies"
ABASE = "/api/hr/v1/applications"


@pytest.fixture
def dep(db):
    return Department.objects.create(name="ИТ", path="it")


@pytest.fixture
def pos(db, dep):
    return Position.objects.create(title="Рекрутер", department=dep, weight=100)


@pytest.fixture
def auth(db):
    """Обычный вошедший пользователь — в этом под-модуле ЕГО ДОСТАТОЧНО и для
    записи (в отличие от positions/org: recruiting не зовёт require_hr_write)."""
    user = User.objects.create(
        username="rec-user", email="rec-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _vac(dep, pos, **kw):
    return Vacancy.objects.create(department=dep, position=pos, **{"title": "Инженер", **kw})


def _app(vacancy, **kw):
    defaults = {"candidate_name": "Иван Иванов", "candidate_email": "ivan@example.com"}
    defaults.update(kw)
    return Application.objects.create(vacancy=vacancy, **defaults)


# ── auth (странность исходника: запись НЕ требует is_elevated) ─────────────

@pytest.mark.django_db
def test_vacancy_list_requires_jwt():
    assert Client().get(f"{VBASE}/").status_code == 401


@pytest.mark.django_db
def test_vacancy_create_requires_jwt_but_not_admin(auth, dep, pos):
    """Обычный (не is_elevated) jwt-пользователь МОЖЕТ создать вакансию —
    в отличие от positions/org, recruiting не зовёт require_hr_write."""
    resp = Client().post(
        f"{VBASE}/",
        data={"title": "Инженер", "department_id": dep.id, "position_id": pos.id},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_vacancy_create_requires_jwt_at_all(dep, pos):
    resp = Client().post(
        f"{VBASE}/", data={"title": "X", "department_id": dep.id, "position_id": pos.id},
        content_type="application/json",
    )
    assert resp.status_code == 401


# ── GET /vacancies/ (list, paginated envelope) ──────────────────────────────

@pytest.mark.django_db
def test_vacancy_list_paginated_envelope(auth, dep, pos):
    _vac(dep, pos, title="Первая")
    _vac(dep, pos, title="Вторая")

    resp = Client().get(f"{VBASE}/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "page", "pages", "limit"}
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["limit"] == 20
    assert body["pages"] == 1
    assert {"id", "title", "department_id", "position_id", "description", "requirements",
            "status", "assigned_recruiter_id", "opened_at", "closed_at",
            "created_at", "updated_at"} == set(body["items"][0])


@pytest.mark.django_db
def test_vacancy_list_filters_by_status_and_department(auth, dep, pos):
    other_dep = Department.objects.create(name="Финансы", path="fin")
    _vac(dep, pos, title="Открытая", status="open")
    _vac(dep, pos, title="Закрытая", status="closed")
    _vac(other_dep, pos, title="Чужой отдел", status="open")

    resp = Client().get(f"{VBASE}/?status=open", **auth)
    titles = {v["title"] for v in resp.json()["items"]}
    assert titles == {"Открытая", "Чужой отдел"}

    resp2 = Client().get(f"{VBASE}/?department_id={dep.id}", **auth)
    titles2 = {v["title"] for v in resp2.json()["items"]}
    assert titles2 == {"Открытая", "Закрытая"}


@pytest.mark.django_db
def test_vacancy_list_pagination_page_and_limit(auth, dep, pos):
    for i in range(5):
        _vac(dep, pos, title=f"V{i}")

    resp = Client().get(f"{VBASE}/?page=2&limit=2", **auth)
    body = resp.json()
    assert body["page"] == 2
    assert body["limit"] == 2
    assert body["total"] == 5
    assert body["pages"] == 3
    assert len(body["items"]) == 2


@pytest.mark.django_db
def test_vacancy_list_invalid_query_params_422(auth):
    resp = Client().get(f"{VBASE}/?page=0", **auth)
    assert resp.status_code == 422
    resp2 = Client().get(f"{VBASE}/?limit=500", **auth)
    assert resp2.status_code == 422


# ── POST /vacancies/ (create) ────────────────────────────────────────────────

@pytest.mark.django_db
def test_vacancy_create_defaults(auth, dep, pos):
    resp = Client().post(
        f"{VBASE}/", data={"title": "Бэкенд-разработчик", "department_id": dep.id, "position_id": pos.id},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "open"
    assert body["description"] == ""
    assert body["requirements"] == ""
    assert body["opened_at"] is not None
    assert body["closed_at"] is None
    assert body["assigned_recruiter_id"] is None


@pytest.mark.django_db
def test_vacancy_create_with_recruiter(auth, dep, pos):
    recruiter = Employee.objects.create(
        first_name="А", last_name="Б", email="ab@htq.test",
        department=dep, position=pos, hire_date=datetime.date(2024, 1, 9),
    )
    resp = Client().post(
        f"{VBASE}/",
        data={
            "title": "Тестировщик", "department_id": dep.id, "position_id": pos.id,
            "assigned_recruiter_id": recruiter.id,
        },
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    assert resp.json()["assigned_recruiter_id"] == recruiter.id


# ── GET /vacancies/{id}/ ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_vacancy_detail_and_404(auth, dep, pos):
    v = _vac(dep, pos)
    resp = Client().get(f"{VBASE}/{v.id}/", **auth)
    assert resp.status_code == 200
    assert resp.json()["title"] == "Инженер"

    missing = Client().get(f"{VBASE}/999999/", **auth)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Vacancy not found"


# ── PUT + PATCH /vacancies/{id}/ ─────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("method", ["put", "patch"])
def test_vacancy_update_accepts_both_put_and_patch(auth, dep, pos, method):
    v = _vac(dep, pos)
    resp = getattr(Client(), method)(
        f"{VBASE}/{v.id}/", data={"title": "Ст. инженер"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Ст. инженер"
    v.refresh_from_db()
    assert v.title == "Ст. инженер"


@pytest.mark.django_db
def test_vacancy_update_ignores_none_fields(auth, dep, pos):
    v = _vac(dep, pos, description="исходное")
    Client().patch(
        f"{VBASE}/{v.id}/", data={"title": "Новое", "description": None},
        content_type="application/json", **auth,
    )
    v.refresh_from_db()
    assert v.title == "Новое"
    assert v.description == "исходное"


@pytest.mark.django_db
def test_vacancy_update_404(auth):
    resp = Client().patch(
        f"{VBASE}/999999/", data={"title": "X"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 404


# ── DELETE /vacancies/{id}/ (close, не физическое удаление) ─────────────────

@pytest.mark.django_db
def test_vacancy_delete_closes_not_removes(auth, dep, pos):
    v = _vac(dep, pos, status="open")
    resp = Client().delete(f"{VBASE}/{v.id}/", **auth)
    assert resp.status_code == 204
    v.refresh_from_db()
    assert Vacancy.objects.filter(id=v.id).exists()
    assert v.status == "closed"
    assert v.closed_at == datetime.date.today()


@pytest.mark.django_db
def test_vacancy_delete_404(auth):
    resp = Client().delete(f"{VBASE}/999999/", **auth)
    assert resp.status_code == 404


# ── GET /vacancies/{id}/applications ─────────────────────────────────────────

@pytest.mark.django_db
def test_vacancy_applications_ordered_desc(auth, dep, pos):
    v = _vac(dep, pos)
    _app(v, candidate_name="Первый", applied_at=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc))
    _app(v, candidate_name="Второй", applied_at=datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc))

    resp = Client().get(f"{VBASE}/{v.id}/applications", **auth)
    assert resp.status_code == 200
    names = [a["candidate_name"] for a in resp.json()]
    assert names == ["Второй", "Первый"]


@pytest.mark.django_db
def test_vacancy_applications_404_for_missing_vacancy(auth):
    resp = Client().get(f"{VBASE}/999999/applications", **auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Vacancy not found"


@pytest.mark.django_db
def test_vacancy_applications_only_own(auth, dep, pos):
    v1 = _vac(dep, pos, title="V1")
    v2 = _vac(dep, pos, title="V2")
    _app(v1, candidate_name="A")
    _app(v2, candidate_name="B")

    resp = Client().get(f"{VBASE}/{v1.id}/applications", **auth)
    names = [a["candidate_name"] for a in resp.json()]
    assert names == ["A"]


# ═══════════════════════════════════════════════════════════════════════════
#  /applications/*
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_application_list_requires_jwt():
    assert Client().get(f"{ABASE}/").status_code == 401


@pytest.mark.django_db
def test_application_list_paginated_envelope(auth, dep, pos):
    v = _vac(dep, pos)
    _app(v, candidate_name="Первый")
    _app(v, candidate_name="Второй")

    resp = Client().get(f"{ABASE}/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "page", "pages", "limit"}
    assert body["total"] == 2
    assert {"id", "vacancy_id", "candidate_name", "candidate_email", "candidate_phone",
            "resume_url", "cover_letter", "notes", "status", "applied_at",
            "created_at", "updated_at"} == set(body["items"][0])


@pytest.mark.django_db
def test_application_list_pagination(auth, dep, pos):
    v = _vac(dep, pos)
    for i in range(5):
        _app(v, candidate_name=f"C{i}", candidate_email=f"c{i}@x.test")

    resp = Client().get(f"{ABASE}/?page=2&limit=2", **auth)
    body = resp.json()
    assert body["page"] == 2
    assert body["total"] == 5
    assert body["pages"] == 3
    assert len(body["items"]) == 2


@pytest.mark.django_db
def test_application_list_invalid_query_params_422(auth):
    resp = Client().get(f"{ABASE}/?page=0", **auth)
    assert resp.status_code == 422


# ── POST /applications/ (create) ─────────────────────────────────────────────

@pytest.mark.django_db
def test_application_create_requires_jwt_but_not_admin(auth, dep, pos):
    v = _vac(dep, pos)
    resp = Client().post(
        f"{ABASE}/",
        data={"vacancy_id": v.id, "candidate_name": "Пётр", "candidate_email": "petr@example.com"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "new"
    assert body["vacancy_id"] == v.id


@pytest.mark.django_db
def test_application_create_missing_vacancy_returns_404_not_422(auth):
    """Буквальный порт: create_application проверяет вакансию ДО создания
    отклика — 404 "Vacancy not found", а не 422 схемы."""
    resp = Client().post(
        f"{ABASE}/",
        data={"vacancy_id": 999999, "candidate_name": "Пётр", "candidate_email": "petr@example.com"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Vacancy not found"


@pytest.mark.django_db
def test_application_create_invalid_email_422(auth, dep, pos):
    v = _vac(dep, pos)
    resp = Client().post(
        f"{ABASE}/",
        data={"vacancy_id": v.id, "candidate_name": "Пётр", "candidate_email": "not-an-email"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 422


# ── GET /applications/archive/ (литеральный роут ДО /{id}/) ─────────────────

@pytest.mark.django_db
def test_archive_requires_jwt():
    assert Client().get(f"{ABASE}/archive/").status_code == 401


@pytest.mark.django_db
def test_archive_returns_only_closed_statuses(auth, dep, pos):
    v = _vac(dep, pos)
    _app(v, candidate_name="Новый", status="new")
    _app(v, candidate_name="Нанят", status="hired")
    _app(v, candidate_name="Отклонён", status="rejected")

    resp = Client().get(f"{ABASE}/archive/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"applications", "documents"}
    names = {a["candidate_name"] for a in body["applications"]}
    assert names == {"Нанят", "Отклонён"}
    # Document ещё не перенесена в apps.hr (hr-docs, отдельная задача) —
    # documents всегда пустой список.
    assert body["documents"] == []


@pytest.mark.django_db
def test_archive_route_does_not_shadow_int_id(auth, dep, pos):
    """``archive/`` — литеральный роут ДО ``/<int:id>/``: числовой id всё ещё
    резолвится в application_detail, а не пытается матчить archive."""
    v = _vac(dep, pos)
    a = _app(v)
    resp = Client().get(f"{ABASE}/{a.id}/", **auth)
    assert resp.status_code == 200
    assert resp.json()["id"] == a.id


# ── GET /applications/{id}/ ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_application_detail_and_404(auth, dep, pos):
    v = _vac(dep, pos)
    a = _app(v)
    resp = Client().get(f"{ABASE}/{a.id}/", **auth)
    assert resp.status_code == 200
    assert resp.json()["candidate_name"] == "Иван Иванов"

    missing = Client().get(f"{ABASE}/999999/", **auth)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Application not found"


# ── PUT + PATCH /applications/{id}/ ──────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("method", ["put", "patch"])
def test_application_update_accepts_both_put_and_patch(auth, dep, pos, method):
    v = _vac(dep, pos)
    a = _app(v)
    resp = getattr(Client(), method)(
        f"{ABASE}/{a.id}/", data={"candidate_name": "Обновлённый"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 200
    assert resp.json()["candidate_name"] == "Обновлённый"
    a.refresh_from_db()
    assert a.candidate_name == "Обновлённый"


@pytest.mark.django_db
def test_application_update_ignores_none_fields(auth, dep, pos):
    v = _vac(dep, pos)
    a = _app(v, notes="исходное")
    Client().patch(
        f"{ABASE}/{a.id}/", data={"candidate_name": "Новое имя", "notes": None},
        content_type="application/json", **auth,
    )
    a.refresh_from_db()
    assert a.candidate_name == "Новое имя"
    assert a.notes == "исходное"


@pytest.mark.django_db
def test_application_update_404(auth):
    resp = Client().patch(
        f"{ABASE}/999999/", data={"candidate_name": "X"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 404


# ── DELETE /applications/{id}/ ───────────────────────────────────────────────

@pytest.mark.django_db
def test_application_delete_204(auth, dep, pos):
    v = _vac(dep, pos)
    a = _app(v)
    resp = Client().delete(f"{ABASE}/{a.id}/", **auth)
    assert resp.status_code == 204
    assert not Application.objects.filter(id=a.id).exists()


@pytest.mark.django_db
def test_application_delete_404(auth):
    resp = Client().delete(f"{ABASE}/999999/", **auth)
    assert resp.status_code == 404


# ── POST /applications/{id}/status ───────────────────────────────────────────

@pytest.mark.django_db
def test_change_status_updates_status_and_notes(auth, dep, pos):
    v = _vac(dep, pos)
    a = _app(v, status="new")
    resp = Client().post(
        f"{ABASE}/{a.id}/status", data={"status": "interview", "notes": "Собеседование в пятницу"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "interview"
    assert body["notes"] == "Собеседование в пятницу"


@pytest.mark.django_db
def test_change_status_empty_string_notes_is_not_persisted(auth, dep, pos):
    """Буквальный порт: ``if data.notes:`` (truthy) — пустая строка НЕ
    затирает существующие notes."""
    v = _vac(dep, pos)
    a = _app(v, status="new", notes="старые заметки")
    resp = Client().post(
        f"{ABASE}/{a.id}/status", data={"status": "reviewed", "notes": ""},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 200
    a.refresh_from_db()
    assert a.status == "reviewed"
    assert a.notes == "старые заметки"


@pytest.mark.django_db
def test_change_status_invalid_value_422(auth, dep, pos):
    v = _vac(dep, pos)
    a = _app(v)
    resp = Client().post(
        f"{ABASE}/{a.id}/status", data={"status": "bogus"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_change_status_404(auth):
    resp = Client().post(
        f"{ABASE}/999999/status", data={"status": "hired"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Application not found"


@pytest.mark.django_db
def test_change_status_requires_jwt():
    resp = Client().post(
        f"{ABASE}/1/status", data={"status": "hired"}, content_type="application/json",
    )
    assert resp.status_code == 401
