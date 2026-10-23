"""Перенос карточки, порядок в колонке и быстрое добавление (мастер-план §3.2,
§5.3, §6.1–6.2).
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.tasks.models import (BoardCardRank, BoardKind, Status, TaskActivity, TaskAssignee)
from apps.tasks.services import board_rank

from .helpers import BASE, post_json
from .org_fixtures import (EMP_IT, HEAD_IT, OD, as_user, make_org, make_task)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _mine(**fields):
    task = make_task(assignee_id=EMP_IT, **fields)
    TaskAssignee.objects.create(task=task, user_id=EMP_IT, role="primary")
    return task


def _move(task_id, board, status, who=EMP_IT, **neighbours):
    return post_json(Client(), f"{BASE}/tasks/{task_id}/move",
                     {"board": board, "status": status, **neighbours}, **as_user(who))


def _column(path, status, who=EMP_IT):
    body = Client().get(f"{BASE}/{path}", **as_user(who)).json()
    column = next(column for column in body["columns"] if column["status"] == status)
    return [card["id"] for card in column["cards"]]


PERSONAL = {"kind": "personal"}


def test_move_to_another_column_changes_status(org):
    task = _mine(status=Status.TODO)
    response = _move(task.pk, PERSONAL, "in_progress")
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "in_progress" and response.json()["rank"]
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS
    assert TaskActivity.objects.filter(task=task, field_name="status",
                                       new_value="in_progress").exists()


def test_move_against_the_transition_scheme_is_400_with_allowed(org):
    task = _mine(status=Status.BACKLOG)
    response = _move(task.pk, PERSONAL, "done")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "task_transition_invalid"
    assert set(body["details"]["allowed"]) == {"todo", "in_progress", "cancelled"}
    task.refresh_from_db()
    assert task.status == Status.BACKLOG


def test_reorder_between_neighbours(org):
    first, second, third = (_mine(status=Status.TODO) for _ in range(3))
    # Без рангов колонка идёт по -created_at: третья, вторая, первая.
    assert _column("boards/personal", "todo") == [third.pk, second.pk, first.pk]
    response = _move(first.pk, PERSONAL, "todo", before_id=third.pk, after_id=second.pk)
    assert response.status_code == 200, response.content
    assert _column("boards/personal", "todo") == [third.pk, first.pk, second.pk]
    # В начало колонки — только сосед снизу.
    assert _move(second.pk, PERSONAL, "todo", after_id=third.pk).status_code == 200
    assert _column("boards/personal", "todo") == [second.pk, third.pk, first.pk]


def test_neighbours_from_another_column_are_stale(org):
    task = _mine(status=Status.TODO)
    other = _mine(status=Status.IN_PROGRESS)
    response = _move(task.pk, PERSONAL, "todo", before_id=other.pk)
    assert response.status_code == 409
    assert response.json()["code"] == "board_order_stale"


def test_non_adjacent_neighbours_are_stale(org):
    a, b, c = (_mine(status=Status.TODO) for _ in range(3))
    moving = _mine(status=Status.TODO)
    order = _column("boards/personal", "todo")
    response = _move(moving.pk, PERSONAL, "todo", before_id=order[0], after_id=order[3])
    assert response.status_code == 409


def test_department_board_reorder_rights(org):
    """Порядок на доске отдела: участник задачи — у своих карточек, глава
    отдела доски — у любых (§5.3); видящий, но не участник — 403."""
    board = {"kind": "department", "id": org.it.id}
    foreign = make_task(department_id=org.it.id, status=Status.TODO)
    make_task(department_id=org.it.id, status=Status.TODO)
    assert _move(foreign.pk, board, "todo", who=EMP_IT).status_code == 403
    assert _move(foreign.pk, board, "in_progress", who=EMP_IT).status_code == 403
    assert _move(foreign.pk, board, "todo", who=HEAD_IT).status_code == 200


def test_directors_see_but_do_not_move(org):
    task = make_task(department_id=org.ops.id, status=Status.TODO)
    board = {"kind": "department", "id": org.ops.id}
    assert _move(task.pk, board, "in_progress", who=OD).status_code == 403


def test_task_not_on_the_board_is_404(org):
    task = _mine(status=Status.TODO, department_id=org.ops.id)
    response = _move(task.pk, {"kind": "department", "id": org.it.id}, "todo")
    assert response.status_code == 404


def test_personal_board_id_is_rejected(org):
    task = _mine(status=Status.TODO)
    response = _move(task.pk, {"kind": "personal", "id": 709}, "todo")
    assert response.status_code == 422


def test_ranks_belong_to_the_board(org):
    """Порядок на личной доске не трогает порядок на доске отдела."""
    task = _mine(status=Status.TODO, department_id=org.it.id)
    assert _move(task.pk, PERSONAL, "todo").status_code == 200
    kinds = set(BoardCardRank.objects.filter(task=task).values_list("board_kind", "board_id"))
    assert kinds == {(BoardKind.PERSONAL, EMP_IT)}


def test_long_ranks_are_rebalanced(org, monkeypatch):
    """Порог 1 символ: вставка между соседними однобуквенными рангами даёт
    двухбуквенный — колонка раскладывается заново, порядок сохраняется."""
    monkeypatch.setattr(board_rank, "MAX_LENGTH", 1)
    a, b, c = (_mine(status=Status.TODO) for _ in range(3))
    order = _column("boards/personal", "todo")                       # c, b, a
    for _ in range(3):
        top, middle, bottom = _column("boards/personal", "todo")
        response = _move(bottom, PERSONAL, "todo", before_id=top, after_id=middle)
        assert response.status_code == 200, response.content
        assert _column("boards/personal", "todo") == [top, bottom, middle]
    ranks = list(BoardCardRank.objects.filter(board_kind=BoardKind.PERSONAL)
                 .values_list("rank", flat=True))
    assert len(ranks) == 3 and all(len(rank) == 1 for rank in ranks)
    assert set(order) == {a.pk, b.pk, c.pk}


# ── быстрое добавление ──────────────────────────────────────────────────

def test_quick_add_goes_to_the_end_of_its_column(org):
    first = _mine(status=Status.TODO)
    second = _mine(status=Status.TODO)
    response = post_json(Client(), f"{BASE}/tasks/",
                         {"summary": "Быстрая", "status": "todo", "board": PERSONAL},
                         **as_user(EMP_IT))
    assert response.status_code == 201, response.content
    new_id = response.json()["id"]
    assert _column("boards/personal", "todo") == [second.pk, first.pk, new_id]


def test_quick_add_to_an_invisible_board_is_404(org):
    response = post_json(Client(), f"{BASE}/tasks/",
                         {"summary": "Чужая", "status": "todo",
                          "board": {"kind": "department", "id": org.ops.id}},
                         **as_user(EMP_IT))
    assert response.status_code == 404


def test_own_assignment_is_not_new_but_assigned_by_others_is(org):
    created = post_json(Client(), f"{BASE}/tasks/",
                        {"summary": "Сам себе", "status": "todo",
                         "assignees": [{"user_id": EMP_IT, "role": "primary"},
                                       {"user_id": HEAD_IT, "role": "collaborator"}]},
                        **as_user(EMP_IT)).json()
    rows = dict(TaskAssignee.objects.filter(task_id=created["id"])
                .values_list("user_id", "seen_at"))
    assert rows[EMP_IT] is not None and rows[HEAD_IT] is None


# ── перенос в отдел ─────────────────────────────────────────────────────

def test_transfer_moves_card_to_the_end_of_target_board(org):
    existing = make_task(department_id=org.ops.id, status=Status.TODO)
    task = make_task(department_id=org.it.id, status=Status.TODO)
    BoardCardRank.objects.create(board_kind=BoardKind.DEPARTMENT, board_id=org.it.id,
                                 task=task, rank="V")
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/transfer",
                         {"department_id": org.ops.id}, **as_user(HEAD_IT))
    assert response.status_code == 200, response.content
    rows = set(BoardCardRank.objects.filter(task=task).values_list("board_kind", "board_id"))
    assert rows == {(BoardKind.DEPARTMENT, org.ops.id)}
    assert _column(f"boards/departments/{org.ops.id}", "todo", who=OD) == [existing.pk, task.pk]
