"""Действия автоматизации и кнопки (этап S4).

Действия проверяются кнопкой на карточке: её нажимает тот, кто ведёт
задачу, действия идут от его имени без проверки прав. Кнопка на доске — тем,
кто создаёт задачи на доске; без колонки — действия уровня доски.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client

from apps.notifications.models import Notification
from apps.tasks.models import (AutomationKind, AutomationRule, BoardCardRank, BoardField,
                               BoardSettings, Status, Task, TaskAssignee, TaskChecklist,
                               TaskComment, TaskWatcher)
from apps.tasks.services import board_fields, board_service, checklist_service
from apps.tasks.services.automation import actions, context

from .automation_helpers import add_rule, assigned_task, dept_board, label, members
from .helpers import BASE, post_json
from .org_fixtures import EMP_DEV, EMP_IT, HEAD_IT, OUTSIDER, as_user, make_org, make_task

pytestmark = pytest.mark.django_db

BUTTON = {"type": "card_button"}


@pytest.fixture
def org():
    made = make_org()
    members(EMP_IT, EMP_DEV, HEAD_IT)
    return made


def _button(org, button_actions, conditions=None, name="Кнопка"):
    return add_rule(dept_board(org.it), BUTTON, button_actions, conditions,
                    kind=AutomationKind.CARD_BUTTON, name=name)


def _press(task, rule, who=EMP_IT):
    return post_json(Client(), f"{BASE}/tasks/{task.pk}/buttons/{rule.pk}", {}, **as_user(who))


def _ok(task, rule, who=EMP_IT):
    response = _press(task, rule, who)
    assert response.status_code == 200, response.content
    task.refresh_from_db()
    return task


# ── кнопка на карточке: права и отказы ─────────────────────────────────

def test_card_button_rights(org):
    rule = _button(org, [{"type": "complete"}])
    task = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS)
    assert _press(task, rule, who=OUTSIDER).status_code == 404       # задачу не видит
    viewer_task = make_task(department_id=org.it.id, status=Status.IN_PROGRESS)
    assert _press(viewer_task, rule, who=EMP_IT).status_code == 403  # видит, но не ведёт
    rule.enabled = False
    rule.save()
    assert _press(task, rule).status_code == 404
    rule.enabled = True
    rule.save()
    assert _ok(task, rule).status == Status.DONE


def test_button_of_another_board_is_404(org):
    rule = add_rule(dept_board(org.ops), BUTTON, [{"type": "complete"}],
                    kind=AutomationKind.CARD_BUTTON, name="Чужая")
    task = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS)
    assert _press(task, rule).status_code == 404


def test_failed_and_inapplicable_button_explain(org):
    broken = _button(org, [{"type": "move", "status": "backlog"}])
    task = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS)
    response = _press(task, broken)
    assert response.status_code == 422 and "перенести нельзя" in response.json()["detail"]
    picky = _button(org, [{"type": "complete"}], [{"type": "has_due"}], name="Только со сроком")
    response = _press(task, picky)
    assert response.status_code == 409 and response.json()["code"] == "automation_not_applicable"


# ── перемещение ─────────────────────────────────────────────────────────

def test_move_top_and_bottom_of_column(org):
    board = dept_board(org.it)
    others = [assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS) for _ in range(2)]
    for task in others:
        board_service.place_new(board, task)
    task = assigned_task(org.it, EMP_IT, status=Status.TODO)
    _ok(task, _button(org, [{"type": "move", "status": "in_progress", "position": "top"}]))
    order = [pk for pk, _rank in board_service._column(board, Status.IN_PROGRESS)]
    assert order[0] == task.pk
    _ok(task, _button(org, [{"type": "reposition", "position": "bottom"}], name="Вниз"))
    order = [pk for pk, _rank in board_service._column(board, Status.IN_PROGRESS)]
    assert order[-1] == task.pk
    assert BoardCardRank.objects.filter(task=task).count() == 1


def test_cancel(org):
    task = assigned_task(org.it, EMP_IT)
    assert _ok(task, _button(org, [{"type": "cancel"}])).status == Status.CANCELLED


# ── метки ───────────────────────────────────────────────────────────────

def test_labels(org):
    one, two = label("Метка 1 (действия)"), label("Метка 2 (действия)")
    task = assigned_task(org.it, EMP_IT)
    _ok(task, _button(org, [{"type": "add_label", "label_id": one.pk},
                            {"type": "add_label", "label_id": two.pk}]))
    assert set(task.labels.values_list("pk", flat=True)) == {one.pk, two.pk}
    _ok(task, _button(org, [{"type": "remove_label", "label_id": one.pk}], name="Снять"))
    assert set(task.labels.values_list("pk", flat=True)) == {two.pk}
    _ok(task, _button(org, [{"type": "remove_all_labels"}], name="Снять все"))
    assert not task.labels.exists()


# ── задачи ──────────────────────────────────────────────────────────────

def test_create_and_copy_task(org):
    urgent = label("Срочно (копия)")
    task = assigned_task(org.it, EMP_IT, summary="Смета", description="Подробно")
    task.labels.add(urgent)
    checklist = checklist_service.add_checklist(task, "Приёмка", ["Проверить", "Сдать"], EMP_IT)
    checklist_service.set_item_done(task, checklist.items.first(), True, EMP_IT)
    _ok(task, _button(org, [{"type": "create_task", "summary": "Проверка: {cardname}",
                             "status": "backlog"},
                            {"type": "copy_task", "summary": "{cardname} (копия)"}]))
    created = Task.objects.get(summary="Проверка: Смета")
    assert created.status == Status.BACKLOG and created.department_id == org.it.id
    assert created.reporter_id == EMP_IT
    copy = Task.objects.get(summary="Смета (копия)")
    assert copy.description == "Подробно" and set(copy.labels.all()) == {urgent}
    items = list(TaskChecklist.objects.get(task=copy).items.order_by("position")
                 .values_list("text", "is_done"))
    assert items == [("Проверить", False), ("Сдать", False)]
    assert BoardCardRank.objects.filter(task=created, board_id=org.it.id).exists()


# ── даты ────────────────────────────────────────────────────────────────

def test_dates(org):
    today = context.today()
    when = BoardField.objects.create(board_kind="department", board_id=org.it.id, name="Когда",
                                     field_type="date", position="V")
    task = assigned_task(org.it, EMP_IT)
    _ok(task, _button(org, [{"type": "set_due", "mode": "in_days", "days": 3}]))
    assert task.due_date == today + timedelta(days=3)
    _ok(task, _button(org, [{"type": "set_due", "mode": "in_days", "days": 1, "working": True}],
                      name="Рабочий"))
    assert task.due_date == actions._add_days(today, 1, True) and task.due_date > today
    _ok(task, _button(org, [{"type": "shift_due", "days": -1}], name="Сдвиг"))
    assert task.due_date == actions._add_days(today, 1, True) - timedelta(days=1)
    board_fields.store_value(task, when, today + timedelta(days=9), EMP_IT)
    _ok(task, _button(org, [{"type": "set_due", "mode": "field", "field_id": when.pk}],
                      name="Из поля"))
    assert task.due_date == today + timedelta(days=9)
    _ok(task, _button(org, [{"type": "set_start_today"}], name="Начало"))
    assert task.start_date == today
    _ok(task, _button(org, [{"type": "clear_due"}, {"type": "clear_start"}], name="Убрать"))
    assert task.due_date is None and task.start_date is None
    response = _press(task, _button(org, [{"type": "shift_due", "days": 2}], name="Нечего"))
    assert response.status_code == 422 and "нет срока" in response.json()["detail"]


# ── чек-листы ───────────────────────────────────────────────────────────

def test_checklists(org):
    BoardSettings.objects.create(board_kind="department", board_id=org.it.id,
                                 checklist_templates=[{"id": "t1", "title": "Чек-лист",
                                                       "items": ["Выполнить", "Сдать"]}])
    task = assigned_task(org.it, EMP_IT)
    _ok(task, _button(org, [{"type": "add_checklist", "title": "Чек-лист", "template_id": "t1"},
                            {"type": "add_item", "checklist_title": "Итог", "text": "Отчёт"},
                            {"type": "check_item", "text": "выполнить"}]))
    lists = {row.title: list(row.items.order_by("position").values_list("text", "is_done"))
             for row in TaskChecklist.objects.filter(task=task)}
    assert lists == {"Чек-лист": [("Выполнить", True), ("Сдать", False)],
                     "Итог": [("Отчёт", False)]}
    _ok(task, _button(org, [{"type": "check_all"}], name="Все"))
    assert not checklist_service.TaskChecklistItem.objects.filter(
        checklist__task=task, is_done=False).exists()
    _ok(task, _button(org, [{"type": "reset_all"}, {"type": "uncheck_item", "text": "Нет"},
                            {"type": "remove_item", "text": "Отчёт"}], name="Сброс"))
    items = checklist_service.TaskChecklistItem.objects.filter(checklist__task=task)
    assert not items.filter(is_done=True).exists() and not items.filter(text="Отчёт").exists()


# ── участники ───────────────────────────────────────────────────────────

def _crew(task) -> set[int]:
    return set(TaskAssignee.objects.filter(task=task).values_list("user_id", flat=True))


def test_members(org):
    task = make_task(department_id=org.it.id, reporter_id=EMP_IT)       # EMP_IT — автор
    _ok(task, _button(org, [{"type": "join_actor"}, {"type": "add_assignee", "user_id": EMP_DEV},
                            {"type": "set_supervisor", "who": "actor"},
                            {"type": "watch_actor"}]))
    assert _crew(task) == {EMP_IT, EMP_DEV} and task.assignee_id == EMP_IT
    assert task.supervisor_id == EMP_IT
    assert TaskWatcher.objects.filter(task=task, user_id=EMP_IT).exists()
    _ok(task, _button(org, [{"type": "remove_assignee", "user_id": EMP_DEV}], name="Снять"))
    assert _crew(task) == {EMP_IT}
    _ok(task, _button(org, [{"type": "remove_all_assignees"}], name="Снять всех"))
    assert _crew(task) == set() and task.assignee_id is None


def test_round_robin_and_random(org):
    rule = _button(org, [{"type": "round_robin_assignee", "user_ids": [EMP_DEV, HEAD_IT]}])
    first = make_task(department_id=org.it.id, reporter_id=EMP_IT)
    second = make_task(department_id=org.it.id, reporter_id=EMP_IT)
    _ok(first, rule)
    _ok(second, rule)
    assert _crew(first) == {EMP_DEV} and _crew(second) == {HEAD_IT}
    assert AutomationRule.objects.get(pk=rule.pk).state["round_robin"] == 1
    third = make_task(department_id=org.it.id, reporter_id=EMP_IT)
    _ok(third, _button(org, [{"type": "random_assignee", "user_ids": [EMP_DEV]}], name="Случай"))
    assert _crew(third) == {EMP_DEV}


# ── содержимое ──────────────────────────────────────────────────────────

def test_content(org):
    task = assigned_task(org.it, EMP_IT, summary="Смета", description="Было")
    _ok(task, _button(org, [{"type": "rename", "summary": "{cardname} — проверена"},
                            {"type": "set_description", "text": "Стало", "mode": "append"},
                            {"type": "comment", "text": "@card Готово к сдаче"},
                            {"type": "notify", "user_ids": [EMP_DEV], "text": "Посмотрите"}]))
    assert task.summary == "Смета — проверена" and task.description == "Было\n\nСтало"
    comment = TaskComment.objects.get(task=task)
    assert comment.body == "Готово к сдаче" and comment.author_id == EMP_IT
    assert Notification.objects.filter(recipient_id=EMP_DEV,
                                       title__startswith="Посмотрите").exists()


# ── свои поля ───────────────────────────────────────────────────────────

def test_fields(org):
    today = context.today()
    stage = BoardField.objects.create(board_kind="department", board_id=org.it.id, name="Этап",
                                      field_type="list", position="V",
                                      options=[{"id": "a1", "name": "Стройка", "color": None}])
    volume = BoardField.objects.create(board_kind="department", board_id=org.it.id, name="Объём",
                                       field_type="number", position="W")
    taken = BoardField.objects.create(board_kind="department", board_id=org.it.id,
                                      name="Взята", field_type="date", position="X")
    flag = BoardField.objects.create(board_kind="department", board_id=org.it.id, name="Срочно",
                                     field_type="checkbox", position="Y")
    task = assigned_task(org.it, EMP_IT)
    _ok(task, _button(org, [{"type": "set_field", "field_id": stage.pk, "value": "a1"},
                            {"type": "set_field", "field_id": volume.pk, "value": 10},
                            {"type": "increment_field", "field_id": volume.pk, "by": 2.5},
                            {"type": "set_field", "field_id": taken.pk, "mode": "in_days",
                             "days": 2},
                            {"type": "shift_field_date", "field_id": taken.pk, "days": 1},
                            {"type": "set_field", "field_id": flag.pk, "value": True}]))
    values = {field["name"]: field["value"] for board in board_fields.home_boards(task)
              for field in board["fields"]}
    assert values == {"Этап": "a1", "Объём": "12.5",
                      "Взята": (today + timedelta(days=3)).isoformat(), "Срочно": True}
    _ok(task, _button(org, [{"type": "clear_field", "field_id": stage.pk},
                            {"type": "set_field", "field_id": flag.pk, "value": False}],
                      name="Очистить"))
    values = {field["name"]: field["value"] for board in board_fields.home_boards(task)
              for field in board["fields"]}
    assert values["Этап"] is None and values["Срочно"] is False


# ── кнопка на доске ─────────────────────────────────────────────────────

def _board_button(org, trigger, button_actions, conditions=None):
    return add_rule(dept_board(org.it), trigger, button_actions, conditions,
                    kind=AutomationKind.BOARD_BUTTON, name="Кнопка доски")


def test_board_button_over_cards_and_board_level(org):
    urgent = label("Срочно (кнопка доски)")
    todo = [assigned_task(org.it, EMP_IT) for _ in range(2)]
    doing = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS)
    over_cards = _board_button(org, {"type": "board_button", "cards": {"status": "todo"}},
                               [{"type": "add_label", "label_id": urgent.pk}])
    response = post_json(Client(), f"{BASE}/boards/departments/{org.it.id}/buttons/"
                         f"{over_cards.pk}", {}, **as_user(EMP_IT))
    assert response.status_code == 200 and response.json()["done"] == 2
    assert all(task.labels.filter(pk=urgent.pk).exists() for task in todo)
    assert not doing.labels.exists()

    titles = [make_task(department_id=org.it.id, summary=summary, status=Status.BACKLOG)
              for summary in ("Вторая", "Альфа", "Бета")]
    board_level = _board_button(org, {"type": "board_button"},
                                [{"type": "sort_column", "status": "backlog", "by": "title"},
                                 {"type": "create_task", "summary": "Планёрка"}])
    response = post_json(Client(), f"{BASE}/boards/departments/{org.it.id}/buttons/"
                         f"{board_level.pk}", {}, **as_user(EMP_IT))
    assert response.status_code == 200, response.content
    order = [pk for pk, _rank in board_service._column(dept_board(org.it), Status.BACKLOG)]
    assert order == [titles[1].pk, titles[2].pk, titles[0].pk]
    assert Task.objects.filter(summary="Планёрка", department_id=org.it.id).exists()
    # Кто не создаёт задачи на доске — не нажимает.
    response = post_json(Client(), f"{BASE}/boards/departments/{org.it.id}/buttons/"
                         f"{board_level.pk}", {}, **as_user(OUTSIDER))
    assert response.status_code == 404


# ── кнопки: доступность и чужие карточки (спецификация §7, этап S4b) ────

def test_card_button_shows_availability_and_reports_its_own_error(org):
    board = dept_board(org.it)
    submit = add_rule(board, BUTTON, [{"type": "complete"}],
                      [{"type": "in_column", "status": "in_progress"}],
                      kind=AutomationKind.CARD_BUTTON, name="Сдать")
    task = assigned_task(org.it, EMP_IT, status=Status.TODO)
    detail = Client().get(f"{BASE}/tasks/{task.pk}", **as_user(EMP_IT)).json()
    [button] = detail["home_boards"][0]["buttons"]
    assert button["available"] is False and button["reason"]
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/buttons/{submit.pk}", {},
                         **as_user(EMP_IT))
    assert response.status_code == 409
    # Колонку кнопка не задаёт — перенос «В работе → Бэклог» падает уже на
    # месте, и нажавший видит причину ЭТОГО запуска.
    back = add_rule(board, BUTTON, [{"type": "move", "status": "backlog"}],
                    kind=AutomationKind.CARD_BUTTON, name="Назад")
    working = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS)
    response = post_json(Client(), f"{BASE}/tasks/{working.pk}/buttons/{back.pk}", {},
                         **as_user(EMP_IT))
    assert response.status_code == 422 and "перенести нельзя" in response.json()["detail"]


def test_board_button_handles_only_cards_the_presser_may_lead(org):
    button = add_rule(dept_board(org.it), {"type": "board_button", "cards": {"status": "todo"}},
                      [{"type": "set_start_today"}], kind=AutomationKind.BOARD_BUTTON,
                      name="Начать сегодня")
    mine = assigned_task(org.it, EMP_IT, status=Status.TODO)
    foreign = assigned_task(org.it, EMP_DEV, status=Status.TODO)
    response = post_json(Client(), f"{BASE}/boards/departments/{org.it.id}/buttons/{button.pk}",
                         {}, **as_user(EMP_IT))
    assert response.json() == {"status": "ok", "cards": 1, "done": 1, "skipped": 1}
    mine.refresh_from_db()
    foreign.refresh_from_db()
    assert mine.start_date == context.today() and foreign.start_date is None
