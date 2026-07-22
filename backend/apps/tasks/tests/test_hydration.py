"""Cross-app hydration and its degradation contract (PLAN.md §7).

Поток B consumes ``apps.hr`` and ``apps.users`` through their interfaces.
§7 makes degradation a hard requirement for a consumer: a disabled or
unavailable neighbour must cost the enrichment, never the request. These
tests are the consumer-side proof of that, and they are what lets this
domain ship before Поток A has implemented ``apps.hr.interface`` at all.
"""

from unittest.mock import patch

import pytest
from django.test import Client

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.tasks.models import Task, TaskAssignee
from apps.tasks.services import hydration

from .helpers import BASE, admin_token, auth

USER = 7


def _mk_task(**over) -> Task:
    fields = {"key": "TASK-1", "summary": "S", "reporter_id": USER}
    fields.update(over)
    return Task.objects.create(**fields)


# ── batching ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_user_briefs_issues_one_call_for_the_whole_batch():
    """The N+1-across-an-app-boundary guard. The replicas existed to avoid
    exactly this cost; if hydration ever loops, the port has regressed."""
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=[]) as mock:
        hydration.user_briefs([1, 2, 3, 2, None, 1])
    mock.assert_called_once()
    # de-duplicated and sorted, so the call is stable and cache-friendly
    assert mock.call_args[0][0] == [1, 2, 3]


@pytest.mark.django_db
def test_task_list_query_count_does_not_grow_with_the_result_set():
    """The end-to-end proof of the batching design (added in the phase-4
    final review).

    The deleted replicas existed to make ``assignee_name`` a JOIN. Their
    replacement is one batched interface call per request — so the query
    count for ``GET /tasks/`` must be flat, not proportional to the number of
    tasks. Asserted as "same cost for 15 rows as for 3" rather than a fixed
    number, so adding a legitimate query does not fail the test spuriously
    while a reintroduced N+1 still does.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.tasks.models import Label, TaskAssignee

    label = Label.objects.create(name="ops")

    def make(count):
        start = Task.objects.count()
        for i in range(start, start + count):
            task = Task.objects.create(
                key=f"TASK-{i}", summary=f"s{i}", assignee_id=100 + i,
                reporter_id=200 + i, supervisor_id=300 + i, department_id=i)
            TaskAssignee.objects.create(task=task, user_id=100 + i)
            task.labels.add(label)

    hdr = auth(admin_token())
    make(3)
    Client().get(f"{BASE}/tasks/", **hdr)          # warm the service-gate cache
    with CaptureQueriesContext(connection) as few:
        Client().get(f"{BASE}/tasks/", **hdr)

    make(12)
    with CaptureQueriesContext(connection) as many:
        assert len(Client().get(f"{BASE}/tasks/", **hdr).json()) == 15

    assert len(many.captured_queries) == len(few.captured_queries), (
        f"N+1 reintroduced: {len(few.captured_queries)} queries for 3 tasks, "
        f"{len(many.captured_queries)} for 15"
    )


@pytest.mark.django_db
def test_user_briefs_skips_the_call_entirely_when_there_are_no_ids():
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief") as mock:
        assert hydration.user_briefs([None, None]) == {}
    mock.assert_not_called()


# ── degradation ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_hydration_degrades_when_neighbour_is_disabled():
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               side_effect=ServiceDisabled("users", "off")):
        assert hydration.user_briefs([1]) == {}


@pytest.mark.django_db
def test_hydration_degrades_while_hr_is_still_a_prep_stub():
    """``apps.hr.interface`` raises NotImplementedError until Поток A fills
    it in (PLAN.md §6.3). That must read as "no enrichment", not a 500."""
    assert hydration.department_briefs([1, 2]) == {}
    assert hydration.employee_department_id(USER) is None


@pytest.mark.django_db
def test_hydration_degrades_on_an_unexpected_neighbour_error():
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               side_effect=RuntimeError("boom")):
        assert hydration.user_briefs([1]) == {}


@pytest.mark.django_db
def test_task_list_still_serves_when_users_is_disabled():
    """End-to-end version of the rule: the request succeeds, only the
    denormalised name is missing."""
    _mk_task(assignee_id=11)
    ServiceStatus.objects.update_or_create(app_label="users",
                                           defaults={"enabled": False})
    resp = Client().get(f"{BASE}/tasks/", **auth(admin_token()))
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["assignee_id"] == 11        # the id is local, always present
    assert row["assignee_name"] is None    # the name degraded away


@pytest.mark.django_db
def test_task_detail_still_serves_when_hr_is_disabled():
    task = _mk_task(department_id=3)
    ServiceStatus.objects.update_or_create(app_label="hr",
                                           defaults={"enabled": False})
    resp = Client().get(f"{BASE}/tasks/{task.id}/", **auth())
    assert resp.status_code == 200
    assert resp.json()["department_id"] == 3
    assert resp.json()["department_name"] is None


# ── enrichment, when the neighbour answers ──────────────────────────────

@pytest.mark.django_db
def test_names_are_filled_from_the_users_interface():
    task = _mk_task(assignee_id=11, supervisor_id=12)
    TaskAssignee.objects.create(task=task, user_id=11)
    briefs = [
        {"id": 11, "username": "ivanov", "email": "i@x", "is_active": True,
         "full_name": "Иван Иванов"},
        {"id": 12, "username": "petrov", "email": "p@x", "is_active": True,
         "full_name": "Пётр Петров"},
    ]
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=briefs):
        resp = Client().get(f"{BASE}/tasks/{task.id}/", **auth())
    body = resp.json()
    assert body["assignee_name"] == "Иван Иванов"
    assert body["supervisor_name"] == "Пётр Петров"
    assert body["assignees"][0]["name"] == "Иван Иванов"


@pytest.mark.django_db
def test_department_names_are_filled_from_the_hr_interface():
    task = _mk_task(department_id=3)
    with patch("apps.tasks.services.hydration.hr_interface.get_departments_brief",
               return_value=[{"id": 3, "name": "Логистика"}]):
        resp = Client().get(f"{BASE}/tasks/{task.id}/", **auth())
    assert resp.json()["department_name"] == "Логистика"


@pytest.mark.django_db
def test_unknown_ids_hydrate_to_none_rather_than_raising():
    """The interface omits ids it cannot resolve; a deleted user must render
    as a null name, the same result a lagging replica gave the original."""
    task = _mk_task(assignee_id=404)
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=[]):
        resp = Client().get(f"{BASE}/tasks/{task.id}/", **auth())
    assert resp.json()["assignee_name"] is None


@pytest.mark.django_db
def test_avatar_url_is_none_until_the_users_brief_carries_one():
    """Documents the known §7 gap: the response field exists, the agreed
    users brief has no avatar, and a consumer may not reach past the
    interface. Update this test when the brief is extended by agreement —
    ``hydration.user_avatar`` already reads the key."""
    task = _mk_task()
    TaskAssignee.objects.create(task=task, user_id=11)
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=[{"id": 11, "username": "u", "email": "e",
                              "is_active": True, "full_name": "U"}]):
        resp = Client().get(f"{BASE}/tasks/{task.id}/", **auth())
    assert resp.json()["assignees"][0]["avatar_url"] is None
