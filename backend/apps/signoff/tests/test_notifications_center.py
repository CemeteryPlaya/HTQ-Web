"""Уведомления движка идут через центр уведомлений (мастер-план БЗО, B1.2 / A1.5).

Колокольчик фронта слушает события ``notification`` центра; прямые события
мессенджера ``signoff.*`` он не показывает — без центра согласующий их не
видел бы.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.core.models import ServiceStatus
from apps.notifications.models import Notification
from apps.signoff.models import Quorum
from apps.signoff.services import engine
from apps.signoff.tests.helpers import SUBJECT, make_doc, make_route, make_user
from apps.signoff.tests.testapp import hooks

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_calls():
    hooks.reset()
    yield
    hooks.reset()


def test_approver_gets_a_bell_notification_with_a_link():
    a = make_user("a")
    make_route([(1, "Первый", Quorum.ANY, [a.pk])])
    doc = make_doc()
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    row = Notification.objects.get(recipient_id=a.pk)
    assert row.event == "signoff.awaiting_you"
    assert row.title == f"{doc.title} ждёт вашего согласования"
    assert row.url == f"/probe/{doc.pk}"
    assert (row.target_type, row.target_id) == (SUBJECT, str(doc.pk))
    assert process.pk


def test_initiator_hears_the_outcome():
    a, author = make_user("a"), make_user("author")
    make_route([(1, "Первый", Quorum.ANY, [a.pk])])
    doc = make_doc()
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk, initiator_id=author.pk)
    task = process.stages.get().tasks.get()
    engine.act(task_id=task.pk, actor_id=a.pk, decision="approve")

    row = Notification.objects.get(recipient_id=author.pk)
    assert (row.event, row.title) == ("signoff.approved", f"{doc.title} — согласовано")


def test_disabled_center_falls_back_to_the_messenger():
    ServiceStatus.objects.update_or_create(
        app_label="notifications", defaults={"enabled": False, "message": "выключено"})
    a = make_user("a")
    make_route([(1, "Первый", Quorum.ANY, [a.pk])])
    with patch("apps.messenger.interface.dispatch_notification") as sent, \
            pytest.MonkeyPatch.context() as mp:
        mp.setattr("django.db.transaction.on_commit", lambda fn, *a, **k: fn())
        engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    assert not Notification.objects.exists()
    assert sent.call_args.args[1]["type"] == "signoff.awaiting_you"
