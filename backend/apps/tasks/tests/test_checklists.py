"""Чек-листы задачи (решение K-20, мастер-план канбана §3.6, §6.3; этап S2).

Права — как у статуса: отметить, добавить, переименовать пункт или чек-лист —
тот, кто ведёт задачу (``require_soft_edit``); удалить чек-лист — только с
полной правкой. Чужой чек-лист — 404, как несуществующий. Каждое действие,
кроме перестановки, — строка журнала задачи. Счётчики «3/7» — на карточке
доски.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.test import Client

from apps.tasks.models import Status, TaskActivity, TaskAssignee, TaskChecklist, TaskChecklistItem
from apps.tasks.services import checklist_service

from .helpers import BASE, patch_json, post_json
from .org_fixtures import EMP_DEV, EMP_IT, HEAD_IT, OUTSIDER, as_user, make_org, make_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _assigned(user_id=EMP_IT, **fields):
    """Задача, которую ведёт ``user_id`` (исполнитель — soft edit), автор — HEAD_IT."""
    task = make_task(assignee_id=user_id, reporter_id=HEAD_IT, **fields)
    TaskAssignee.objects.create(task=task, user_id=user_id, role="primary")
    return task


def _new_checklist(task, title="Чек-лист", who=EMP_IT):
    return post_json(Client(), f"{BASE}/tasks/{task.pk}/checklists", {"title": title},
                     **as_user(who))


def _add(checklist_id, text, who=EMP_IT, **neighbours):
    return post_json(Client(), f"{BASE}/checklists/{checklist_id}/items",
                     {"text": text, **neighbours}, **as_user(who))


def _texts(body):
    return [item["text"] for item in body["items"]]


def test_assignee_creates_checklist_and_items_in_order(org):
    task = _assigned()
    response = _new_checklist(task, "  Приёмка  ")
    assert response.status_code == 201, response.content
    checklist = response.json()
    assert checklist["title"] == "Приёмка" and checklist["total"] == 0
    for text in ("Проверить смету", "Подписать акт"):
        body = _add(checklist["id"], text).json()
    assert _texts(body) == ["Проверить смету", "Подписать акт"]
    first, second = body["items"]
    body = _add(checklist["id"], "Сверить объёмы", before_id=first["id"],
                after_id=second["id"]).json()
    assert _texts(body) == ["Проверить смету", "Сверить объёмы", "Подписать акт"]
    assert body["done"] == 0 and body["total"] == 3


def test_check_records_who_and_when_and_uncheck_clears(org):
    task = _assigned()
    checklist = _new_checklist(task).json()
    item = _add(checklist["id"], "Сделать").json()["items"][0]
    body = patch_json(Client(), f"{BASE}/checklist-items/{item['id']}", {"is_done": True},
                      **as_user(EMP_IT)).json()
    checked = body["items"][0]
    assert checked["is_done"] and checked["done_by"]["id"] == EMP_IT and checked["done_at"]
    assert body["done"] == 1
    body = patch_json(Client(), f"{BASE}/checklist-items/{item['id']}", {"is_done": False},
                      **as_user(EMP_IT)).json()
    assert body["items"][0]["done_by"] is None and body["items"][0]["done_at"] is None
    fields = list(TaskActivity.objects.filter(task=task).order_by("id")
                  .values_list("field_name", flat=True))
    assert fields == ["checklist_added", "checklist_item_added", "checklist_item_checked",
                      "checklist_item_unchecked"]


def test_viewer_without_soft_edit_cannot_touch_checklists(org):
    task = _assigned(department_id=org.it.id)
    checklist = _new_checklist(task).json()
    # Посторонний из ops задачу отдела it не видит вовсе — 404, не 403.
    assert _new_checklist(task, who=OUTSIDER).status_code == 404
    assert _add(checklist["id"], "Чужой пункт", who=OUTSIDER).status_code == 404
    other = make_task(department_id=org.it.id, reporter_id=HEAD_IT)
    other_list = TaskChecklist.objects.create(task=other, title="Глава", position="V")
    # EMP_IT видит задачу своего отдела, но не участник — правки нет (403).
    assert _add(other_list.id, "Пункт", who=EMP_IT).status_code == 403
    # Глава отдела задачи правит (K-06).
    assert _add(other_list.id, "Пункт", who=HEAD_IT).status_code == 201


def test_delete_checklist_needs_full_edit(org):
    task = _assigned()
    checklist = _new_checklist(task).json()
    url = f"{BASE}/checklists/{checklist['id']}"
    # Исполнитель — soft edit: чек-лист удалить не может.
    assert Client().delete(url, **as_user(EMP_IT)).status_code == 403
    # Автор задачи — полная правка.
    assert Client().delete(url, **as_user(HEAD_IT)).status_code == 204
    assert not TaskChecklist.objects.filter(pk=checklist["id"]).exists()
    assert TaskActivity.objects.filter(task=task, field_name="checklist_deleted",
                                       old_value="Чек-лист").exists()


def test_item_delete_and_rename_are_soft_and_logged(org):
    task = _assigned()
    checklist = _new_checklist(task).json()
    item = _add(checklist["id"], "Старый текст").json()["items"][0]
    body = patch_json(Client(), f"{BASE}/checklist-items/{item['id']}", {"text": "Новый текст"},
                      **as_user(EMP_IT)).json()
    assert _texts(body) == ["Новый текст"]
    response = Client().delete(f"{BASE}/checklist-items/{item['id']}", **as_user(EMP_IT))
    assert response.status_code == 200 and response.json()["total"] == 0
    renamed = TaskActivity.objects.get(task=task, field_name="checklist_item_renamed")
    assert (renamed.old_value, renamed.new_value) == ("Старый текст", "Новый текст")
    assert TaskActivity.objects.filter(task=task, field_name="checklist_item_deleted").exists()


def test_item_moves_to_another_checklist_of_the_same_task_only(org):
    task = _assigned()
    first = _new_checklist(task, "Первый").json()
    second = _new_checklist(task, "Второй").json()
    item = _add(first["id"], "Пункт").json()["items"][0]
    body = patch_json(Client(), f"{BASE}/checklist-items/{item['id']}",
                      {"checklist_id": second["id"]}, **as_user(EMP_IT)).json()
    assert body["id"] == second["id"] and _texts(body) == ["Пункт"]
    foreign = TaskChecklist.objects.create(task=_assigned(), title="Чужой", position="V")
    response = patch_json(Client(), f"{BASE}/checklist-items/{item['id']}",
                          {"checklist_id": foreign.id}, **as_user(EMP_IT))
    assert response.status_code == 404


def test_reorder_checklists_and_stale_neighbour(org):
    task = _assigned()
    a, b, c = (_new_checklist(task, title).json() for title in ("A", "B", "C"))
    response = patch_json(Client(), f"{BASE}/checklists/{c['id']}",
                          {"before_id": None, "after_id": a["id"]}, **as_user(EMP_IT))
    assert response.status_code == 200, response.content
    titles = [row["title"] for row in checklist_service.for_task(task.pk)]
    assert titles == ["C", "A", "B"]
    stale = patch_json(Client(), f"{BASE}/checklists/{a['id']}",
                       {"before_id": b["id"], "after_id": c["id"]}, **as_user(EMP_IT))
    assert stale.status_code == 409 and stale.json()["code"] == "checklist_order_stale"
    # Перестановка в журнал не пишется.
    assert not TaskActivity.objects.filter(task=task, field_name="checklist_renamed").exists()


def test_limits(org, monkeypatch):
    task = _assigned()
    monkeypatch.setattr(checklist_service, "CHECKLIST_LIMIT", 1)
    monkeypatch.setattr(checklist_service, "ITEM_LIMIT", 1)
    checklist = _new_checklist(task).json()
    second = _new_checklist(task)
    assert second.status_code == 422 and second.json()["code"] == "checklist_limit"
    _add(checklist["id"], "Один")
    extra = _add(checklist["id"], "Два")
    assert extra.status_code == 422 and extra.json()["code"] == "checklist_limit"


def test_blank_text_is_422(org):
    task = _assigned()
    assert _new_checklist(task, "   ").status_code == 422


def test_detail_carries_checklists_and_board_counts(org):
    task = _assigned(status=Status.TODO)
    checklist = _new_checklist(task).json()
    for text in ("a", "b", "c"):
        body = _add(checklist["id"], text).json()
    patch_json(Client(), f"{BASE}/checklist-items/{body['items'][0]['id']}", {"is_done": True},
               **as_user(EMP_IT))
    detail = Client().get(f"{BASE}/tasks/{task.pk}/", **as_user(EMP_IT)).json()
    assert [row["title"] for row in detail["checklists"]] == ["Чек-лист"]
    assert detail["checklists"][0]["done"] == 1 and detail["checklists"][0]["total"] == 3
    board = Client().get(f"{BASE}/boards/personal", **as_user(EMP_IT)).json()
    card = next(card for column in board["columns"] for card in column["cards"]
                if card["id"] == task.pk)
    assert (card["counts"]["checklist_done"], card["counts"]["checklist_total"]) == (1, 3)


def test_done_constraint_holds_in_the_database(org):
    task = _assigned()
    checklist = TaskChecklist.objects.create(task=task, title="БД", position="V")
    with pytest.raises(IntegrityError), transaction.atomic():
        TaskChecklistItem.objects.create(checklist=checklist, text="x", position="V",
                                         is_done=True, done_at=None)


def test_dev_department_employee_does_not_see_parent_task(org):
    """Видимость — по поддереву своего отдела (K-04): сотрудник подотдела
    задачу отдела-родителя не видит, её чек-листы — тоже (404)."""
    task = _assigned(department_id=org.it.id)
    response = Client().get(f"{BASE}/tasks/{task.pk}/checklists", **as_user(EMP_DEV))
    assert response.status_code == 404
