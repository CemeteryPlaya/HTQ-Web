"""Contract tests for ``/api/tasks/v1/notifications/*``.

Mirrors ``services/task/app/api/v1/notifications.py``. The recurring theme is
caller-scoping: a notification belongs to its recipient, and every route
must refuse another user's row with 404 rather than 403 (a 403 would confirm
the row exists).
"""

from unittest.mock import patch

import pytest
from django.test import Client

from apps.tasks.models import Notification, Task

from .helpers import BASE, auth, token

USER = 7
OTHER = 42


def _mk(recipient=USER, **over) -> Notification:
    fields = {"recipient_id": recipient, "verb": "task_assigned:TASK-1"}
    fields.update(over)
    return Notification.objects.create(**fields)


@pytest.mark.django_db
def test_notifications_require_auth():
    assert Client().get(f"{BASE}/notifications/").status_code == 401


@pytest.mark.django_db
def test_list_returns_only_the_callers_rows_newest_first():
    old = _mk()
    new = _mk()
    _mk(recipient=OTHER)
    resp = Client().get(f"{BASE}/notifications/", **auth())
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [new.id, old.id]


@pytest.mark.django_db
def test_list_respects_limit():
    for _ in range(3):
        _mk()
    assert len(Client().get(f"{BASE}/notifications/?limit=2",
                            **auth()).json()) == 2


@pytest.mark.django_db
def test_list_rejects_out_of_range_limit():
    assert Client().get(f"{BASE}/notifications/?limit=500",
                        **auth()).status_code == 422


@pytest.mark.django_db
def test_task_key_resolves_through_the_legacy_fk():
    task = Task.objects.create(key="TASK-9", summary="S")
    _mk(task=task)
    row = Client().get(f"{BASE}/notifications/", **auth()).json()[0]
    assert row["task_key"] == "TASK-9"


@pytest.mark.django_db
def test_task_key_resolves_through_the_generic_target():
    task = Task.objects.create(key="TASK-10", summary="S")
    _mk(target_type="task", target_id=task.id)
    row = Client().get(f"{BASE}/notifications/", **auth()).json()[0]
    assert row["task_key"] == "TASK-10"
    assert row["task_id"] is None


@pytest.mark.django_db
def test_non_task_target_leaves_task_key_null():
    _mk(target_type="employee", target_id=5)
    row = Client().get(f"{BASE}/notifications/", **auth()).json()[0]
    assert row["task_key"] is None
    assert row["target_type"] == "employee"


@pytest.mark.django_db
def test_actor_name_hydrates_and_avatar_snapshot_wins():
    """The stored snapshot is a point-in-time record and must not be
    overwritten by a live lookup."""
    _mk(actor_id=11, actor_avatar_url="https://old/avatar.png")
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=[{"id": 11, "username": "a", "email": "a@x",
                              "is_active": True, "full_name": "Актёр А",
                              "avatar_url": "https://new/avatar.png"}]):
        row = Client().get(f"{BASE}/notifications/", **auth()).json()[0]
    assert row["actor_name"] == "Актёр А"
    assert row["actor_avatar_url"] == "https://old/avatar.png"


# ── history ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_history_pagination_envelope():
    for _ in range(5):
        _mk()
    resp = Client().get(f"{BASE}/notifications/history/?page=1&limit=2",
                        **auth())
    body = resp.json()
    assert body["total"] == 5
    assert body["pages"] == 3
    assert body["page"] == 1
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert body["unread_total"] == 5


@pytest.mark.django_db
def test_history_status_filter_keeps_unread_total_stable():
    """The badge count ignores the active tab's filter — that is the whole
    reason ``unread_total`` is computed separately."""
    _mk(is_read=True)
    _mk(is_read=False)
    body = Client().get(f"{BASE}/notifications/history/?status=read",
                        **auth()).json()
    assert body["total"] == 1
    assert body["unread_total"] == 1


@pytest.mark.django_db
def test_history_target_type_filter():
    _mk(target_type="task")
    _mk(target_type="employee")
    body = Client().get(f"{BASE}/notifications/history/?target_type=employee",
                        **auth()).json()
    assert body["total"] == 1


@pytest.mark.django_db
def test_history_rejects_an_unknown_status():
    assert Client().get(f"{BASE}/notifications/history/?status=weird",
                        **auth()).status_code == 422


@pytest.mark.django_db
def test_history_is_empty_for_a_page_past_the_end():
    _mk()
    body = Client().get(f"{BASE}/notifications/history/?page=9", **auth()).json()
    assert body["items"] == []
    assert body["total"] == 1


# ── mutations ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_mark_read_and_unread():
    row = _mk()
    assert Client().post(f"{BASE}/notifications/{row.id}/mark_read/",
                         **auth()).status_code == 204
    row.refresh_from_db()
    assert row.is_read is True and row.read_at is not None

    assert Client().post(f"{BASE}/notifications/{row.id}/mark_unread/",
                         **auth()).status_code == 204
    row.refresh_from_db()
    assert row.is_read is False and row.read_at is None


@pytest.mark.django_db
def test_mark_all_read():
    _mk()
    _mk()
    _mk(recipient=OTHER)
    assert Client().post(f"{BASE}/notifications/mark-all-read/",
                         **auth()).status_code == 204
    assert Notification.objects.filter(recipient_id=USER,
                                       is_read=False).count() == 0
    # someone else's feed is untouched
    assert Notification.objects.filter(recipient_id=OTHER,
                                       is_read=False).count() == 1


@pytest.mark.django_db
def test_delete_notification():
    row = _mk()
    assert Client().delete(f"{BASE}/notifications/{row.id}/",
                           **auth()).status_code == 204
    assert not Notification.objects.filter(pk=row.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("method,suffix", [
    ("post", "/mark_read/"),
    ("post", "/mark_unread/"),
    ("delete", "/"),
])
def test_another_users_notification_is_404_not_403(method, suffix):
    """404, not 403 — a 403 would confirm the row exists."""
    row = _mk(recipient=OTHER)
    resp = getattr(Client(), method)(
        f"{BASE}/notifications/{row.id}{suffix}", **auth(token()))
    assert resp.status_code == 404
    assert Notification.objects.filter(pk=row.id).exists()
