"""Лента задач живёт в центре уведомлений, контракт ручек прежний."""

import pytest
from django.test import Client

from apps.notifications.models import Delivery
from apps.notifications.models import Notification as CenterNotification
from apps.tasks import interface as tasks

from .helpers import BASE, COMPANY, auth


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)


@pytest.mark.django_db
def test_push_notification_writes_to_the_center(company_context):
    tasks.push_notification(recipient_id=7, actor_id=8, verb="вам написали",
                            target_type="chat", target_id=5)
    row = CenterNotification.objects.get()
    assert (row.recipient_id, row.title, row.target_type, row.target_id) == \
        (7, "вам написали", "chat", "5")
    assert row.company_slug == company_context["slug"]
    # только колокольчик, как было: письма о каждом сообщении нет
    assert not Delivery.objects.exists()


@pytest.mark.django_db
def test_dedupe_window_still_holds(company_context):
    first = tasks.push_notification(recipient_id=7, actor_id=8, verb="вам написали",
                                    target_type="chat", target_id=5)
    second = tasks.push_notification(recipient_id=7, actor_id=8, verb="вам написали",
                                     target_type="chat", target_id=5)
    assert first is not None and second is None
    assert CenterNotification.objects.count() == 1


@pytest.mark.django_db
def test_bell_endpoint_keeps_its_shape():
    CenterNotification.objects.create(recipient_id=7, company_slug=COMPANY, event="tasks.task",
                                      title="задача назначена", target_type="task")
    body = Client().get(f"{BASE}/notifications/", **auth()).json()
    assert body[0]["verb"] == "задача назначена"
    assert set(body[0]) >= {"id", "verb", "target_type", "target_id", "is_read",
                            "created_at", "task_key", "actor_name", "url"}
