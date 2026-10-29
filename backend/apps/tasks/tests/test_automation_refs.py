"""Ссылки автоматизаций на удалённое (решение L-01; спецификация логики §10).

Своё поле, вариант списка и шаблон чек-листа доски нельзя удалить, пока на
них ссылается автоматизация этой доски (409 со списком). Метку компании,
ушедшего сотрудника, отдел и проект удалить можно — затронутые автоматизации
ломаются: выключаются с причиной и уведомляют администраторов доски. Движок
не вычисляет отсутствующую ссылку молча; сломанную включает только правка,
прошедшая проверку.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.hr.models import Department
from apps.notifications.models import Notification
from apps.tasks import schemas
from apps.tasks.models import (AutomationRule, AutomationRun, BoardField, BoardKind, Label,
                               Status)
from apps.tasks.services import board_service, project_service, reference_service, task_service
from apps.tasks.services.automation import refs
from apps.users.models import User, UserStatus

from .automation_helpers import add_rule, assigned_task, dept_board, label, members
from .helpers import BASE, COMPANY, patch_json, post_json, put_json
from .org_fixtures import EMP_DEV, EMP_IT, HEAD_IT, as_user, make_board, make_org

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    made = make_org()
    members(EMP_IT, EMP_DEV, HEAD_IT)
    return made


def _field(org, name="Причина", field_type="text", **extra) -> BoardField:
    response = post_json(Client(), f"{BASE}/boards/departments/{org.it.id}/fields",
                         {"name": name, "type": field_type, **extra}, **as_user(HEAD_IT))
    assert response.status_code == 201, response.content
    return BoardField.objects.get(pk=response.json()["id"])


def _broken(rule) -> str:
    rule.refresh_from_db()
    assert rule.enabled is False
    return rule.broken_reason


# ── своё поле, вариант, шаблон — не удаляются ───────────────────────────

def test_field_used_by_automation_cannot_be_deleted(org):
    field = _field(org)
    rule = add_rule(dept_board(org.it), {"type": "field_changed", "field_id": field.pk,
                                         "op": "set"}, [{"type": "set_start_today"}],
                    name="По полю")
    url = f"{BASE}/boards/fields/{field.pk}"
    response = Client().delete(url, **as_user(HEAD_IT))
    assert response.status_code == 409 and response.json()["code"] == "automation_ref_in_use"
    assert "«По полю»" in response.json()["detail"]
    rule.delete()
    assert Client().delete(url, **as_user(HEAD_IT)).status_code == 204


def test_list_option_used_by_automation_cannot_be_removed(org):
    field = _field(org, "Этап", "list", options=[{"name": "Стройка"}, {"name": "Сдача"}])
    build, handover = field.options
    add_rule(dept_board(org.it), {"type": "moved", "to_status": "done"},
             [{"type": "set_field", "field_id": field.pk, "value": handover["id"]}],
             name="Сдана — этап «Сдача»")
    url = f"{BASE}/boards/fields/{field.pk}"
    # Без варианта «Сдача» — нельзя; переименовать его — можно.
    response = patch_json(Client(), url, {"options": [build]}, **as_user(HEAD_IT))
    assert response.status_code == 409 and "«Сдача»" in response.json()["detail"]
    renamed = {**handover, "name": "Передача"}
    assert patch_json(Client(), url, {"options": [build, renamed]},
                      **as_user(HEAD_IT)).status_code == 200


def test_checklist_template_used_by_automation_cannot_be_removed(org):
    url = f"{BASE}/boards/departments/{org.it.id}/settings"
    response = put_json(Client(), url, {"checklist_templates": [
        {"title": "Приёмка", "items": ["Акт"]}]}, **as_user(HEAD_IT))
    assert response.status_code == 200, response.content
    template = response.json()["checklist_templates"][0]
    add_rule(dept_board(org.it), {"type": "card_created"},
             [{"type": "add_checklist", "title": "Приёмка", "template_id": template["id"]}],
             name="Новая — приёмка")
    response = put_json(Client(), url, {"checklist_templates": []}, **as_user(HEAD_IT))
    assert response.status_code == 409 and "«Приёмка»" in response.json()["detail"]


# ── метка, люди, отдел, проект — ломают автоматизацию ───────────────────

def test_deleted_label_breaks_automation_and_tells_the_admins(org):
    temporary = label("Временная (ссылки)")
    rule = add_rule(dept_board(org.it), {"type": "moved", "to_status": "done"},
                    [{"type": "add_label", "label_id": temporary.pk}], name="Метка при сдаче")
    reference_service.delete_label(temporary.pk)
    assert "Временная (ссылки)" in _broken(rule)
    assert Notification.objects.filter(recipient_id=HEAD_IT,
                                       title__contains="«Метка при сдаче» выключена").exists()
    url = f"{BASE}/boards/automation/{rule.pk}"
    # Включить сломанную без правки — нельзя.
    response = patch_json(Client(), url, {"enabled": True}, **as_user(HEAD_IT))
    assert response.status_code == 422 and response.json()["code"] == "automation_broken"
    # Правка, прошедшая проверку, снимает поломку.
    other = label("Другая (ссылки)")
    response = patch_json(Client(), url, {"actions": [{"type": "add_label", "label_id": other.pk}],
                                          "enabled": True}, **as_user(HEAD_IT))
    assert response.status_code == 200, response.content
    assert response.json()["broken_reason"] is None and response.json()["enabled"] is True


def test_label_missing_at_runtime_breaks_instead_of_guessing(org):
    """«Без метки X» с удалённой меткой — не «верно всегда», а поломка."""
    gone = label("Исчезнет (ссылки)")
    rule = add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
                    [{"type": "set_start_today"}],
                    [{"type": "has_label", "label_id": gone.pk, "negate": True}],
                    name="Без метки — начало")
    Label.objects.filter(pk=gone.pk).delete()            # мимо сервиса: ссылку не заметили
    task = assigned_task(org.it, EMP_IT)
    task_service.update_task(task.pk, schemas.TaskUpdate(status=Status.IN_PROGRESS),
                             user_id=EMP_IT)
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS and task.start_date is None
    assert _broken(rule)
    run = AutomationRun.objects.get(rule=rule, status="failed")
    assert run.details["error"].startswith("Автоматизация выключена")


def test_block_with_missing_field_breaks_and_lets_the_move_through(org):
    field = _field(org)
    rule = add_rule(dept_board(org.it), {"type": "moved", "to_status": "in_progress"},
                    [{"type": "block", "message": "Сначала заполните поле"}],
                    [{"type": "field", "field_id": field.pk, "op": "empty"}],
                    name="Запрет по полю")
    BoardField.objects.filter(pk=field.pk).delete()       # мимо сервиса
    task = assigned_task(org.it, EMP_IT)
    response = patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"status": "in_progress"},
                          **as_user(EMP_IT))
    assert response.status_code == 200, response.content
    assert _broken(rule)
    assert Notification.objects.filter(recipient_id=HEAD_IT,
                                       title__contains="«Запрет по полю» выключена").exists()


def test_deleted_project_breaks_its_board(org):
    project = make_board("REFS-1")
    board = board_service.board_for(BoardKind.PROJECT, project.pk)
    rule = add_rule(board, {"type": "card_created"}, [{"type": "set_start_today"}],
                    name="Проектное правило")
    project_service.delete_project(project.pk)
    assert _broken(rule) == "проект задач удалён"


def test_nightly_sweep_finds_people_who_left_and_departments_that_are_gone(org, monkeypatch):
    monkeypatch.setattr(refs, "current_company_or_none", lambda: COMPANY)
    notify = add_rule(dept_board(org.it), {"type": "moved", "to_status": "done"},
                      [{"type": "notify", "user_ids": [EMP_DEV], "text": "Готово"}],
                      name="Сообщить разработчику")
    temporary = Department.objects.create(name="Временный (ссылки)", path="kb_tmp_refs")
    orphan = add_rule(dept_board(temporary), {"type": "card_created"},
                      [{"type": "set_start_today"}], name="Правило временного отдела")
    assert refs.sweep() == 0
    User.objects.filter(pk=EMP_DEV).update(status=UserStatus.SUSPENDED)
    temporary.delete()
    assert refs.sweep() == 2
    assert "больше не работает в компании" in _broken(notify)
    assert _broken(orphan) == "отдела доски больше нет"
    assert refs.sweep() == 0                                # сломанные не трогаются повторно
    assert AutomationRule.objects.filter(broken_reason="").count() == 0
