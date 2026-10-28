"""Шаблон «Процесс задач HTQ» (решение K-40, этап S4) — сквозной тест процесса
из Trello на доске отдела.

Назначили исполнителя и срок — задача сама в «Ожидающие исполнения» с
чек-листом; руками в «Исполнение» нельзя, «Выполнить задачу» или кнопка
«Взять в работу» — можно; причина ожидания уводит в «В ожидании» и обратно;
все пункты — «Готово» и снятие «Просрочено»; «На доработку» возвращает в
«Исполнение» со сброшенным чек-листом; просрочка — метка и комментарий.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client

from apps.tasks.models import (AutomationRule, BoardField, BoardSettings, Label, Status, Task,
                               TaskAssignee, TaskChecklistItem, TaskComment)
from apps.tasks.services.automation import context, presets, scheduled

from .automation_helpers import dept_board
from .helpers import BASE, patch_json, post_json, put_json
from .org_fixtures import EMP_IT, HEAD_IT, as_user, make_org, make_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    made = make_org()
    presets.apply(dept_board(made.it), "htq_process", HEAD_IT)
    return made


def _field(org, name) -> BoardField:
    return BoardField.objects.get(board_kind="department", board_id=org.it.id, name=name)


def _items(task) -> list[tuple[str, bool]]:
    return list(TaskChecklistItem.objects.filter(checklist__task=task)
                .order_by("position").values_list("text", "is_done"))


def _check(task, text, who=EMP_IT, done=True):
    item = TaskChecklistItem.objects.get(checklist__task=task, text=text)
    response = patch_json(Client(), f"{BASE}/checklist-items/{item.pk}", {"is_done": done},
                          **as_user(who))
    assert response.status_code == 200, response.content
    task.refresh_from_db()


def _manual(task, status, who=EMP_IT):
    return patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"status": status}, **as_user(who))


def _button(org, task, name, who=EMP_IT):
    rule = AutomationRule.objects.get(board_id=org.it.id, kind="card_button", name=name)
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/buttons/{rule.pk}", {},
                         **as_user(who))
    assert response.status_code == 200, response.content
    task.refresh_from_db()


def _new_task(org) -> Task:
    """Задачу ставит глава отдела: исполнитель и срок — сразу."""
    response = post_json(Client(), f"{BASE}/tasks/", {
        "summary": "Согласовать смету", "status": "backlog", "department_id": org.it.id,
        "assignee_id": EMP_IT, "due_date": "2031-01-10"}, **as_user(HEAD_IT))
    assert response.status_code in (200, 201), response.content
    return Task.objects.get(pk=response.json()["id"])


def test_preset_sets_up_the_board_and_is_idempotent(org):
    settings = BoardSettings.objects.get(board_kind="department", board_id=org.it.id)
    assert settings.columns["backlog"]["title"] == "Постановка задачи"
    assert settings.columns["cancelled"]["hidden"] is True
    assert [item["title"] for item in settings.checklist_templates] == ["Чек-лист"]
    report = presets.apply(dept_board(org.it), "htq_process", HEAD_IT)
    assert report["automations"]["created"] == [] and len(report["automations"]["updated"]) == 19
    assert AutomationRule.objects.filter(board_id=org.it.id).count() == 19
    assert BoardField.objects.filter(board_id=org.it.id).count() == 2
    assert Label.objects.filter(name="Просрочено").count() == 1
    dry = presets.apply(dept_board(org.it), "htq_process", HEAD_IT, dry_run=True)
    assert dry["dry_run"] is True


def test_htq_process_from_trello(org):
    today = context.today()
    task = _new_task(org)
    # Назначен исполнитель и срок — «Ожидающие исполнения», чек-лист по шаблону.
    assert task.status == Status.TODO
    assert _items(task) == [(text, False) for text in presets.CHECKLIST_ITEMS]

    # Руками в «Исполнение» — нельзя, пока не взята в работу.
    response = _manual(task, "in_progress")
    assert response.status_code == 409 and response.json()["detail"] == presets.BLOCK_17

    # «Выполнить задачу» — взята в работу сегодня, «Исполнение».
    _check(task, "Ознакомиться с задачей")
    _check(task, "Выполнить задачу")
    assert task.status == Status.IN_PROGRESS
    taken = _field(org, presets.FIELD_TAKEN)
    detail = Client().get(f"{BASE}/tasks/{task.pk}", **as_user(EMP_IT)).json()
    values = {field["name"]: field["value"] for field in detail["home_boards"][0]["fields"]}
    assert values[presets.FIELD_TAKEN] == today.isoformat()
    assert taken.show_on_card is True

    # Обратно в «Ожидающие» и в «Готово» с невыполненным чек-листом — нельзя.
    assert _manual(task, "todo").json()["detail"] == presets.BLOCK_13
    assert _manual(task, "done").json()["detail"] == presets.BLOCK_16

    # Причина ожидания — «В ожидании», очищена — снова «Исполнение».
    reason = _field(org, presets.FIELD_REASON)
    put_json(Client(), f"{BASE}/tasks/{task.pk}/fields/{reason.pk}", {"value": "Ждём подпись"},
             **as_user(EMP_IT))
    task.refresh_from_db()
    assert task.status == Status.BLOCKED
    put_json(Client(), f"{BASE}/tasks/{task.pk}/fields/{reason.pk}", {"value": None},
             **as_user(EMP_IT))
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS

    # Все пункты отмечены — «Готово», «Просрочено» снята.
    overdue = Label.objects.get(name="Просрочено")
    task.labels.add(overdue)
    _check(task, "Проверить результат")
    _check(task, "Отправить отчёт руководителю")
    assert task.status == Status.DONE
    assert not task.labels.filter(pk=overdue.pk).exists()

    # «На доработку…» в комментарии — «Исполнение», чек-лист сброшен.
    post_json(Client(), f"{BASE}/tasks/{task.pk}/comments/",
              {"body": "На доработку: поправьте смету"}, **as_user(HEAD_IT))
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS
    assert all(not done for _text, done in _items(task))
    rework = TaskComment.objects.filter(task=task, author_id=None).get()
    assert rework.body.startswith("Задачу вернули на доработку")

    # «Сдать» — «Готово», все пункты отмечены.
    _button(org, task, "Сдать")
    assert task.status == Status.DONE and all(done for _text, done in _items(task))


def test_take_button_and_backlog_block(org):
    task = make_task(department_id=org.it.id, reporter_id=HEAD_IT, status=Status.BACKLOG)
    response = _manual(task, "in_progress", who=HEAD_IT)
    assert response.status_code == 409 and response.json()["detail"] == presets.BLOCK_12
    _button(org, task, "Взять в работу", who=HEAD_IT)
    assert task.status == Status.IN_PROGRESS
    assert TaskAssignee.objects.filter(task=task, user_id=HEAD_IT).exists()
    _button(org, task, "Сдать", who=HEAD_IT)
    _button(org, task, "На доработку", who=HEAD_IT)
    assert task.status == Status.IN_PROGRESS


def test_overdue_command(org):
    today = context.today()
    task = make_task(department_id=org.it.id, reporter_id=HEAD_IT, status=Status.IN_PROGRESS,
                     due_date=today - timedelta(days=1))
    done = make_task(department_id=org.it.id, reporter_id=HEAD_IT, status=Status.DONE,
                     due_date=today - timedelta(days=1))
    assert scheduled.run_due() == 1
    assert task.labels.filter(name="Просрочено").exists()
    assert TaskComment.objects.get(task=task).body.startswith("Срок выполнения прошёл")
    assert not done.labels.exists()
    assert scheduled.run_due() == 0
