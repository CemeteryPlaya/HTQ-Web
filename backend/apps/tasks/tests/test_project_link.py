"""Доска задач повторяет «Проект» БЗО (D-02: «Проект» главный).

Правка «Проекта» приезжает на связанную доску в той же транзакции; правку,
которую доска принять не может, «Проект» не получает вовсе (409
``E-PRJ-04``). Миграция ``0024`` связывает доски, заведённые до связи.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client

from apps.access.tests.helpers import assign, token
from apps.project.models import Project as Platform
from apps.tasks.models import Project as Board
from htqweb.tenancy.db import use_company

PROJECT_API = "/api/project/v1/projects"


def _patch(slug, project_id, body):
    tok = token(user_id=7, sub="7", company=slug)
    return Client().patch(f"{PROJECT_API}/{project_id}", data=json.dumps(body),
                          content_type="application/json",
                          HTTP_AUTHORIZATION=f"Bearer {tok}", HTTP_X_HTQ_COMPANY=slug)


@pytest.fixture
def linked(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project.projects", "full")
    assign(slug, 7, "project.all", "full")
    platform = Platform.objects.create(code="П-1", name="Объект 15", country_code="KZ",
                                       manager_user_id=11)
    board = Board.objects.create(name="Объект 15", owner_id=11, project_ref=str(platform.pk))
    return slug, platform, board


@pytest.mark.django_db
def test_project_edit_reaches_the_board(linked):
    slug, platform, board = linked
    resp = _patch(slug, platform.pk, {"name": "Объект 15-бис", "status": "closed",
                                      "date_start": "2026-02-01", "date_end": "2026-09-30",
                                      "manager_user_id": 12})
    assert resp.status_code == 200, resp.content
    with use_company(slug):
        board.refresh_from_db()
    assert (board.name, board.status, board.owner_id) == ("Объект 15-бис", "completed", 12)
    assert (board.start_date, board.end_date) == (dt.date(2026, 2, 1), dt.date(2026, 9, 30))


@pytest.mark.django_db
def test_edit_the_board_cannot_take_is_refused_whole(linked):
    """Имя занято другой доской — «Проект» не переименован вовсе, а не
    переименован без доски: данные не расходятся."""
    slug, platform, board = linked
    Board.objects.create(name="Занято")
    resp = _patch(slug, platform.pk, {"name": "Занято", "manager_user_id": 12})
    assert resp.status_code == 409 and resp.json()["code"] == "E-PRJ-04"
    assert "Занято" in resp.json()["detail"]
    reversed_dates = _patch(slug, platform.pk, {"date_start": "2026-05-01",
                                                "date_end": "2026-04-01"})
    assert reversed_dates.status_code == 409
    with use_company(slug):
        platform.refresh_from_db()
        board.refresh_from_db()
    assert (platform.name, platform.manager_user_id, platform.date_start) == (
        "Объект 15", 11, None)
    assert (board.name, board.owner_id) == ("Объект 15", 11)


@pytest.mark.django_db
def test_project_without_a_board_is_edited_freely(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project.projects", "full")
    assign(slug, 7, "project.all", "full")
    Board.objects.create(name="Занято")
    platform = Platform.objects.create(code="П-2", name="Свой", country_code="KZ")
    assert _patch(slug, platform.pk, {"name": "Занято"}).status_code == 200


# ── миграция 0024: доски, заведённые до связи ───────────────────────────

BEFORE = [("tasks", "0023_contractor_bpp_counterparty"), ("project", "0001_initial")]
AFTER = [("tasks", "0025_project_ref_unique")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


@pytest.fixture
def at_0023():
    try:
        yield _migrate(BEFORE)
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(
            [key for key in executor.loader.graph.leaf_nodes() if key[0] == "tasks"])


@pytest.mark.django_db(transaction=True)
def test_migration_links_every_board(at_0023):
    OldBoard = at_0023.get_model("tasks", "Project")
    OldPlatform = at_0023.get_model("project", "Project")
    plain = OldBoard.objects.create(name="Без связи", status="completed", owner_id=5,
                                    start_date=dt.date(2026, 1, 1))
    # Связанная командой: «Проект» с умолчаниями — пустое берётся с доски.
    made = OldPlatform.objects.create(code="TP-X", name="Связанная", country_code="KZ")
    tied = OldBoard.objects.create(name="Связанная", status="archived", owner_id=6,
                                   end_date=dt.date(2026, 12, 31), project_ref=str(made.pk))
    # Код TP-<id> занят «Проектом», заведённым человеком.
    squatter = OldBoard.objects.create(name="С конфликтом")
    OldPlatform.objects.create(code=f"TP-{squatter.pk}", name="Чужой", country_code="KZ",
                               created_by=3)

    apps = _migrate(AFTER)
    NewBoard = apps.get_model("tasks", "Project")
    NewPlatform = apps.get_model("project", "Project")
    Member = apps.get_model("project", "ProjectMember")

    assert not NewBoard.objects.filter(project_ref="").exists()
    first = NewPlatform.objects.get(pk=NewBoard.objects.get(pk=plain.pk).project_ref)
    assert (first.code, first.name, first.status, first.manager_user_id, first.date_start) == (
        f"TP-{plain.pk}", "Без связи", "closed", 5, dt.date(2026, 1, 1))
    assert Member.objects.filter(project=first, user_id=5).exists()

    kept = NewPlatform.objects.get(pk=made.pk)
    assert (kept.status, kept.manager_user_id, kept.date_end) == (
        "archived", 6, dt.date(2026, 12, 31))
    assert NewBoard.objects.get(pk=tied.pk).project_ref == str(made.pk)

    third = NewPlatform.objects.get(pk=NewBoard.objects.get(pk=squatter.pk).project_ref)
    assert third.code == f"TP-{squatter.pk}-2" and third.name == "С конфликтом"
    assert NewPlatform.objects.get(code=f"TP-{squatter.pk}").name == "Чужой"


@pytest.mark.django_db(transaction=True)
def test_migration_survives_a_nonstandard_board_status(at_0023):
    """M-1 итогового ревью: ограничения на статус в БД нет — неизвестное
    значение не роняет миграцию компании, доска и «Проект» становятся действующими."""
    OldBoard = at_0023.get_model("tasks", "Project")
    odd = OldBoard.objects.create(name="Нестандартный статус", status="on_hold")

    apps = _migrate(AFTER)
    board = apps.get_model("tasks", "Project").objects.get(pk=odd.pk)
    platform = apps.get_model("project", "Project").objects.get(pk=board.project_ref)
    assert platform.status == "active" and board.status == "active"
