"""Перенос ленты задач (``tasks.Notification`` в схеме компании) в центр."""

import pytest
from django.core.management import call_command

from apps.notifications.models import Delivery, Notification
from apps.tasks.models import Notification as OldNotification
from apps.tasks.models import Task


@pytest.mark.django_db
def test_old_rows_are_copied_once(company_context):
    old = OldNotification.objects.create(recipient_id=7, actor_id=8, verb="старое",
                                         target_type="task", target_id=3, is_read=True)
    call_command("notifications_import_tasks", "--company", company_context["slug"])
    call_command("notifications_import_tasks", "--company", company_context["slug"])
    row = Notification.objects.get()
    assert (row.title, row.target_id, row.is_read, row.company_slug, row.actor_id) == \
        ("старое", "3", True, company_context["slug"], 8)
    assert row.created_at == old.created_at  # дата сохраняется
    assert not Delivery.objects.exists()     # старое не рассылается заново


@pytest.mark.django_db
def test_legacy_task_fk_becomes_a_task_target(company_context):
    task = Task.objects.create(key="TASK-1", summary="S")
    OldNotification.objects.create(recipient_id=7, verb="task_assigned:TASK-1", task=task)
    call_command("notifications_import_tasks", "--company", company_context["slug"])
    row = Notification.objects.get()
    assert (row.target_type, row.target_id) == ("task", str(task.id))
