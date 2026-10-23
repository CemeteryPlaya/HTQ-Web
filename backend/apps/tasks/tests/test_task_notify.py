"""Уведомления о задаче участникам и выключатель по доске (решения K-29,
K-30; мастер-план канбана §3.4; этап S2).

Получают только участники задачи, кроме автора события; кто просто видит
доску — ничего. Выключенная доска отдела гасит уведомления о задачах своего
поддерева, доска проекта — своих задач. Адресные события («вас назначили»)
доходят всегда. Заголовок — фраза, код события — в ссылке.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client

from apps.core.models import ServiceStatus

from apps.notifications.models import Notification
from apps.tasks.models import BoardKind, BoardNotificationMute, Status, TaskAssignee, TaskWatcher

from .helpers import BASE, patch_json, post_json, put_json
from .org_fixtures import (EMP_DEV, EMP_IT, HEAD_IT, OUTSIDER, TD, as_user, make_board,
                           make_org, make_task)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _team_task(department, **fields):
    """Исполнитель EMP_IT, автор HEAD_IT, руководитель TD, наблюдатель EMP_DEV."""
    task = make_task(department_id=department.id, assignee_id=EMP_IT, reporter_id=HEAD_IT,
                     supervisor_id=TD, status=Status.TODO, **fields)
    TaskAssignee.objects.create(task=task, user_id=EMP_IT, role="primary")
    TaskWatcher.objects.create(task=task, user_id=EMP_DEV)
    return task


def _recipients(event):
    return set(Notification.objects.filter(url__contains=f"event={event}")
               .values_list("recipient_id", flat=True))


def _status(task, status="in_progress", who=EMP_IT):
    return patch_json(Client(), f"{BASE}/tasks/{task.pk}/", {"status": status}, **as_user(who))


def test_status_change_goes_to_participants_except_the_actor(org):
    task = _team_task(org.it)
    assert _status(task).status_code == 200
    assert _recipients("status") == {HEAD_IT, TD, EMP_DEV}
    note = Notification.objects.filter(recipient_id=TD).get()
    assert note.title == f"Статус «В работе»: {task.key} «{task.summary}»"
    assert note.url == f"/tasks/board?card={task.pk}&event=status"


def test_board_viewer_who_is_not_a_participant_gets_nothing(org):
    task = make_task(department_id=org.it.id, reporter_id=HEAD_IT, assignee_id=EMP_IT)
    TaskAssignee.objects.create(task=task, user_id=EMP_IT, role="primary")
    _status(task)
    # OUTSIDER и прочие коллеги задачу видят или нет — неважно: не участники.
    assert OUTSIDER not in _recipients("status")
    assert _recipients("status") == {HEAD_IT}


def test_muted_department_board_covers_its_subtree(org):
    task = _team_task(org.dev)
    response = put_json(Client(), f"{BASE}/boards/departments/{org.it.id}/notifications",
                        {"enabled": False}, **as_user(TD))
    # TD не видит доску отдела it (не числится там) — 404, строка не пишется.
    assert response.status_code == 404
    response = put_json(Client(), f"{BASE}/boards/departments/{org.it.id}/notifications",
                        {"enabled": False}, **as_user(HEAD_IT))
    assert response.status_code == 200 and response.json() == {"enabled": False}
    _status(task)
    # HEAD_IT выключил доску родителя it — задача подотдела dev молчит для него.
    assert _recipients("status") == {TD, EMP_DEV}


def test_direct_assignment_ignores_the_switch(org):
    BoardNotificationMute.objects.create(board_kind=BoardKind.DEPARTMENT,
                                         board_id=org.it.id, user_id=EMP_DEV)
    task = make_task(department_id=org.it.id, reporter_id=HEAD_IT)
    patch_json(Client(), f"{BASE}/tasks/{task.pk}/assignees/",
               {"assignees": [{"user_id": EMP_DEV, "role": "primary"}]}, **as_user(HEAD_IT))
    note = Notification.objects.get(recipient_id=EMP_DEV)
    assert note.title.startswith("Вас назначили основным исполнителем:")


def test_muted_project_board(org):
    board = make_board("NTF-1", department=org.it)
    task = _team_task(org.it, project=board)
    BoardNotificationMute.objects.create(board_kind=BoardKind.PROJECT, board_id=board.pk,
                                         user_id=TD)
    _status(task)
    assert _recipients("status") == {HEAD_IT, EMP_DEV}


def test_comment_notifies_participants_with_excerpt(org):
    task = _team_task(org.it)
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/comments/",
                         {"body": "Проверил смету, есть вопросы"}, **as_user(HEAD_IT))
    assert response.status_code in (200, 201), response.content
    assert _recipients("comment") == {EMP_IT, TD, EMP_DEV}
    note = Notification.objects.get(recipient_id=TD)
    assert note.text == "Проверил смету, есть вопросы"


def test_claim_tells_participants_once(org):
    task = make_task(department_id=org.it.id, reporter_id=HEAD_IT, status=Status.TODO)
    response = post_json(Client(), f"{BASE}/tasks/{task.pk}/claim", {}, **as_user(EMP_IT))
    assert response.status_code == 200, response.content
    notes = Notification.objects.filter(recipient_id=HEAD_IT)
    assert notes.count() == 1 and notes.get().title.startswith("Взята в работу")


def test_switch_endpoints_and_board_flag(org):
    url = f"{BASE}/boards/departments/{org.it.id}"
    assert Client().get(url, **as_user(EMP_IT)).json()["board"]["notifications_enabled"] is True
    put_json(Client(), f"{url}/notifications", {"enabled": False}, **as_user(EMP_IT))
    assert Client().get(url, **as_user(EMP_IT)).json()["board"]["notifications_enabled"] is False
    muted = Client().get(f"{BASE}/boards/notifications", **as_user(EMP_IT)).json()
    assert muted == [{"board": {"kind": "department", "id": org.it.id, "title": org.it.name}}]
    # Повторное выключение идемпотентно, включение удаляет строку.
    put_json(Client(), f"{url}/notifications", {"enabled": False}, **as_user(EMP_IT))
    put_json(Client(), f"{url}/notifications", {"enabled": True}, **as_user(EMP_IT))
    assert not BoardNotificationMute.objects.filter(user_id=EMP_IT).exists()
    personal = Client().get(f"{BASE}/boards/personal", **as_user(EMP_IT)).json()
    assert personal["board"]["notifications_enabled"] is None


def test_disabled_notification_center_does_not_break_the_change(org):
    task = _team_task(org.it)
    ServiceStatus.objects.update_or_create(app_label="notifications", defaults={"enabled": False})
    cache.delete("svc-status:notifications")
    try:
        assert _status(task).status_code == 200
    finally:
        ServiceStatus.objects.update_or_create(app_label="notifications", defaults={"enabled": True})
        cache.delete("svc-status:notifications")
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS
    assert not Notification.objects.exists()
