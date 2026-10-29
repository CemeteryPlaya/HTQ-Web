"""Ручки автоматизации досок (этап S4): каталог, список и правка автоматизаций,
журнал запусков, кнопки в карточке задачи, шаблон процесса.

Список видит тот, кто видит доску; правит и читает журнал — администратор
доски (K-39). Создание, правка и удаление — строки журнала «было → стало».
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.tasks.models import AutomationRule, AutomationRun, Status
from apps.tasks.services.automation import rules

from .automation_helpers import add_rule, assigned_task, dept_board, label
from .helpers import BASE, patch_json, post_json
from .org_fixtures import EMP_IT, HEAD_IT, OUTSIDER, TD, as_user, make_board, make_org

pytestmark = pytest.mark.django_db

RULE = {"kind": "rule", "name": "В работе — срок через 3 дня",
        "trigger": {"type": "moved", "to_status": "in_progress"},
        "actions": [{"type": "set_due", "mode": "in_days", "days": 3}]}


@pytest.fixture
def org():
    return make_org()


def _url(org, suffix=""):
    return f"{BASE}/boards/departments/{org.it.id}/automation{suffix}"


def _create(org, body=None, who=HEAD_IT):
    return post_json(Client(), _url(org), body or RULE, **as_user(who))


def test_catalog_endpoint(org):
    response = Client().get(f"{BASE}/automation/catalog", **as_user(EMP_IT))
    assert response.status_code == 200
    assert {"triggers", "conditions", "actions", "kinds", "limits"} <= set(response.json())


def test_create_needs_board_admin_and_list_needs_visibility(org):
    assert _create(org, who=EMP_IT).status_code == 403
    response = _create(org)
    assert response.status_code == 201, response.content
    created = response.json()
    assert created["kind"] == "rule" and created["enabled"] is True and created["position"]
    listed = Client().get(_url(org), **as_user(EMP_IT))
    assert listed.status_code == 200 and [row["id"] for row in listed.json()] == [created["id"]]
    assert Client().get(_url(org), {"kind": "card_button"}, **as_user(EMP_IT)).json() == []
    assert Client().get(_url(org), **as_user(OUTSIDER)).status_code == 404
    changed = AutomationRun.objects.get(rule_id=created["id"], status="changed")
    assert changed.event == "created" and changed.actor_id == HEAD_IT


def test_invalid_automation_explains(org):
    response = _create(org, {**RULE, "actions": [{"type": "fly"}]})
    assert response.status_code == 422 and response.json()["code"] == "automation_invalid"
    response = _create(org, {"kind": "card_button", "trigger": {"type": "card_button"},
                             "actions": [{"type": "complete"}]})
    assert response.status_code == 422 and "Назовите кнопку" in response.json()["detail"]


def test_limit(org, monkeypatch):
    monkeypatch.setattr(rules, "AUTOMATION_LIMIT", 1)
    assert _create(org).status_code == 201
    response = _create(org)
    assert response.status_code == 422 and response.json()["code"] == "automation_limit"


def test_patch_rename_disable_reorder_and_log(org):
    first, second, third = (_create(org).json() for _ in range(3))
    url = f"{BASE}/boards/automation/{third['id']}"
    response = patch_json(Client(), url, {"name": "Новое имя", "enabled": False,
                                          "before_id": None, "after_id": first["id"]},
                          **as_user(HEAD_IT))
    assert response.status_code == 200, response.content
    order = [row["id"] for row in Client().get(_url(org), **as_user(HEAD_IT)).json()]
    assert order == [third["id"], first["id"], second["id"]]
    rule = AutomationRule.objects.get(pk=third["id"])
    assert rule.name == "Новое имя" and rule.enabled is False
    log = AutomationRun.objects.filter(rule=rule, event="updated").get()
    assert log.details["before"]["name"] == RULE["name"]
    assert log.details["after"]["enabled"] is False
    stale = patch_json(Client(), url, {"before_id": second["id"], "after_id": first["id"]},
                       **as_user(HEAD_IT))
    assert stale.status_code == 409 and stale.json()["code"] == "automation_order_stale"
    bad = patch_json(Client(), url, {"actions": []}, **as_user(HEAD_IT))
    assert bad.status_code == 422
    assert patch_json(Client(), url, {"name": "x"}, **as_user(EMP_IT)).status_code == 403


def test_copy_is_disabled_and_delete_keeps_the_log(org):
    created = _create(org).json()
    copy = post_json(Client(), f"{BASE}/boards/automation/{created['id']}/copy", {},
                     **as_user(HEAD_IT))
    assert copy.status_code == 201
    assert copy.json()["enabled"] is False and copy.json()["name"].endswith("(копия)")
    response = Client().delete(f"{BASE}/boards/automation/{created['id']}", **as_user(HEAD_IT))
    assert response.status_code == 204
    assert not AutomationRule.objects.filter(pk=created["id"]).exists()
    deleted = AutomationRun.objects.get(event="deleted")
    assert deleted.rule_id is None and deleted.rule_name == RULE["name"]


def test_runs_are_for_admin_with_filters(org):
    # Колонку триггер не задаёт: перенос «В работе → Бэклог» невозможен
    # только на месте — правило сохраняется и падает при выполнении.
    marker = label("Метка-триггер (журнал)")
    rule = add_rule(dept_board(org.it), {"type": "label_added", "label_id": marker.pk},
                    [{"type": "move", "status": "backlog"}], name="Сломанное")
    task = assigned_task(org.it, EMP_IT, status=Status.IN_PROGRESS)
    patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"label_ids": [marker.pk]},
               **as_user(HEAD_IT))
    runs_url = _url(org, "/runs")
    assert Client().get(runs_url, **as_user(EMP_IT)).status_code == 403
    body = Client().get(runs_url, {"problems": "1"}, **as_user(HEAD_IT)).json()
    assert [item["status"] for item in body["items"]] == ["failed"]
    assert body["items"][0]["task"]["key"] == task.key
    assert body["items"][0]["rule_name"] == "Сломанное"
    page = Client().get(runs_url, {"limit": "1"}, **as_user(HEAD_IT)).json()
    assert len(page["items"]) == 1 and page["next_before"]
    rest = Client().get(runs_url, {"before": page["next_before"], "rule": rule.pk},
                        **as_user(HEAD_IT)).json()
    assert all(item["rule_id"] == rule.pk for item in rest["items"])


def test_card_detail_lists_buttons_of_home_boards(org):
    take = _create(org, {"kind": "card_button", "name": "Взять в работу", "icon": "arrow-right",
                         "trigger": {"type": "card_button"},
                         "actions": [{"type": "move", "status": "in_progress"}]}).json()
    _create(org, {"kind": "card_button", "name": "Выключенная", "enabled": False,
                  "trigger": {"type": "card_button"}, "actions": [{"type": "complete"}]})
    task = assigned_task(org.it, EMP_IT)
    detail = Client().get(f"{BASE}/tasks/{task.pk}", **as_user(EMP_IT)).json()
    assert detail["home_boards"][0]["buttons"] == [
        {"id": take["id"], "name": "Взять в работу", "icon": "arrow-right",
         "available": True, "reason": None}]
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/buttons/{take['id']}", {},
                         **as_user(EMP_IT))
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS


def test_project_owner_administers_project_automation(org):
    board = make_board("KB-AUT2", department=org.it)
    board.owner_id = TD
    board.save(update_fields=["owner_id"])
    url = f"{BASE}/boards/projects/{board.pk}/automation"
    assert post_json(Client(), url, RULE, **as_user(TD)).status_code == 201
    assert post_json(Client(), url, RULE, **as_user(HEAD_IT)).status_code == 403


def test_preset_endpoint_is_for_board_admin(org):
    url = f"{BASE}/boards/departments/{org.it.id}/preset"
    assert post_json(Client(), url, {"preset": "htq_process"}, **as_user(EMP_IT)).status_code == 403
    # Пробный прогон (этап S4b): тот же отчёт, в базе — ничего.
    dry = post_json(Client(), url, {"preset": "htq_process", "dry_run": True}, **as_user(HEAD_IT))
    assert dry.status_code == 200 and dry.json()["dry_run"] is True
    assert len(dry.json()["automations"]["created"]) == 27
    assert not AutomationRule.objects.filter(board_id=org.it.id).exists()
    response = post_json(Client(), url, {"preset": "htq_process"}, **as_user(HEAD_IT))
    assert response.status_code == 200, response.content
    assert len(response.json()["automations"]["created"]) == 27
    assert post_json(Client(), url, {"preset": "nope"}, **as_user(HEAD_IT)).status_code == 422
