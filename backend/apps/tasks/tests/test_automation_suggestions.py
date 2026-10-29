"""«Рекомендации» автоматизации (решение L-04; спецификация логики §15) —
личные, как в Trello: подсказки кнопок по МОИМ повторяющимся ручным действиям
на домашних задачах доски; «Добавить» — у администратора доски, «Скрыть» —
каждый для себя; образец, который закрывает кнопка доски, и правки
автоматизации подсказками не становятся.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.tasks.models import AutomationKind, Status
from apps.tasks.services.automation import suggestions

from .automation_helpers import add_rule, assigned_task, dept_board
from .helpers import BASE, patch_json, post_json
from .org_fixtures import EMP_IT, HEAD_IT, as_user, make_org

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _url(org) -> str:
    return f"{BASE}/boards/departments/{org.it.id}/automation/suggestions"


def _move_by_hand(org, times: int, who=EMP_IT):
    for _ in range(times):
        task = assigned_task(org.it, EMP_IT, status=Status.TODO)
        response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"status": "in_progress"},
                              **as_user(who))
        assert response.status_code == 200, response.content


def test_repeated_manual_moves_suggest_a_button(org):
    _move_by_hand(org, suggestions.THRESHOLD)
    body = Client().get(_url(org), **as_user(EMP_IT)).json()
    assert body["can_add"] is False
    [item] = body["items"]
    assert item["key"] == "move:in_progress" and item["count"] == suggestions.THRESHOLD
    assert item["actions"] == [{"type": "move", "status": "in_progress", "position": "top"}]
    # Подсказки личные: у главы отдела своих повторов нет.
    assert Client().get(_url(org), **as_user(HEAD_IT)).json() == {"items": [], "can_add": True}
    # «Скрыть» — больше не показывается.
    response = post_json(Client(), f"{_url(org)}/dismiss", {"key": "move:in_progress"},
                         **as_user(EMP_IT))
    assert response.status_code == 204
    assert Client().get(_url(org), **as_user(EMP_IT)).json()["items"] == []


def test_too_few_repeats_and_automation_moves_are_not_suggestions(org):
    _move_by_hand(org, suggestions.THRESHOLD - 1)
    assert Client().get(_url(org), **as_user(EMP_IT)).json()["items"] == []
    forward = add_rule(dept_board(org.it), {"type": "card_button"},
                       [{"type": "move", "status": "in_progress"}, {"type": "set_start_today"}],
                       kind=AutomationKind.CARD_BUTTON, name="Вперёд")
    for _ in range(suggestions.THRESHOLD):
        task = assigned_task(org.it, EMP_IT, status=Status.TODO)
        post_json(Client(), f"{BASE}/tasks/{task.pk}/buttons/{forward.pk}", {}, **as_user(EMP_IT))
    # Переносы кнопкой — правки автоматизации, а не мои руками.
    assert Client().get(_url(org), **as_user(EMP_IT)).json()["items"] == []


def test_admin_adds_the_suggested_button_and_it_stops_being_suggested(org):
    _move_by_hand(org, suggestions.THRESHOLD, who=HEAD_IT)
    body = Client().get(_url(org), **as_user(HEAD_IT)).json()
    assert body["can_add"] is True
    [item] = body["items"]
    response = post_json(Client(), f"{BASE}/boards/departments/{org.it.id}/automation", {
        "kind": "card_button", "name": item["name"], "icon": item["icon"],
        "trigger": {"type": "card_button"}, "actions": item["actions"]}, **as_user(HEAD_IT))
    assert response.status_code == 201, response.content
    assert Client().get(_url(org), **as_user(HEAD_IT)).json()["items"] == []
