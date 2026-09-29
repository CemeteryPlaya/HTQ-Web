"""Порядок дат: «конец раньше начала» — это 422 с текстом, а не 500.

Правило само по себе скучное, интересно то, что до него доходило раньше.
В БД оно стоит пятью ``CheckConstraint``, а в схемах ``*Create`` — валидатором
с прямой пометкой «здесь это 422 с текстом, а не IntegrityError→500». Но на
``*Update`` валидатора не было, поэтому ПРАВКА уходила в базу и возвращалась:

* у блока — как 409 «Блок с таким названием или кодом уже есть на этом
  объекте», потому что вьюха ловит ``IntegrityError`` и знает про него одно
  объяснение. Человек, поправивший даты, читал про дубль имени;
* у остальных — как голая 500.

Отдельно проверяется ЧАСТИЧНЫЙ ``PATCH``: он присылает одну дату, вторая
лежит в строке, и схема тут бессильна — правило держит сервис по слитому
состоянию (``date_rules.assert_instance_ordered``).

У задачи валидатора не было и при создании, у проекта нет даже ограничения в
БД — там перепутанные даты просто сохранялись.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.tasks.models import Project, Roadmap, Site, SiteBlock, Task

from .helpers import BASE, admin_token, auth, patch_json, post_json

D = dt.date


def detail_text(resp) -> str:
    """Текст 422 независимо от того, кто его поднял.

    У платформы два законных источника этого кода, и envelope у них разный:
    валидатор схемы (Pydantic) кладёт в ``detail`` СПИСОК ошибок, сервисное
    правило (``date_rules``) — строку. Тест проверяет смысл сообщения, а не
    того, кто первым его заметил, поэтому обе формы сводятся к тексту.
    """
    detail = resp.json()["detail"]
    if isinstance(detail, str):
        return detail
    return " ".join(str(item.get("msg", item)) for item in detail)


@pytest.fixture
def site(db) -> Site:
    return Site.objects.create(name="Сазаган", code="SZG")


@pytest.fixture
def block(site) -> SiteBlock:
    return SiteBlock.objects.create(site=site, name="Блок I", order=1,
                                    start_date=D(2026, 3, 1),
                                    end_date=D(2026, 4, 1))


@pytest.fixture
def project(db) -> Project:
    return Project.objects.create(name="Алга")


# ── создание ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_block_create_rejects_reversed_dates(site):
    resp = post_json(Client(), f"{BASE}/sites/{site.id}/blocks/",
                     {"name": "Блок II", "start_date": "2026-05-01",
                      "end_date": "2026-04-01"}, **auth(admin_token()))
    assert resp.status_code == 422
    assert "позже" in detail_text(resp)


@pytest.mark.django_db
def test_task_create_rejects_reversed_dates(db):
    """У задачи валидатора не было вовсе — только ck_task_dates, то есть 500."""
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Развезти валы", "start_date": "2026-05-01",
                      "due_date": "2026-04-01"}, **auth(admin_token()))
    assert resp.status_code == 422
    assert "позже" in detail_text(resp)


@pytest.mark.django_db
def test_project_create_rejects_reversed_dates(db):
    """У проекта нет и ограничения в БД: до этой проверки строка сохранялась."""
    resp = post_json(Client(), f"{BASE}/projects/",
                     {"name": "Тобол", "start_date": "2026-05-01",
                      "end_date": "2026-04-01"}, **auth(admin_token()))
    assert resp.status_code == 422
    assert Project.objects.filter(name="Тобол").count() == 0


# ── правка целиком ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_block_update_rejects_reversed_dates(block):
    resp = patch_json(Client(), f"{BASE}/blocks/{block.id}",
                      {"start_date": "2026-05-01", "end_date": "2026-04-01"},
                      **auth(admin_token()))
    assert resp.status_code == 422
    detail = detail_text(resp)
    assert "позже" in detail
    # Ровно та подмена, ради которой тест и написан: раньше отвечало 409 про
    # занятое имя, хотя имя человек не трогал.
    assert "названием" not in detail


@pytest.mark.django_db
def test_roadmap_update_rejects_reversed_dates(project, block):
    roadmap = Roadmap.objects.create(project=project, site_block=block,
                                     name="Пакет 1")
    resp = patch_json(Client(), f"{BASE}/roadmaps/{roadmap.id}",
                      {"planned_start_date": "2026-05-01",
                       "planned_end_date": "2026-04-01"},
                      **auth(admin_token()))
    assert resp.status_code == 422
    assert "Плановая" in detail_text(resp)


# ── частичная правка: вторая дата лежит в строке ────────────────────────

@pytest.mark.django_db
def test_partial_update_compares_with_stored_date(block):
    """Схема этого не видит: в теле одна дата. Держит правило сервис."""
    resp = patch_json(Client(), f"{BASE}/blocks/{block.id}",
                      {"end_date": "2026-02-01"}, **auth(admin_token()))
    assert resp.status_code == 422
    block.refresh_from_db()
    assert block.end_date == D(2026, 4, 1)


@pytest.mark.django_db
def test_partial_update_with_ordered_dates_still_saves(block):
    """Проверка не должна мешать нормальной правке одного поля."""
    resp = patch_json(Client(), f"{BASE}/blocks/{block.id}",
                      {"end_date": "2026-06-01"}, **auth(admin_token()))
    assert resp.status_code == 200
    block.refresh_from_db()
    assert block.end_date == D(2026, 6, 1)


@pytest.mark.django_db
def test_task_partial_update_compares_with_stored_date(db):
    task = Task.objects.create(summary="Монтаж", start_date=D(2026, 3, 1),
                               due_date=D(2026, 4, 1))
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}",
                      {"due_date": "2026-02-01"}, **auth(admin_token()))
    assert resp.status_code == 422
    task.refresh_from_db()
    assert task.due_date == D(2026, 4, 1)
