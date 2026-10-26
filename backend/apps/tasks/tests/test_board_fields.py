"""Свои поля досок и шаблоны чек-листов (решение K-35, канбан, этап S3).

Поля — у досок отделов и проектов; правит их администратор доски (K-39).
Поля задачи — поля её домашних досок: отдела ``department_id`` и проекта
``project_id``; доска вышестоящего отдела свои поля к поддереву не
применяет. Значение правит тот, кто ведёт задачу; смена — строка журнала
``field:<id>``. Шаблоны чек-листов живут в настройках доски, кнопка
«Чек-лист» копирует их пункты.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.tasks.models import (BoardField, BoardSettings, Label, Status, TaskActivity,
                               TaskAssignee, TaskChecklist, TaskFieldValue)
from apps.tasks.services import board_fields

from .helpers import BASE, patch_json, post_json, put_json
from .org_fixtures import (EMP_DEV, EMP_IT, HEAD_IT, HEAD_OPS, OUTSIDER, TD, as_user,
                           make_board, make_org, make_task)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _fields_url(org):
    return f"{BASE}/boards/departments/{org.it.id}/fields"


def _create(org, body, who=HEAD_IT, url=None):
    return post_json(Client(), url or _fields_url(org), body, **as_user(who))


def _field(org, name, field_type, **extra):
    response = _create(org, {"name": name, "type": field_type, **extra})
    assert response.status_code == 201, response.content
    return response.json()


def _assigned(org, user_id=EMP_IT, **fields):
    """Задача отдела it, которую ведёт ``user_id`` (исполнитель — soft edit)."""
    task = make_task(department_id=org.it.id, assignee_id=user_id, reporter_id=HEAD_IT,
                     **fields)
    TaskAssignee.objects.create(task=task, user_id=user_id, role="primary")
    return task


def _set(task, field_id, value, who=EMP_IT):
    return put_json(Client(), f"{BASE}/tasks/{task.pk}/fields/{field_id}", {"value": value},
                    **as_user(who))


def _detail(task, who=EMP_IT):
    return Client().get(f"{BASE}/tasks/{task.pk}", **as_user(who)).json()


def _values(home_boards):
    return {field["name"]: field["value"] for board in home_boards for field in board["fields"]}


# ── определения ────────────────────────────────────────────────────────

def test_head_creates_fields_of_every_type_in_order(org):
    names = []
    for name, field_type in (("Причина ожидания", "text"), ("Объём, м³", "number"),
                             ("Взята в работу", "date"), ("Срочно", "checkbox")):
        names.append(_field(org, name, field_type)["name"])
    stage = _field(org, "Этап", "list", show_on_card=True,
                   options=[{"name": "Проект", "color": "blue"}, {"name": "Стройка"}])
    assert [option["name"] for option in stage["options"]] == ["Проект", "Стройка"]
    assert all(option["id"] for option in stage["options"])
    assert stage["options"][0]["color"] == "blue" and stage["options"][1]["color"] is None
    listed = Client().get(_fields_url(org), **as_user(EMP_IT))
    assert listed.status_code == 200
    assert [field["name"] for field in listed.json()] == names + ["Этап"]


def test_fields_need_board_admin(org):
    assert _create(org, {"name": "Поле", "type": "text"}, who=EMP_IT).status_code == 403
    assert _create(org, {"name": "Поле", "type": "text"}, who=OUTSIDER).status_code == 404
    field = _field(org, "Поле", "text")
    url = f"{BASE}/boards/fields/{field['id']}"
    assert patch_json(Client(), url, {"name": "Другое"}, **as_user(EMP_IT)).status_code == 403
    assert Client().delete(url, **as_user(EMP_IT)).status_code == 403
    # Доску ops сотрудник it не видит — поле её доски для него не существует.
    assert Client().delete(url, **as_user(OUTSIDER)).status_code == 404
    assert BoardField.objects.filter(pk=field["id"]).exists()


def test_project_owner_administers_project_board_fields(org):
    board = make_board("KB-F1", department=org.it)
    board.owner_id = TD
    board.save(update_fields=["owner_id"])
    url = f"{BASE}/boards/projects/{board.pk}/fields"
    response = _create(org, {"name": "Смета", "type": "number"}, who=TD, url=url)
    assert response.status_code == 201, response.content
    assert response.json()["board_kind"] == "project"
    assert _create(org, {"name": "Ещё", "type": "text"}, who=HEAD_IT, url=url).status_code == 403


@pytest.mark.parametrize("body", [
    {"name": "Список", "type": "list", "options": [{"name": "А"}, {"name": "а"}]},
    {"name": "Текст", "type": "text", "options": [{"name": "А"}]},
    {"name": "Цвет", "type": "list", "options": [{"name": "А", "color": "magenta"}]},
    {"name": "Тип", "type": "rating"},
    {"name": "   ", "type": "text"},
])
def test_bad_field_definitions_are_rejected(org, body):
    assert _create(org, body).status_code == 422


def test_name_is_unique_on_board_ignoring_case(org):
    _field(org, "Причина ожидания", "text")
    response = _create(org, {"name": "причина ОЖИДАНИЯ", "type": "text"})
    assert response.status_code == 409 and response.json()["code"] == "board_field_name_taken"
    # На другой доске — можно.
    other = f"{BASE}/boards/departments/{org.ops.id}/fields"
    assert _create(org, {"name": "Причина ожидания", "type": "text"}, who=HEAD_OPS,
                   url=other).status_code == 201


def test_field_limit(org, monkeypatch):
    monkeypatch.setattr(board_fields, "FIELD_LIMIT", 2)
    _field(org, "Первое", "text")
    _field(org, "Второе", "text")
    response = _create(org, {"name": "Третье", "type": "text"})
    assert response.status_code == 422 and response.json()["code"] == "board_field_limit"


def test_type_does_not_change_and_fields_reorder(org):
    first = _field(org, "Первое", "text")
    second = _field(org, "Второе", "text")
    third = _field(org, "Третье", "text")
    url = f"{BASE}/boards/fields/{third['id']}"
    assert patch_json(Client(), url, {"type": "number"}, **as_user(HEAD_IT)).status_code == 422
    response = patch_json(Client(), url, {"before_id": first["id"], "after_id": second["id"]},
                          **as_user(HEAD_IT))
    assert response.status_code == 200, response.content
    names = [field["name"] for field in Client().get(_fields_url(org), **as_user(HEAD_IT)).json()]
    assert names == ["Первое", "Третье", "Второе"]
    stale = patch_json(Client(), url, {"before_id": second["id"], "after_id": first["id"]},
                       **as_user(HEAD_IT))
    assert stale.status_code == 409 and stale.json()["code"] == "board_field_order_stale"


# ── значения ────────────────────────────────────────────────────────────

def test_assignee_sets_and_clears_values_with_journal(org):
    reason = _field(org, "Причина ожидания", "text")
    volume = _field(org, "Объём", "number")
    taken = _field(org, "Взята в работу", "date")
    urgent = _field(org, "Срочно", "checkbox")
    stage = _field(org, "Этап", "list", options=[{"name": "Проект"}, {"name": "Стройка"}])
    task = _assigned(org)

    assert _set(task, reason["id"], "  Ждём смету  ").status_code == 200
    assert _set(task, volume["id"], "1 234,50").status_code == 200
    assert _set(task, taken["id"], "2026-10-26").status_code == 200
    assert _set(task, urgent["id"], True).status_code == 200
    response = _set(task, stage["id"], stage["options"][1]["id"])
    assert response.status_code == 200
    values = _values(response.json()["home_boards"])
    assert values == {"Причина ожидания": "Ждём смету", "Объём": "1234.5",
                      "Взята в работу": "2026-10-26", "Срочно": True,
                      "Этап": stage["options"][1]["id"]}

    assert _set(task, reason["id"], None).status_code == 200
    assert _set(task, urgent["id"], False).status_code == 200
    assert _set(task, volume["id"], 7).status_code == 200
    values = _values(_detail(task)["home_boards"])
    assert values["Причина ожидания"] is None and values["Срочно"] is False
    assert values["Объём"] == "7"
    assert not TaskFieldValue.objects.filter(task=task, field_id=reason["id"]).exists()

    journal = {(row.field_name, row.old_value, row.new_value)
               for row in TaskActivity.objects.filter(task=task, field_name__startswith="field:")}
    assert (f"field:{reason['id']}", None, "Ждём смету") in journal
    assert (f"field:{reason['id']}", "Ждём смету", None) in journal
    assert (f"field:{stage['id']}", None, "Стройка") in journal
    assert (f"field:{urgent['id']}", "true", None) in journal
    assert (f"field:{volume['id']}", "1234.5", "7") in journal


def test_same_value_writes_no_journal(org):
    reason = _field(org, "Причина", "text")
    task = _assigned(org)
    _set(task, reason["id"], "Ждём")
    _set(task, reason["id"], " Ждём ")
    assert TaskActivity.objects.filter(task=task, field_name=f"field:{reason['id']}").count() == 1


@pytest.mark.parametrize(("field_type", "value"), [
    ("text", "x" * 501), ("text", 5), ("number", "много"), ("number", True),
    ("number", "1e20"), ("date", "26.10.2026"), ("date", 20261026), ("checkbox", "да"),
    ("list", "nope"),
])
def test_bad_values_are_rejected(org, field_type, value):
    field = _field(org, "Поле", field_type,
                   **({"options": [{"name": "А"}]} if field_type == "list" else {}))
    response = _set(_assigned(org), field["id"], value)
    assert response.status_code == 422
    assert response.json()["code"] == "board_field_value_invalid"


def test_value_rights_follow_soft_edit(org):
    field = _field(org, "Поле", "text")
    task = make_task(department_id=org.it.id, reporter_id=HEAD_IT)
    # Видит задачу своего отдела, но не ведёт её — 403; посторонний — 404.
    assert _set(task, field["id"], "x", who=EMP_IT).status_code == 403
    assert _set(task, field["id"], "x", who=OUTSIDER).status_code == 404
    assert _set(task, field["id"], "x", who=HEAD_IT).status_code == 200


def test_field_applies_only_to_home_boards(org):
    """Задача поддерева (it.dev) лежит на доске it, но поле доски it к ней не
    применяется — её домашняя доска — доска it.dev."""
    field = _field(org, "Поле it", "text")
    sub = make_task(department_id=org.dev.id, assignee_id=EMP_DEV, reporter_id=HEAD_IT)
    TaskAssignee.objects.create(task=sub, user_id=EMP_DEV, role="primary")
    assert _set(sub, field["id"], "x", who=EMP_DEV).status_code == 404
    assert _detail(sub, EMP_DEV)["home_boards"][0]["fields"] == []
    foreign = BoardField.objects.create(board_kind="department", board_id=org.ops.id,
                                        name="Чужое", field_type="text", position="V")
    assert _set(_assigned(org), foreign.id, "x").status_code == 404


def test_home_boards_of_department_and_project(org):
    board = make_board("KB-F2", department=org.it)
    task = _assigned(org, project=board)
    _field(org, "Поле отдела", "text")
    BoardField.objects.create(board_kind="project", board_id=board.pk, name="Поле проекта",
                              field_type="checkbox", position="V")
    homes = _detail(task)["home_boards"]
    assert [(home["kind"], home["id"]) for home in homes] == [("department", org.it.id),
                                                              ("project", board.pk)]
    assert homes[0]["title"] == org.it.name and homes[1]["title"] == board.name
    assert [field["name"] for field in homes[0]["fields"]] == ["Поле отдела"]
    assert homes[1]["fields"][0]["value"] is False
    assert _detail(make_task(reporter_id=EMP_IT))["home_boards"] == []


# ── варианты списка ─────────────────────────────────────────────────────

def test_option_rename_keeps_values_and_removal_clears_them(org):
    stage = _field(org, "Этап", "list", options=[{"name": "Проект"}, {"name": "Стройка"}])
    project, build = stage["options"]
    task = _assigned(org)
    other = _assigned(org)
    _set(task, stage["id"], project["id"])
    _set(other, stage["id"], build["id"])
    url = f"{BASE}/boards/fields/{stage['id']}"
    response = patch_json(Client(), url, {"options": [
        {"id": project["id"], "name": "Проектирование", "color": "purple"},
        {"name": "Сдача"},
    ]}, **as_user(HEAD_IT))
    assert response.status_code == 200, response.content
    assert [option["name"] for option in response.json()["options"]] == ["Проектирование", "Сдача"]
    assert _values(_detail(task)["home_boards"])["Этап"] == project["id"]
    assert _values(_detail(other)["home_boards"])["Этап"] is None
    assert not TaskFieldValue.objects.filter(task=other).exists()
    cleared = TaskActivity.objects.get(task=other, field_name=f"field:{stage['id']}",
                                       new_value=None)
    assert cleared.old_value == "Стройка" and cleared.actor_id == HEAD_IT
    stale = patch_json(Client(), url, {"options": [{"id": "deadbeef", "name": "Х"}]},
                       **as_user(HEAD_IT))
    assert stale.status_code == 422


def test_delete_field_removes_values(org):
    field = _field(org, "Поле", "text")
    task = _assigned(org)
    _set(task, field["id"], "x")
    response = Client().delete(f"{BASE}/boards/fields/{field['id']}", **as_user(HEAD_IT))
    assert response.status_code == 204
    assert not TaskFieldValue.objects.filter(task=task).exists()
    assert _detail(task)["home_boards"][0]["fields"] == []


# ── карточка на доске ───────────────────────────────────────────────────

def test_board_card_shows_filled_fields_marked_for_card(org):
    stage = _field(org, "Этап", "list", show_on_card=True,
                   options=[{"name": "Стройка", "color": "orange"}])
    urgent = _field(org, "Срочно", "checkbox", show_on_card=True)
    hidden = _field(org, "Внутреннее", "text")
    task = _assigned(org)
    calm = _assigned(org)
    _set(task, stage["id"], stage["options"][0]["id"])
    _set(task, urgent["id"], True)
    _set(task, hidden["id"], "не на карточке")
    _set(calm, urgent["id"], False)
    body = Client().get(f"{BASE}/boards/departments/{org.it.id}", **as_user(EMP_IT)).json()
    cards = {card["id"]: card for column in body["columns"] for card in column["cards"]}
    badges = cards[task.pk]["fields"]
    assert [(badge["name"], badge["value"]) for badge in badges] == [
        ("Этап", stage["options"][0]["id"]), ("Срочно", True)]
    assert badges[0]["option"] == {"id": stage["options"][0]["id"], "name": "Стройка",
                                   "color": "orange"}
    assert cards[calm.pk]["fields"] == []


def test_board_query_count_with_fields(org, django_assert_max_num_queries):
    fields = [_field(org, f"Поле {index}", "text", show_on_card=True) for index in range(3)]
    for index in range(12):
        task = _assigned(org, status=[Status.TODO, Status.IN_PROGRESS][index % 2])
        task.labels.add(Label.objects.get_or_create(name=f"Метка {index % 3}")[0])
        for field in fields:
            TaskFieldValue.objects.create(task=task, field_id=field["id"], value_text="x")
    client = Client()
    headers = as_user(EMP_IT)
    client.get(f"{BASE}/boards/departments/{org.it.id}", **headers)
    with django_assert_max_num_queries(32):
        response = client.get(f"{BASE}/boards/departments/{org.it.id}", **headers)
    cards = [card for column in response.json()["columns"] for card in column["cards"]]
    assert len(cards) == 12 and all(len(card["fields"]) == 3 for card in cards)


# ── лента ───────────────────────────────────────────────────────────────

def test_feed_names_the_field(org):
    field = _field(org, "Причина ожидания", "text")
    task = _assigned(org)
    _set(task, field["id"], "Ждём смету")
    feed = Client().get(f"{BASE}/tasks/{task.pk}/feed", {"details": "1"},
                        **as_user(EMP_IT)).json()
    entry = next(item for item in feed["items"] if item.get("field") == f"field:{field['id']}")
    assert entry["board_field"] == {"id": field["id"], "name": "Причина ожидания", "type": "text"}
    assert entry["new"] == "Ждём смету"
    # Без подробностей значения полей не показываются.
    brief = Client().get(f"{BASE}/tasks/{task.pk}/feed", **as_user(EMP_IT)).json()
    assert all(item.get("field") != f"field:{field['id']}" for item in brief["items"])
    BoardField.objects.filter(pk=field["id"]).delete()
    feed = Client().get(f"{BASE}/tasks/{task.pk}/feed", {"details": "1"},
                        **as_user(EMP_IT)).json()
    entry = next(item for item in feed["items"] if item.get("field") == f"field:{field['id']}")
    assert entry["board_field"] == {"id": field["id"], "name": None, "type": None}


# ── шаблоны чек-листов ──────────────────────────────────────────────────

def _put_settings(org, body, who=HEAD_IT, url=None):
    return put_json(Client(), url or f"{BASE}/boards/departments/{org.it.id}/settings", body,
                    **as_user(who))


def test_templates_are_saved_without_touching_columns(org):
    _put_settings(org, {"columns": {"todo": {"title": "Ожидающие исполнения"}}})
    response = _put_settings(org, {"checklist_templates": [
        {"title": "Чек-лист", "items": ["Выполнить задачу", " Проверить ", "Сдать"]}]})
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["columns"]["todo"]["title"] == "Ожидающие исполнения"
    template = body["checklist_templates"][0]
    assert template["id"] and template["items"] == ["Выполнить задачу", "Проверить", "Сдать"]
    # Колонки без шаблонов — шаблоны остаются.
    body = _put_settings(org, {"columns": {}}).json()
    assert body["checklist_templates"] == [template]
    assert body["columns"]["todo"]["title"] is None
    renamed = _put_settings(org, {"checklist_templates": [
        {"id": template["id"], "title": "Приёмка", "items": []}]}).json()
    assert renamed["checklist_templates"][0]["id"] == template["id"]
    stale = _put_settings(org, {"checklist_templates": [{"id": "deadbeef", "title": "Х"}]})
    assert stale.status_code == 422
    assert _put_settings(org, {"checklist_templates": []}, who=EMP_IT).status_code == 403


def test_personal_board_has_no_templates(org):
    url = f"{BASE}/boards/personal/settings"
    response = _put_settings(org, {"checklist_templates": [{"title": "Мой"}]}, who=EMP_IT,
                             url=url)
    assert response.status_code == 422
    assert Client().get(url, **as_user(EMP_IT)).json()["checklist_templates"] == []


def test_checklist_from_template_copies_items(org):
    body = _put_settings(org, {"checklist_templates": [
        {"title": "Чек-лист", "items": ["Выполнить задачу", "Проверить", "Сдать"]}]}).json()
    template = body["checklist_templates"][0]
    task = _assigned(org)
    assert _detail(task)["home_boards"][0]["checklist_templates"] == [template]
    ref = {"board_kind": "department", "board_id": org.it.id, "template_id": template["id"]}
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/checklists",
                         {"title": "Чек-лист", "template": ref}, **as_user(EMP_IT))
    assert response.status_code == 201, response.content
    checklist = response.json()
    assert [item["text"] for item in checklist["items"]] == ["Выполнить задачу", "Проверить",
                                                             "Сдать"]
    assert checklist["total"] == 3 and checklist["done"] == 0
    assert TaskActivity.objects.filter(task=task, field_name="checklist_added").count() == 1
    # Шаблон не с домашней доски задачи — 422.
    sub = make_task(department_id=org.dev.id, assignee_id=EMP_DEV, reporter_id=HEAD_IT)
    TaskAssignee.objects.create(task=sub, user_id=EMP_DEV, role="primary")
    response = post_json(Client(), f"{BASE}/tasks/{sub.pk}/checklists",
                         {"title": "Чек-лист", "template": ref}, **as_user(EMP_DEV))
    assert response.status_code == 422
    assert not TaskChecklist.objects.filter(task=sub).exists()
    assert BoardSettings.objects.count() == 1
