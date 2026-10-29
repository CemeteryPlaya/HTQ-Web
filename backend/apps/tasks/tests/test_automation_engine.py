"""Движок автоматизации досок (решения K-36…K-38, этап S4).

Правила домашних досок задачи срабатывают на событиях её правки, в той же
транзакции; правила запускают друг друга, как в Trello, но с пределами:
одно правило — раз на задачу за цепочку, глубина до 5, не больше 50
действий. Сбой правила откатывает только его. «Запретить перенос» — 409 на
ручной перенос, автоматизацию не останавливает.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client

from apps.notifications.models import Notification
from apps.tasks import schemas
from apps.tasks.models import (AutomationRun, BoardKind, Status, Task, TaskAccessRequest,
                               TaskComment, TaskFieldValue)
from apps.tasks.services import access_requests, board_fields, board_service, checklist_service
from apps.tasks.services import task_content_service, task_service
from apps.tasks.services.automation import context

from .automation_helpers import add_rule, assigned_task, dept_board, journal, label, statuses
from .helpers import BASE, patch_json, post_json
from .org_fixtures import EMP_DEV, EMP_IT, HEAD_IT, as_user, make_board, make_org, make_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _status(task, status, user=EMP_IT):
    task_service.update_task(task.pk, schemas.TaskUpdate(status=status), user_id=user)
    task.refresh_from_db()


def _labels(task) -> set[str]:
    return set(task.labels.values_list("name", flat=True))


# ── срабатывание и журнал ───────────────────────────────────────────────

def test_rule_runs_on_move_and_marks_journal(org):
    urgent = label("Срочно (автоматизация)")
    rule = add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
                    [{"type": "add_label", "label_id": urgent.pk}], name="В работе — срочно")
    task = assigned_task(org.it, EMP_IT)
    _status(task, Status.IN_PROGRESS)
    assert _labels(task) == {urgent.name}
    assert statuses(rule) == ["ok"]
    # Правка автоматизации подписана в журнале задачи.
    feed = Client().get(f"{BASE}/tasks/{task.pk}/feed", {"details": "1"}, **as_user(EMP_IT)).json()
    status_row = next(item for item in feed["items"] if item.get("field") == "status")
    assert status_row["automation"] is None and status_row["actor"]["id"] == EMP_IT


def test_conditions_no_match_is_logged(org):
    rule = add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
                    [{"type": "complete"}], [{"type": "has_due"}])
    task = assigned_task(org.it, EMP_IT)
    _status(task, Status.IN_PROGRESS)
    assert task.status == Status.IN_PROGRESS
    assert statuses(rule) == ["no_match"]


def test_disabled_rule_and_other_trigger_do_nothing(org):
    rule = add_rule(dept_board(org.it), {"type": "moved", "to_status": "done"},
                    [{"type": "cancel"}], enabled=False)
    other = add_rule(dept_board(org.it), {"type": "due_set"}, [{"type": "cancel"}])
    task = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS)
    _status(task, Status.DONE)
    assert task.status == Status.DONE
    assert statuses(rule) == [] and statuses(other) == []


def test_failed_rule_rolls_back_only_itself(org):
    urgent = label("Срочно (откат)")
    marker = label("Метка-триггер (откат)")
    # Колонку триггер не задаёт — сохранение не знает, что перенос невозможен;
    # из «В работе» в «Бэклог» схема статусов не пускает уже на месте.
    broken = add_rule(dept_board(org.it), {"type": "label_added", "label_id": marker.pk},
                      [{"type": "add_label", "label_id": urgent.pk},
                       {"type": "move", "status": "backlog"}])
    task = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS)
    task_service.update_task(task.pk, schemas.TaskUpdate(label_ids=[marker.pk]), user_id=EMP_IT)
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS            # правка человека осталась
    assert _labels(task) == {marker.name}               # метка правила откатилась
    run = AutomationRun.objects.get(rule=broken, status="failed")
    assert "перенести нельзя" in run.details["error"]


# ── домашние доски ──────────────────────────────────────────────────────

def test_parent_board_rules_do_not_apply_to_subtree(org):
    urgent = label("Срочно (поддерево)")
    add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
             [{"type": "add_label", "label_id": urgent.pk}])
    sub = assigned_task(org.dev, EMP_DEV)
    _status(sub, Status.IN_PROGRESS, user=EMP_DEV)
    assert _labels(sub) == set()


def test_project_board_rules_apply_to_project_tasks(org):
    board = make_board("KB-AUT1", department=org.it)
    urgent = label("Срочно (проект)")
    add_rule(board_service.board_for(BoardKind.PROJECT, board.pk),
             {"type": "moved", "to_status": "in_progress"},
             [{"type": "add_label", "label_id": urgent.pk}])
    task = assigned_task(org.it, EMP_IT, project=board)
    _status(task, Status.IN_PROGRESS)
    assert _labels(task) == {urgent.name}


# ── цепочки и пределы ───────────────────────────────────────────────────

def test_rules_trigger_each_other(org):
    first = label("Цепочка 1")
    board = dept_board(org.it)
    add_rule(board, {"type": "moved", "to_status": "in_progress"},
             [{"type": "add_label", "label_id": first.pk}])
    second = add_rule(board, {"type": "label_added", "label_id": first.pk},
                      [{"type": "comment", "text": "Метка «{cardname}» поставлена"}])
    task = assigned_task(org.it, EMP_IT, summary="Смета")
    _status(task, Status.IN_PROGRESS)
    assert statuses(second) == ["ok"]
    comment = TaskComment.objects.get(task=task)
    assert comment.author_id is None and comment.body == "Метка «Смета» поставлена"


def test_ping_pong_stops_once_per_rule(org):
    board = dept_board(org.it)
    forth = add_rule(board, {"type": "moved", "to_status": "in_progress"},
                     [{"type": "move", "status": "todo"}])
    back = add_rule(board, {"type": "moved", "to_status": "todo"},
                    [{"type": "move", "status": "in_progress"}])
    task = assigned_task(org.it, EMP_IT)
    _status(task, Status.IN_PROGRESS)
    # Человек — в «В работе», правило — назад, второе — снова вперёд; дальше
    # первое уже выполнено в этой цепочке и молчит.
    assert task.status == Status.IN_PROGRESS
    assert statuses(forth) == ["ok"] and statuses(back) == ["ok"]


def test_depth_limit_is_logged(org):
    board = dept_board(org.it)
    marks = [label(f"Глубина {index}") for index in range(8)]
    add_rule(board, {"type": "moved", "to_status": "in_progress"},
             [{"type": "add_label", "label_id": marks[0].pk}])
    chain = [add_rule(board, {"type": "label_added", "label_id": marks[index].pk},
                      [{"type": "add_label", "label_id": marks[index + 1].pk}])
             for index in range(7)]
    task = assigned_task(org.it, EMP_IT)
    _status(task, Status.IN_PROGRESS)
    # Событие человека — глубина 0; правило на глубине 5 ещё выполняется,
    # следующее упирается в предел.
    done = [statuses(rule) for rule in chain]
    assert done[:5] == [["ok"]] * 5
    assert done[5] == ["limited"] and done[6] == []
    assert len(_labels(task)) == 6


def test_action_budget_is_per_chain(org, monkeypatch):
    monkeypatch.setattr(context, "MAX_ACTIONS", 2)
    board = dept_board(org.it)
    one, two = label("Бюджет 1"), label("Бюджет 2")
    first = add_rule(board, {"type": "moved", "to_status": "in_progress"},
                     [{"type": "add_label", "label_id": one.pk},
                      {"type": "add_label", "label_id": two.pk}])
    second = add_rule(board, {"type": "label_added"}, [{"type": "complete"}])
    task = assigned_task(org.it, EMP_IT)
    _status(task, Status.IN_PROGRESS)
    assert statuses(first) == ["ok"]
    assert set(statuses(second)) == {"limited"}
    assert task.status == Status.IN_PROGRESS


# ── события ─────────────────────────────────────────────────────────────

def test_creation_with_crew_and_due_fires_their_triggers(org):
    board = dept_board(org.it)
    created = add_rule(board, {"type": "card_created", "status": "backlog"},
                       [{"type": "add_checklist", "title": "Приёмка"}])
    assigned = add_rule(board, {"type": "assignee_added", "user_id": EMP_IT},
                        [{"type": "move", "status": "todo"}], [{"type": "has_due"}])
    task = task_service.create_task(schemas.TaskCreate(
        summary="Новая", status=Status.BACKLOG, department_id=org.it.id, assignee_id=EMP_IT,
        due_date="2031-01-10"), user_id=HEAD_IT)
    task.refresh_from_db()
    assert statuses(created) == ["ok"] and statuses(assigned) == ["ok"]
    assert task.status == Status.TODO
    assert task.checklists.get().title == "Приёмка"


def test_due_label_comment_and_checklist_events(org):
    board = dept_board(org.it)
    urgent = label("Срочно (события)")
    due_changed = add_rule(board, {"type": "due_changed"}, [{"type": "add_label",
                                                              "label_id": urgent.pk}])
    removed = add_rule(board, {"type": "label_removed", "label_id": urgent.pk},
                       [{"type": "set_start_today"}])
    commented = add_rule(board, {"type": "comment_added", "match": "starts_with",
                                 "text": "срочно"}, [{"type": "reposition"}])
    done = add_rule(board, {"type": "checklist_completed", "title": "Приёмка"},
                    [{"type": "comment", "text": "Приёмка закрыта"}])
    item_rule = add_rule(board, {"type": "item_checked", "text": "Подписать акт"},
                         [{"type": "add_item", "checklist_title": "Итог", "text": "Сдать"}])
    task = assigned_task(org.it, EMP_IT, due_date="2031-01-10")
    task_service.update_task(task.pk, schemas.TaskUpdate(due_date="2031-01-12"), user_id=EMP_IT)
    assert statuses(due_changed) == ["ok"]
    task_service.update_task(task.pk, schemas.TaskUpdate(label_ids=[]), user_id=EMP_IT)
    assert statuses(removed) == ["ok"]
    task_content_service.create_comment(task.pk, "Срочно посмотрите", author_id=EMP_IT)
    assert statuses(commented) == ["ok"]
    checklist = checklist_service.add_checklist(task, "Приёмка", ["Подписать акт"], EMP_IT)
    item = checklist.items.get()
    checklist_service.set_item_done(task, item, True, EMP_IT)
    assert statuses(item_rule) == ["ok"] and statuses(done) == ["ok"]
    assert task.checklists.get(title="Итог").items.get().text == "Сдать"


def test_field_triggers(org):
    board = dept_board(org.it)
    reason = board_fields.BoardField.objects.create(
        board_kind="department", board_id=org.it.id, name="Причина", field_type="text",
        position="V")
    volume = board_fields.BoardField.objects.create(
        board_kind="department", board_id=org.it.id, name="Объём", field_type="number",
        position="k")
    set_rule = add_rule(board, {"type": "field_changed", "field_id": reason.pk, "op": "set"},
                        [{"type": "move", "status": "blocked"}])
    cleared = add_rule(board, {"type": "field_changed", "field_id": reason.pk, "op": "cleared"},
                       [{"type": "move", "status": "in_progress"}])
    big = add_rule(board, {"type": "field_changed", "field_id": volume.pk, "op": "gt",
                           "value": 100}, [{"type": "comment", "text": "Большой объём"}])
    filled = add_rule(board, {"type": "fields_filled"}, [{"type": "watch_actor"}])
    task = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS)
    board_fields.store_value(task, reason, "Ждём смету", EMP_IT)
    task.refresh_from_db()
    assert task.status == Status.BLOCKED and statuses(set_rule) == ["ok"]
    board_fields.store_value(task, volume, board_fields.parse_value(volume, "50"), EMP_IT)
    assert statuses(big) == ["no_match"] or statuses(big) == []
    assert statuses(filled) == ["ok"]                   # последнее пустое поле заполнено
    board_fields.store_value(task, volume, board_fields.parse_value(volume, "150"), EMP_IT)
    assert "ok" in statuses(big)
    board_fields.store_value(task, reason, None, EMP_IT)
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS and statuses(cleared) == ["ok"]
    assert TaskFieldValue.objects.filter(task=task).count() == 1


def test_column_count_trigger(org):
    board = dept_board(org.it)
    crowded = add_rule(board, {"type": "column_count", "status": "in_progress", "op": "gt",
                               "count": 1}, [{"type": "comment", "text": "Много в работе"}])
    first = assigned_task(org.it, EMP_IT)
    second = assigned_task(org.it, EMP_IT)
    _status(first, Status.IN_PROGRESS)
    assert statuses(crowded) == []
    _status(second, Status.IN_PROGRESS)
    assert statuses(crowded) == ["ok"]


# ── условия ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("condition", "matches"), [
    ({"type": "assigned", "who": "only_user", "user_id": EMP_IT}, True),
    ({"type": "assigned", "who": "nobody"}, False),
    ({"type": "has_checklist", "title": "Приёмка", "negate": True}, False),
    ({"type": "checklists_incomplete"}, True),
    ({"type": "checklists_complete"}, False),
    ({"type": "title", "match": "starts_with", "text": "смета"}, True),
    ({"type": "description", "match": "empty"}, True),
    ({"type": "due_window", "window": "overdue"}, True),
    ({"type": "in_column", "status": "todo", "negate": True}, True),
    ({"type": "actor", "op": "is", "user_id": EMP_IT}, True),
    ({"type": "actor", "op": "automation"}, False),
])
def test_conditions(org, condition, matches):
    task = assigned_task(org.it, EMP_IT, summary="Смета объекта", due_date="2020-01-01")
    checklist_service.add_checklist(task, "Приёмка", ["Проверить"], EMP_IT)
    rule = add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
                    [{"type": "watch_actor"}], [condition])
    _status(task, Status.IN_PROGRESS)
    assert statuses(rule) == (["ok"] if matches else ["no_match"])


# ── запрет ручного переноса (K-38) ──────────────────────────────────────

def test_block_rejects_manual_move_and_is_logged(org):
    rule = add_rule(dept_board(org.it), {"type": "moved", "from_status": "todo",
                                         "to_status": "in_progress"},
                    [{"type": "block", "message": "Сначала возьмите задачу в работу"}],
                    name="Запрет")
    task = assigned_task(org.it, EMP_IT)
    response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"status": "in_progress"},
                          **as_user(EMP_IT))
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "automation_blocked"
    assert body["detail"] == "Сначала возьмите задачу в работу"
    assert body["details"]["rule_name"] == "Запрет"
    task.refresh_from_db()
    assert task.status == Status.TODO
    assert statuses(rule) == ["blocked"]
    # Перенос на доске — то же.
    moved = post_json(Client(), f"{BASE}/tasks/{task.pk}/move",
                      {"board": {"kind": "department", "id": org.it.id}, "status": "in_progress"},
                      **as_user(EMP_IT))
    assert moved.status_code == 409 and moved.json()["code"] == "automation_blocked"


def test_block_does_not_stop_automation(org):
    board = dept_board(org.it)
    add_rule(board, {"type": "moved", "from_status": "todo", "to_status": "in_progress"},
             [{"type": "block", "message": "Нельзя"}])
    mover = add_rule(board, {"type": "label_added"}, [{"type": "move", "status": "in_progress"}])
    task = assigned_task(org.it, EMP_IT)
    task_service.update_task(task.pk, schemas.TaskUpdate(label_ids=[label("Пуск").pk]),
                             user_id=EMP_IT)
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS and statuses(mover) == ["ok"]


def test_block_does_not_hold_claim(org):
    """«Взять в работу» — шаг процесса, как кнопка (решение L-02): запрет
    держит только ручной перенос между колонками."""
    add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
             [{"type": "block", "message": "Вручную не переносить"}])
    task = make_task(department_id=org.it.id, status=Status.TODO)
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/claim", {}, **as_user(EMP_IT))
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.assignee_id == EMP_IT and task.status == Status.IN_PROGRESS
    other = make_task(department_id=org.it.id, status=Status.TODO, assignee_id=EMP_IT)
    moved = patch_json(Client(), f"{BASE}/tasks/{other.pk}/", {"status": "in_progress"},
                       **as_user(EMP_IT))
    assert moved.status_code == 409 and moved.json()["detail"] == "Вручную не переносить"


def test_automation_journal_rows_carry_the_rule(org):
    rule = add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
                    [{"type": "set_start_today"}], name="Начало — сегодня")
    task = assigned_task(org.it, EMP_IT)
    _status(task, Status.IN_PROGRESS)
    rows = journal(task, "start_date")
    assert len(rows) == 1 and rows[0][2] == rule.pk
    feed = Client().get(f"{BASE}/tasks/{task.pk}/feed", {"details": "1"}, **as_user(EMP_IT)).json()
    start = next(item for item in feed["items"] if item.get("field") == "start_date")
    assert start["automation"] == {"id": rule.pk, "name": "Начало — сегодня"}
    assert start["actor"] is None


# ── уведомления ─────────────────────────────────────────────────────────

def _notified(user_id: int, title: str) -> bool:
    return Notification.objects.filter(recipient_id=user_id, title__startswith=title).exists()


def test_chain_initiator_is_not_notified_about_automation_changes(org):
    """Правки автоматизации — от «Автоматизации», но зачинщик цепочки о них не
    узнаёт уведомлением (результат у него на экране), и на втором шаге
    цепочки тоже; прочие участники узнают."""
    urgent = label("Срочно (уведомления)")
    add_rule(dept_board(org.it), {"type": "label_added", "label_id": urgent.pk},
             [{"type": "move", "status": "in_progress"}], name="Срочно — в работу")
    add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
             [{"type": "comment", "text": "@card Взята в работу"}], name="В работе — комментарий")
    task = assigned_task(org.it, EMP_IT)                  # автор — HEAD_IT
    task_service.update_task(task.pk, schemas.TaskUpdate(label_ids=[urgent.pk]), user_id=EMP_IT)
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS
    assert TaskComment.objects.filter(task=task, body="Взята в работу").exists()
    for title in ("Статус", "Новый комментарий"):
        assert _notified(HEAD_IT, title), title
        assert not _notified(EMP_IT, title), title


# ── логика S4b (спецификация docs/plans/2026-10-28-kanban-automation-logic.md) ─

def _mark(board, trigger: dict, name: str, conditions=None):
    """Правило «событие → метка с названием правила» — по ней видно, что сработало."""
    tag = label(f"Метка: {name}")
    add_rule(board, trigger, [{"type": "add_label", "label_id": tag.pk}], conditions, name=name)
    return tag


def test_transfer_arrives_on_the_new_board_and_does_not_recreate_on_the_project(org):
    project = make_board("S4B-T")
    project_board = board_service.board_for(BoardKind.PROJECT, project.pk)
    created_on_project = _mark(project_board, {"type": "card_created"}, "Создана (проект)")
    arrived = _mark(dept_board(org.ops), {"type": "card_created", "how": "arrived"},
                    "Пришла (эксплуатация)")
    not_here = _mark(dept_board(org.it), {"type": "card_created", "how": "arrived"},
                     "Пришла (ИТ)")
    task = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS, project_id=project.pk)
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/transfer",
                         {"department_id": org.ops.id}, **as_user(HEAD_IT))
    assert response.status_code == 200, response.content
    names = _labels(task)
    assert arrived.name in names
    assert created_on_project.name not in names and not_here.name not in names
    statuses_moved = journal(task, "status")
    assert statuses_moved[-1][:2] == (Status.IN_PROGRESS, Status.TODO)


def test_changing_department_in_the_form_arrives_on_the_new_board(org):
    arrived = _mark(dept_board(org.dev), {"type": "card_created", "how": "any"},
                    "Появилась (разработка)")
    task = assigned_task(org.it, EMP_IT)
    response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/",
                          {"department_id": org.dev.id}, **as_user(HEAD_IT))
    assert response.status_code == 200, response.content
    assert arrived.name in _labels(task)


def test_access_approval_and_creation_give_people_events(org):
    joined = _mark(dept_board(org.it), {"type": "assignee_added", "user_id": EMP_DEV},
                   "Добавлен разработчик")
    supervised = _mark(dept_board(org.it), {"type": "supervisor_set"}, "Назначен руководитель")
    created = task_service.create_task(
        schemas.TaskCreate(summary="С руководителем", department_id=org.it.id,
                           reporter_id=HEAD_IT, supervisor_id=HEAD_IT),
        user_id=HEAD_IT, scope=None)
    assert supervised.name in _labels(created)
    task = assigned_task(org.it, EMP_IT)
    row = TaskAccessRequest.objects.create(task=task, requester_id=EMP_DEV, kind="execute")
    access_requests._make_executor(task, row, HEAD_IT)
    assert joined.name in _labels(task)


def test_column_count_fires_when_the_threshold_is_crossed(org):
    crowded = _mark(dept_board(org.it), {"type": "column_count", "status": "in_progress",
                                         "op": "gt", "count": 1}, "В работе больше одной")
    first, second, third = (assigned_task(org.it, EMP_IT) for _ in range(3))
    for task in (first, second, third):
        _status(task, Status.IN_PROGRESS)
    assert [crowded.name in _labels(task) for task in (first, second, third)] == [
        False, True, False]


def test_no_match_is_logged_once_per_rule_and_task(org):
    rule = add_rule(dept_board(org.it), {"type": "label_added"}, [{"type": "set_start_today"}],
                    [{"type": "in_column", "status": "done"}], name="Метка в «Готово»")
    task = assigned_task(org.it, EMP_IT)
    tags = [label(f"Пачка {index}").pk for index in range(3)]
    task_service.update_task(task.pk, schemas.TaskUpdate(label_ids=tags), user_id=EMP_IT)
    assert statuses(rule) == ["no_match"]


def test_rules_that_create_tasks_do_not_multiply(org):
    add_rule(dept_board(org.it), {"type": "card_created"},
             [{"type": "create_task", "summary": "Отчёт к «{cardname}»"}], name="Отчёт")
    before = Task.objects.count()
    task_service.create_task(schemas.TaskCreate(summary="Исходная", department_id=org.it.id,
                                                reporter_id=EMP_IT), user_id=EMP_IT, scope=None)
    assert Task.objects.count() == before + 2         # исходная и одна созданная правилом


def test_two_creating_rules_stop_at_the_chain_limit(org):
    for name in ("Первая", "Вторая"):
        add_rule(dept_board(org.it), {"type": "card_created"},
                 [{"type": "create_task", "summary": name}], name=name)
    before = Task.objects.count()
    task_service.create_task(schemas.TaskCreate(summary="Исходная", department_id=org.it.id,
                                                reporter_id=EMP_IT), user_id=EMP_IT, scope=None)
    assert Task.objects.count() - before <= 1 + context.MAX_CREATED
    assert AutomationRun.objects.filter(status="limited").exists()


def test_dates_out_of_order_is_a_readable_rule_error(org):
    rule = add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
                    [{"type": "set_due", "mode": "today"}], name="Срок — сегодня")
    task = assigned_task(org.it, EMP_IT, start_date=context.today() + timedelta(days=5))
    _status(task, Status.IN_PROGRESS)
    run = AutomationRun.objects.get(rule=rule, status="failed")
    assert run.details["error"] != "Внутренняя ошибка правила"


def test_rule_placement_beats_the_drag(org):
    add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
             [{"type": "reposition", "position": "top"}], name="Наверх")
    board = {"kind": "department", "id": org.it.id}
    tasks = [assigned_task(org.it, EMP_IT) for _ in range(3)]
    for task in tasks[:2]:
        response = post_json(Client(), f"{BASE}/tasks/{task.pk}/move",
                             {"board": board, "status": "in_progress"}, **as_user(EMP_IT))
        assert response.status_code == 200, response.content
    # Тащат в самый низ колонки — правило ставит наверх, и правило сильнее.
    response = post_json(Client(), f"{BASE}/tasks/{tasks[2].pk}/move",
                         {"board": board, "status": "in_progress", "before_id": tasks[0].pk},
                         **as_user(EMP_IT))
    assert response.status_code == 200, response.content
    body = Client().get(f"{BASE}/boards/departments/{org.it.id}", **as_user(EMP_IT)).json()
    column = next(item for item in body["columns"] if item["status"] == "in_progress")
    assert column["cards"][0]["id"] == tasks[2].pk


def test_blocks_hold_the_post_edit_boards_and_check_transitions_first(org):
    add_rule(dept_board(org.dev), {"type": "moved", "to_status": "in_progress"},
             [{"type": "block", "message": "Разработка — только кнопкой"}], name="Запрет")
    task = assigned_task(org.it, EMP_IT)
    # Тем же PATCH задача уходит в «Разработку» — держит запрет её доски.
    response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/",
                          {"department_id": org.dev.id, "status": "in_progress"},
                          **as_user(HEAD_IT))
    assert response.status_code == 409, response.content
    # Недопустимый переход — 400 раньше запрета.
    done = assigned_task(org.dev, EMP_IT, status=Status.DONE)
    add_rule(dept_board(org.dev), {"type": "moved", "to_status": "todo"},
             [{"type": "block", "message": "Не нужен"}], name="Запрет 2")
    assert patch_json(Client(), f"{BASE}/tasks/{done.pk}/", {"status": "todo"},
                      **as_user(HEAD_IT)).status_code == 400
