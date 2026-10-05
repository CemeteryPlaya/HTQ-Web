"""Доски «Проектов» для держателя «Доски задач проекта» (решение Руслана
01.10, узел ``project.board`` — ТД, ОД, АДМ, ПМ): кроме досок своего отдела
видны доски тех «Проектов», что он видит в БЗО — с ``project.all`` все
связанные, иначе проекты-участия. Только чтение: правка доски этим не
открывается.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.access.tests.helpers import assign
from apps.project.models import Project as Platform
from apps.project.models import ProjectMember
from apps.tasks.models import Project as Board
from apps.tasks.models import Roadmap, Site, SiteBlock

from .helpers import BASE, COMPANY, auth, patch_json

pytestmark = pytest.mark.django_db
ME = 7


def _board(code: str, *, member: int | None = None):
    platform = Platform.objects.create(code=code, name=f"Объект {code}", country_code="KZ",
                                       manager_user_id=member)
    if member:
        ProjectMember.objects.create(project=platform, user_id=member)
    board = Board.objects.create(name=f"Доска {code}", owner_id=member,
                                 project_ref=str(platform.pk))
    return platform, board


def _ids(response) -> set[int]:
    assert response.status_code == 200, response.content
    return {row["id"] for row in response.json()}


def test_holder_sees_boards_of_his_projects_and_only_reads_them():
    mine_platform, mine = _board("П-1", member=ME)
    _, other = _board("П-2")
    client = Client()
    # Без узла — прежнее правило (по отделу; отдела у сотрудника нет).
    assert _ids(client.get(f"{BASE}/projects/", **auth())) == set()

    assign(COMPANY, ME, "project.board", "view")
    assert _ids(client.get(f"{BASE}/projects/", **auth())) == {mine.pk}
    assert client.get(f"{BASE}/projects/{mine.pk}/", **auth()).status_code == 200
    assert client.get(f"{BASE}/projects/{other.pk}/", **auth()).status_code == 404
    assert client.get(f"{BASE}/projects/{mine.pk}/tasks/", **auth()).status_code == 200
    # Правка доски этим не открывается — даже владельцу (руководитель
    # «Проекта»): зона записи прежняя.
    edit = patch_json(client, f"{BASE}/projects/{mine.pk}/", {"description": "x"}, **auth())
    assert edit.status_code == 404
    assert mine_platform.code == "П-1"


def test_with_project_all_every_linked_board_is_visible():
    _, first = _board("П-1")
    _, second = _board("П-2")
    Board.objects.create(name="Без «Проекта»")
    assign(COMPANY, ME, "project.board", "view")
    assign(COMPANY, ME, "project.all", "view")
    assert _ids(Client().get(f"{BASE}/projects/", **auth())) == {first.pk, second.pk}


def test_project_ref_finds_the_board_of_one_project():
    platform, board = _board("П-1", member=ME)
    _board("П-2", member=ME)
    assign(COMPANY, ME, "project.board", "view")
    found = Client().get(f"{BASE}/projects/?project_ref={platform.pk}", **auth())
    assert _ids(found) == {board.pk}


def test_roadmaps_of_his_board_are_listed():
    _, board = _board("П-1", member=ME)
    block = SiteBlock.objects.create(site=Site.objects.create(name="Сазаган", code="SZG"),
                                     name="Блок 1")
    roadmap = Roadmap.objects.create(project=board, site_block=block, name="Каркас")
    client = Client()
    assert _ids(client.get(f"{BASE}/roadmaps/?project_id={board.pk}", **auth())) == set()
    assign(COMPANY, ME, "project.board", "view")
    assert _ids(client.get(f"{BASE}/roadmaps/?project_id={board.pk}", **auth())) == {roadmap.pk}
