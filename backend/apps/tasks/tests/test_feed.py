"""Лента карточки «Комментарии и события» (мастер-план канбана §6.4, этап S2).

Комментарии и журнал — одной хронологией, новые сверху; без подробностей —
комментарии и ключевые события; страницы по курсору не теряют и не дублируют
записи на стыке таблиц и при одинаковом времени; id людей и отделов в журнале
приходят с именами; невидимая задача — 404.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client
from django.utils import timezone

from apps.tasks.models import TaskActivity, TaskAssignee, TaskComment
from apps.users.models import User

from .helpers import BASE
from .org_fixtures import EMP_IT, HEAD_IT, OUTSIDER, as_user, make_org, make_task

pytestmark = pytest.mark.django_db

T0 = timezone.make_aware(dt.datetime(2026, 10, 20, 9, 0))


@pytest.fixture
def org():
    return make_org()


def _task():
    task = make_task(assignee_id=EMP_IT, reporter_id=HEAD_IT)
    TaskAssignee.objects.create(task=task, user_id=EMP_IT, role="primary")
    return task


def _comment(task, minutes, body):
    row = TaskComment.objects.create(task=task, author_id=EMP_IT, body=body)
    TaskComment.objects.filter(pk=row.pk).update(created_at=T0 + dt.timedelta(minutes=minutes))
    return row


def _event(task, minutes, field, old=None, new=None, actor=HEAD_IT):
    row = TaskActivity.objects.create(task=task, actor_id=actor, field_name=field,
                                      old_value=old, new_value=new)
    TaskActivity.objects.filter(pk=row.pk).update(created_at=T0 + dt.timedelta(minutes=minutes))
    return row


def _feed(task, who=EMP_IT, **params):
    return Client().get(f"{BASE}/tasks/{task.pk}/feed", params, **as_user(who))


def _summary(body):
    return [(item["kind"], item.get("body") or item.get("field")) for item in body["items"]]


def test_details_switch_hides_minor_events(org):
    task = _task()
    _comment(task, 1, "Первый комментарий")
    _event(task, 2, "status", "todo", "in_progress")
    _event(task, 3, "summary", "Старое", "Новое")
    _event(task, 4, "checklist_item_checked", None, "Пункт")
    short = _feed(task).json()
    assert _summary(short) == [("activity", "checklist_item_checked"),
                               ("activity", "status"),
                               ("comment", "Первый комментарий")]
    full = _feed(task, details="1").json()
    assert _summary(full) == [("activity", "checklist_item_checked"),
                              ("activity", "summary"),
                              ("activity", "status"),
                              ("comment", "Первый комментарий")]


def test_cursor_pages_without_gaps_or_duplicates(org):
    task = _task()
    # Одинаковое время у комментария и события — порядок решает вид и id.
    for minute in range(5):
        _comment(task, minute, f"к{minute}")
        _event(task, minute, "status", "todo", "in_progress")
    seen, before = [], None
    while True:
        params = {"limit": 3, "details": "1"}
        if before:
            params["before"] = before
        body = _feed(task, **params).json()
        seen.extend((item["kind"], item["id"]) for item in body["items"])
        before = body["next_before"]
        if not before:
            break
    assert len(seen) == 10 and len(set(seen)) == 10
    assert seen[0][0] == "comment"          # при равном времени «comment» > «activity»


def test_people_and_departments_come_with_names(org):
    # Имена — из учёток (``users``), а не из кадров: заводим учётку исполнителю.
    worker = User.objects.create(username="feed-worker", email="feed-worker@htq.test",
                                 password="x", first_name="Ерлан", last_name="Сапаров")
    task = _task()
    _event(task, 1, "assignee_id", None, str(worker.pk))
    _event(task, 2, "transfer", str(org.it.id), str(org.ops.id))
    body = _feed(task, details="1").json()
    transfer, assignee = body["items"]
    assert transfer["field"] == "transfer"
    assert transfer["old_label"] == org.it.name and transfer["new_label"] == org.ops.name
    assert assignee["new_label"] == "Ерлан Сапаров"
    assert assignee["actor"]["id"] == HEAD_IT


def test_access_events_name_the_requester(org):
    # «own:<id>» в журнале → имя запросившего: решает другой человек, и без
    # имени строка «запрос одобрен» не говорит, чей.
    requester = User.objects.create(username="feed-requester", email="feed-requester@htq.test",
                                    password="x", first_name="Айгерим", last_name="Нурланова")
    task = _task()
    _event(task, 1, "access_approved", None, f"own:{requester.pk}")
    (item,) = _feed(task).json()["items"]
    assert item["field"] == "access_approved" and item["new"] == f"own:{requester.pk}"
    assert item["new_label"] == "Айгерим Нурланова"


def test_invisible_task_is_404_and_bad_cursor_is_422(org):
    task = _task()
    assert _feed(task, who=OUTSIDER).status_code == 404
    response = _feed(task, before="не-курсор")
    assert response.status_code == 422 and response.json()["code"] == "feed_cursor_invalid"
