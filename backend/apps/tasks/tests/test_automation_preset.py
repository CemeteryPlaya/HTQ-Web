"""Шаблон «Процесс задач HTQ» (решение K-40, этап S4; защита — решения L-02,
L-03 этапа S4b) — сквозной тест процесса из Trello на доске отдела.

Назначили исполнителя и срок — задача сама в «Ожидающие исполнения» с
чек-листом; руками в «Исполнение» нельзя, «Выполнить задачу», кнопка «Взять в
работу» и встроенное «Взять в работу» — можно (дату ставит правило); причина
ожидания уводит в «В ожидании» и обратно; все пункты — «Готово» и снятие
«Просрочено»; «На доработку» возвращает в «Исполнение» со сброшенным
чек-листом; просрочка — метка и комментарий. Кнопки работают только в своих
колонках, обходы процесса через «На ревью» и «В ожидании» закрыты.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client

from apps.tasks.models import (AutomationRule, BoardField, BoardSettings, Label, Status, Task,
                               TaskChecklistItem, TaskComment)
from apps.tasks.services.automation import context, presets, scheduled

from .automation_helpers import assigned_task, dept_board
from .helpers import BASE, patch_json, post_json, put_json
from .org_fixtures import EMP_IT, HEAD_IT, as_user, make_org, make_task

pytestmark = pytest.mark.django_db

PRESET_AUTOMATIONS = 27


@pytest.fixture
def org():
    made = make_org()
    presets.apply(dept_board(made.it), "htq_process", HEAD_IT)
    return made


@pytest.fixture(autouse=True)
def _due_any_hour(settings):
    """Команды по сроку ждут 09:00 по времени платформы — тестам час не важен."""
    settings.AUTOMATION_DUE_HOUR = 0


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


def _press(org, task, name, who=EMP_IT):
    rule = AutomationRule.objects.get(board_id=org.it.id, kind="card_button", name=name)
    return post_json(Client(), f"{BASE}/tasks/{task.pk}/buttons/{rule.pk}", {}, **as_user(who))


def _button(org, task, name, who=EMP_IT):
    response = _press(org, task, name, who)
    assert response.status_code == 200, response.content
    task.refresh_from_db()


def _taken(task, who=EMP_IT):
    detail = Client().get(f"{BASE}/tasks/{task.pk}", **as_user(who)).json()
    values = {field["name"]: field["value"] for field in detail["home_boards"][0]["fields"]}
    return values[presets.FIELD_TAKEN]


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
    assert AutomationRule.objects.filter(board_id=org.it.id).count() == PRESET_AUTOMATIONS
    report = presets.apply(dept_board(org.it), "htq_process", HEAD_IT)
    assert report["automations"]["created"] == [] and report["automations"]["updated"] == []
    assert len(report["automations"]["unchanged"]) == PRESET_AUTOMATIONS
    assert BoardField.objects.filter(board_id=org.it.id).count() == 2
    assert Label.objects.filter(name="Просрочено").count() == 1
    # Правку администратора повтор шаблона восстанавливает; пробный прогон —
    # тот же отчёт без записи.
    rework = AutomationRule.objects.get(board_id=org.it.id, preset_key="htq.r19")
    AutomationRule.objects.filter(pk=rework.pk).update(name="Своё название")
    dry = presets.apply(dept_board(org.it), "htq_process", HEAD_IT, dry_run=True)
    assert dry["dry_run"] is True and dry["automations"]["updated"] == [
        "Комментарий «На доработку» — в «Исполнение»"]
    rework.refresh_from_db()
    assert rework.name == "Своё название"
    presets.apply(dept_board(org.it), "htq_process", HEAD_IT)
    rework.refresh_from_db()
    assert rework.name == "Комментарий «На доработку» — в «Исполнение»"


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
    assert _taken(task) == today.isoformat()
    assert _field(org, presets.FIELD_TAKEN).show_on_card is True

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

    # «На доработку…» в комментарии — «Исполнение», чек-лист сброшен; комментарий
    # автоматизации помнит своё правило.
    post_json(Client(), f"{BASE}/tasks/{task.pk}/comments/",
              {"body": "На доработку: поправьте смету"}, **as_user(HEAD_IT))
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS
    assert all(not done for _text, done in _items(task))
    rework = TaskComment.objects.filter(task=task, author_id=None).get()
    assert rework.body.startswith("Задачу вернули на доработку")
    assert rework.via_rule_id == AutomationRule.objects.get(
        board_id=org.it.id, preset_key="htq.r18").pk

    # «Сдать» — «Готово», все пункты отмечены.
    _button(org, task, "Сдать")
    assert task.status == Status.DONE and all(done for _text, done in _items(task))


def test_buttons_work_only_in_their_columns(org):
    today = context.today()
    task = make_task(department_id=org.it.id, reporter_id=HEAD_IT, status=Status.BACKLOG)
    response = _manual(task, "in_progress", who=HEAD_IT)
    assert response.status_code == 409 and response.json()["detail"] == presets.BLOCK_12
    detail = Client().get(f"{BASE}/tasks/{task.pk}", **as_user(HEAD_IT)).json()
    buttons = {button["name"]: button for button in detail["home_boards"][0]["buttons"]}
    assert buttons["Взять в работу"]["available"] is False
    assert buttons["Сдать"]["available"] is False and buttons["Сдать"]["reason"]
    # Кнопка не в своей колонке не обходит запрет «Постановка → Исполнение».
    assert _press(org, task, "Взять в работу", who=HEAD_IT).status_code == 409
    task.refresh_from_db()
    assert task.status == Status.BACKLOG

    ready = assigned_task(org.it, EMP_IT, status=Status.TODO)
    _button(org, ready, "Взять в работу")
    assert ready.status == Status.IN_PROGRESS and _taken(ready) == today.isoformat()
    assert _press(org, ready, "На доработку").status_code == 409     # ещё не в «Готово»
    _button(org, ready, "Сдать")
    assert ready.status == Status.DONE
    _button(org, ready, "На доработку")
    assert ready.status == Status.IN_PROGRESS


def test_claim_takes_free_work_and_stamps_the_date(org):
    """Встроенное «Взять в работу» — шаг процесса (L-02): запреты r12 и r17 его
    не держат, «Взята в работу» ставит правило входа в «Исполнение»."""
    today = context.today()
    for status in (Status.TODO, Status.BACKLOG):
        free = make_task(department_id=org.it.id, reporter_id=HEAD_IT, status=status)
        response = post_json(Client(), f"{BASE}/tasks/{free.pk}/claim", {}, **as_user(EMP_IT))
        assert response.status_code == 200, response.content
        free.refresh_from_db()
        assert free.status == Status.IN_PROGRESS and free.assignee_id == EMP_IT
        assert _taken(free) == today.isoformat()


def test_no_detours_around_the_process(org):
    task = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS)
    # «На ревью» в процессе нет — через неё в «Готово» не обойти.
    assert _manual(task, "in_review").json()["detail"] == presets.BLOCK_REVIEW
    # В «В ожидании» вручную — только с причиной, обратно — только очистив её.
    assert _manual(task, "blocked").json()["detail"] == presets.BLOCK_WAIT_IN
    reason = _field(org, presets.FIELD_REASON)
    put_json(Client(), f"{BASE}/tasks/{task.pk}/fields/{reason.pk}", {"value": "Ждём подпись"},
             **as_user(EMP_IT))
    task.refresh_from_db()
    assert task.status == Status.BLOCKED
    assert _manual(task, "in_progress").json()["detail"] == presets.BLOCK_WAIT_OUT
    assert _manual(task, "todo").json()["detail"] == presets.BLOCK_WAIT_OUT
    # Отменить ожидающую задачу можно.
    assert _manual(task, "cancelled", who=HEAD_IT).status_code == 200


def test_overdue_label_leaves_with_the_overdue(org):
    today = context.today()
    overdue = Label.objects.get(name="Просрочено")

    def overdue_task():
        task = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS,
                             due_date=today - timedelta(days=3))
        task.labels.add(overdue)
        return task

    def due(task, value):
        response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/",
                              {"due_date": value and str(value)}, **as_user(HEAD_IT))
        assert response.status_code == 200, response.content

    moved = overdue_task()
    due(moved, today + timedelta(days=3))                  # срок перенесли вперёд
    still = overdue_task()
    due(still, today - timedelta(days=1))                  # всё ещё просрочена
    removed = overdue_task()
    due(removed, None)                                      # срок сняли
    cancelled = overdue_task()
    assert _manual(cancelled, "cancelled", who=HEAD_IT).status_code == 200
    has = {task.pk: task.labels.filter(pk=overdue.pk).exists()
           for task in (moved, still, removed, cancelled)}
    assert has == {moved.pk: False, still.pk: True, removed.pk: False, cancelled.pk: False}


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
