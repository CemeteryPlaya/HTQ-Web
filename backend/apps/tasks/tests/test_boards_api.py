"""Канбан-доски: список, личная, отдела, проекта, настройки колонок, фильтры
(мастер-план §5.2, §6.1; решение K-34 — названия, цвета и скрытость колонок).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.tasks.models import (BoardSettings, DepartmentLinkKind, Label, Status, TaskAssignee,
                               TaskComment, TaskDepartmentLink, TaskWatcher)
from apps.tasks.services import board_service

from .helpers import BASE, put_json
from .org_fixtures import (EMP_DEV, EMP_IT, HEAD_IT, OD, OUTSIDER, TD, as_user, make_board,
                           make_org, make_task)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _get(path, who=EMP_IT, **params):
    return Client().get(f"{BASE}/{path}", params, **as_user(who))


def _cards(body, status=None):
    return [card for column in body["columns"] for card in column["cards"]
            if status is None or column["status"] == status]


def _keys(body, status=None):
    return {card["key"] for card in _cards(body, status)}


# ── список досок ────────────────────────────────────────────────────────

def test_boards_list_gives_own_subtree_only(org):
    body = _get("boards/").json()
    ids = {row["id"]: row for row in body["departments"]}
    assert body["personal"] is True
    assert set(ids) == {org.it.id, org.dev.id}
    assert ids[org.dev.id]["depth"] == 1 and ids[org.it.id]["source"] == "own"


def test_head_sees_managed_subtree_and_od_sees_all(org):
    head = {row["id"]: row["source"] for row in _get("boards/", HEAD_IT).json()["departments"]}
    assert head[org.it.id] == "managed" and head[org.dev.id] == "managed"
    assert head[org.hq.id] == "own"
    od = {row["id"] for row in _get("boards/", OD).json()["departments"]}
    assert {org.ops.id, org.itops.id} <= od


# ── личная доска ────────────────────────────────────────────────────────

def test_personal_board_shows_only_my_tasks_in_status_columns(org):
    mine = make_task(assignee_id=EMP_IT, status=Status.IN_PROGRESS)
    TaskAssignee.objects.create(task=mine, user_id=EMP_IT, role="primary")
    reported = make_task(reporter_id=EMP_IT, department_id=org.ops.id)
    watched = make_task(department_id=org.ops.id)
    TaskWatcher.objects.create(task=watched, user_id=EMP_IT)
    foreign = make_task(department_id=org.it.id)        # видна по отделу, но не моя

    body = _get("boards/personal").json()
    assert [column["status"] for column in body["columns"]] == list(board_service.COLUMN_ORDER)
    assert _keys(body) == {mine.key, reported.key, watched.key}
    assert foreign.key not in _keys(body)
    roles = {card["key"]: card["my_role"] for card in _cards(body)}
    assert roles == {mine.key: "assignee", reported.key: "reporter", watched.key: "watcher"}
    assert body["board"]["kind"] == "personal" and body["board"]["id"] is None


def test_personal_board_has_no_owner_parameter(org):
    """Чужую личную доску не открыть: у ручки нет пути с пользователем, а
    лишний параметр запроса ни на что не влияет (§5.4)."""
    foreign = make_task(assignee_id=OUTSIDER)
    TaskAssignee.objects.create(task=foreign, user_id=OUTSIDER, role="primary")
    body = _get("boards/personal", EMP_IT, user_id=OUTSIDER, owner=OUTSIDER).json()
    assert foreign.key not in _keys(body)


def test_card_shape(org):
    task = make_task(assignee_id=EMP_IT, description="Текст", due_date=timezone.localdate())
    TaskAssignee.objects.create(task=task, user_id=EMP_IT, role="primary")
    label = Label.objects.create(name="Срочно (доска)", color="#e11d48")
    task.labels.add(label)
    TaskComment.objects.create(task=task, author_id=EMP_IT, body="1")
    TaskComment.objects.create(task=task, author_id=EMP_IT, body="2")

    card = _cards(_get("boards/personal").json())[0]
    assert card["key"] == task.key
    assert card["labels"] == [{"id": label.id, "name": label.name, "color": "#e11d48"}]
    assert card["counts"]["comments"] == 2 and card["counts"]["attachments"] == 0
    assert card["has_description"] is True
    assert card["members"][0]["user_id"] == EMP_IT
    assert card["can_move"] is True


def test_is_new_only_until_seen(org):
    task = make_task(assignee_id=EMP_IT)
    TaskAssignee.objects.create(task=task, user_id=EMP_IT, role="primary", seen_at=None)
    assert _cards(_get("boards/personal").json())[0]["is_new"] is True
    assert _get("boards/personal", new="1").json()["columns"][1]["count"] == 1

    response = Client().post(f"{BASE}/tasks/{task.pk}/seen", **as_user(EMP_IT))
    assert response.status_code == 204
    assert _cards(_get("boards/personal").json())[0]["is_new"] is False


def test_seen_of_invisible_task_is_404(org):
    task = make_task(department_id=org.ops.id)
    assert Client().post(f"{BASE}/tasks/{task.pk}/seen", **as_user(EMP_IT)).status_code == 404


# ── доска отдела ────────────────────────────────────────────────────────

def test_department_board_takes_subtree_and_skips_prefix_trap(org):
    own = make_task(department_id=org.it.id)
    sub = make_task(department_id=org.dev.id)
    trap = make_task(department_id=org.itops.id)
    linked = make_task(department_id=org.ops.id)
    TaskDepartmentLink.objects.create(task=linked, department_id=org.it.id)
    sent = make_task(department_id=org.ops.id)
    TaskDepartmentLink.objects.create(task=sent, department_id=org.it.id,
                                      kind=DepartmentLinkKind.ORIGIN)

    body = _get(f"boards/departments/{org.it.id}").json()
    assert body["board"]["title"] == org.it.name
    relations = {card["key"]: card["relation"] for card in _cards(body)}
    assert relations == {own.key: "own", sub.key: "own", linked.key: "linked",
                         sent.key: "sent"}
    assert trap.key not in relations


def test_foreign_department_board_is_404_but_open_for_all_departments_holder(org):
    assert _get(f"boards/departments/{org.ops.id}").status_code == 404
    assert _get(f"boards/departments/{org.ops.id}", OD).status_code == 200
    assert _get("boards/departments/999999", OD).status_code == 404


def test_subdepartment_employee_does_not_open_parent_board(org):
    assert _get(f"boards/departments/{org.it.id}", EMP_DEV).status_code == 404
    assert _get(f"boards/departments/{org.dev.id}", EMP_DEV).status_code == 200


# ── доска проекта ───────────────────────────────────────────────────────

def test_project_board_visibility(org):
    """Доска проекта — ``Visible(u) & проект`` (§5.2): задачу своего отдела
    сотрудник видит, задачу без отдела — только участник или держатель
    «Доски задач проекта» (K-14)."""
    board = make_board("KB-P1", department=org.it)
    mine = make_task(project=board, department_id=org.it.id)
    hidden = make_task(project=board)
    body = _get(f"boards/projects/{board.pk}").json()
    assert body["board"]["kind"] == "project" and body["board"]["color"] == board.color
    assert _keys(body) == {mine.key}
    assert hidden.key in _keys(_get(f"boards/projects/{board.pk}", TD).json())
    assert _get(f"boards/projects/{board.pk}", OUTSIDER).status_code == 404


# ── настройки колонок ───────────────────────────────────────────────────

def _put_settings(path, body, user_id):
    return put_json(Client(), f"{BASE}/{path}", body, **as_user(user_id))


def test_head_names_colours_and_hides_columns(org):
    make_task(department_id=org.it.id, status=Status.CANCELLED)
    payload = {"columns": {
        "backlog": {"title": "Постановка задачи", "color": "purple"},
        "todo": {"title": "Ожидающие исполнения", "color": "yellow"},
        "cancelled": {"hidden": True},
    }}
    response = _put_settings(f"boards/departments/{org.it.id}/settings", payload, HEAD_IT)
    assert response.status_code == 200, response.content

    body = _get(f"boards/departments/{org.it.id}").json()
    columns = {column["status"]: column for column in body["columns"]}
    assert columns["backlog"]["title"] == "Постановка задачи"
    assert columns["todo"]["color"] == "yellow"
    assert columns["in_progress"]["title"] is None
    # Скрытая колонка отдаёт число, но не карточки.
    assert columns["cancelled"]["hidden"] is True
    assert columns["cancelled"]["count"] == 1 and columns["cancelled"]["cards"] == []
    assert body["can"]["admin"] is False                 # EMP_IT — не глава


def test_settings_need_board_admin(org):
    body = {"columns": {"todo": {"title": "Моя колонка"}}}
    assert _put_settings(f"boards/departments/{org.it.id}/settings", body,
                         EMP_IT).status_code == 403
    assert not BoardSettings.objects.exists()


@pytest.mark.parametrize("body", [
    {"columns": {"todo": {"color": "magenta"}}},
    {"columns": {"nope": {"title": "x"}}},
    {"columns": {status: {"hidden": True} for status in board_service.COLUMN_ORDER}},
])
def test_bad_settings_are_rejected(org, body):
    response = _put_settings("boards/personal/settings", body, EMP_IT)
    assert response.status_code == 422


def test_owner_sets_personal_board_columns(org):
    response = _put_settings("boards/personal/settings",
                             {"columns": {"done": {"title": "Готово", "color": "green"}}},
                             EMP_IT)
    assert response.status_code == 200
    columns = {column["status"]: column for column in _get("boards/personal").json()["columns"]}
    assert columns["done"]["title"] == "Готово"


# ── фильтры ─────────────────────────────────────────────────────────────

def test_filters(org):
    today = timezone.localdate()
    label = Label.objects.create(name="Фильтр (доска)")
    overdue = make_task(department_id=org.it.id, due_date=today - timedelta(days=2),
                        summary="Акт сверки")
    overdue.labels.add(label)
    mine = make_task(department_id=org.it.id, assignee_id=EMP_IT)
    TaskAssignee.objects.create(task=mine, user_id=EMP_IT, role="primary")
    nobody = make_task(department_id=org.it.id)
    done = make_task(department_id=org.it.id, status=Status.DONE, completed_at=timezone.now())
    old_done = make_task(department_id=org.it.id, status=Status.DONE,
                         completed_at=timezone.now() - timedelta(days=60))
    path = f"boards/departments/{org.it.id}"

    assert _keys(_get(path, q="сверки").json()) == {overdue.key}
    assert _keys(_get(path, label=str(label.id)).json()) == {overdue.key}
    assert mine.key in _keys(_get(path, label="none").json())
    assert _keys(_get(path, member="me").json()) == {mine.key}
    assert nobody.key in _keys(_get(path, member="none").json())
    assert mine.key not in _keys(_get(path, member="none").json())
    assert _keys(_get(path, due="overdue").json()) == {overdue.key}
    assert _keys(_get(path, completion="complete").json()) == {done.key}
    # Завершённые старше 30 дней по умолчанию не показываются (K-26).
    assert old_done.key not in _keys(_get(path).json())
    assert old_done.key in _keys(_get(path, done_days="0").json())


def test_column_paging(org, monkeypatch):
    monkeypatch.setattr(board_service, "COLUMN_LIMIT", 2)
    tasks = [make_task(department_id=org.it.id) for _ in range(3)]
    body = _get(f"boards/departments/{org.it.id}").json()
    todo = next(column for column in body["columns"] if column["status"] == "todo")
    assert len(todo["cards"]) == 2 and todo["has_more"] is True and todo["count"] == 3
    rest = _get(f"boards/departments/{org.it.id}", status="todo", offset="2").json()
    assert [column["status"] for column in rest["columns"]] == ["todo"]
    assert len(rest["columns"][0]["cards"]) == 1
    seen = {card["key"] for card in todo["cards"]} | _keys(rest)
    assert seen == {task.key for task in tasks}


def test_board_query_count_does_not_grow_with_cards(org, django_assert_max_num_queries):
    for index in range(12):
        task = make_task(department_id=org.it.id, assignee_id=EMP_IT,
                         status=board_service.COLUMN_ORDER[index % 5])
        TaskAssignee.objects.create(task=task, user_id=EMP_IT, role="primary")
        task.labels.add(Label.objects.get_or_create(name=f"Метка {index % 3}")[0])
    client = Client()
    headers = as_user(EMP_IT)
    client.get(f"{BASE}/boards/departments/{org.it.id}", **headers)   # прогрев кэшей
    with django_assert_max_num_queries(30):
        response = client.get(f"{BASE}/boards/departments/{org.it.id}", **headers)
    assert response.status_code == 200
    assert len(_cards(response.json())) == 12
