"""Contract tests for ``/api/tasks/v1/projects/*``.

Mirrors ``services/task/app/api/v1/projects.py`` and the metric aggregation
the ``ProjectRepository`` attached to each row.
"""

from unittest.mock import patch

import pytest
from django.test import Client

from apps.tasks.models import Project, ProjectStatus, Status, Task

from .helpers import BASE, admin_token, auth, patch_json, post_json

USER = 7
# helpers.admin_token() issues user_id=9 — the caller in every admin-gated
# case below (project creation, and editing a project one does not own).
ADMIN = 9


def _mk_task(project, status=Status.TODO, **over):
    return Task.objects.create(
        key=f"TASK-{Task.objects.count() + 1}", summary="S",
        project=project, status=status, **over)


@pytest.mark.django_db
def test_projects_require_auth():
    assert Client().get(f"{BASE}/projects/").status_code == 401


@pytest.mark.django_db
def test_create_project_defaults_owner_to_caller():
    resp = post_json(Client(), f"{BASE}/projects/", {"name": "Roadmap"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    body = resp.json()
    assert body["owner_id"] == ADMIN
    assert body["status"] == ProjectStatus.ACTIVE
    assert body["color"] == "#3b82f6"
    assert body["task_count"] == 0
    assert body["progress"] == 0.0


@pytest.mark.django_db
def test_create_project_respects_explicit_owner():
    resp = post_json(Client(), f"{BASE}/projects/",
                     {"name": "P", "owner_id": 55}, **auth(admin_token()))
    assert resp.json()["owner_id"] == 55


@pytest.mark.django_db
def test_project_name_must_be_unique():
    Project.objects.create(name="Dup")
    resp = post_json(Client(), f"{BASE}/projects/", {"name": "Dup"},
                     **auth(admin_token()))
    # A unique-violation is an unhandled DB error -> the 500 envelope, which
    # is exactly what the FastAPI original produced (it had no 409 branch).
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal Server Error"}


@pytest.mark.django_db
def test_progress_metrics_count_terminal_tasks():
    project = Project.objects.create(name="Metrics")
    _mk_task(project, Status.DONE)
    _mk_task(project, Status.CANCELLED)
    _mk_task(project, Status.TODO)
    _mk_task(project, Status.TODO, is_deleted=True)   # excluded

    resp = Client().get(f"{BASE}/projects/{project.id}/", **auth(admin_token()))
    body = resp.json()
    assert body["task_count"] == 3
    assert body["done_count"] == 2
    assert body["progress"] == 66.7          # rounded to 1dp, as in the original


@pytest.mark.django_db
def test_list_projects_orders_by_start_date_nulls_last():
    import datetime as dt
    Project.objects.create(name="no-date")
    Project.objects.create(name="early", start_date=dt.date(2026, 1, 1))
    Project.objects.create(name="late", start_date=dt.date(2026, 6, 1))
    resp = Client().get(f"{BASE}/projects/", **auth(admin_token()))
    assert [p["name"] for p in resp.json()] == ["early", "late", "no-date"]


@pytest.mark.django_db
def test_employee_scope_without_a_department_sees_nothing():
    """hr is still a stub, so ``employee_department_id`` degrades to None —
    the original returned an empty list in that case rather than widening
    the scope to everything."""
    Project.objects.create(name="Hidden", department_id=3)
    resp = Client().get(f"{BASE}/projects/", **auth())
    assert resp.json() == []


@pytest.mark.django_db
def test_employee_scope_sees_only_their_department():
    Project.objects.create(name="Mine", department_id=3)
    Project.objects.create(name="Theirs", department_id=9)
    with patch("apps.tasks.services.hydration.hr_interface.get_employee_brief",
               return_value={"id": USER, "department_id": 3}):
        resp = Client().get(f"{BASE}/projects/", **auth())
    assert [p["name"] for p in resp.json()] == ["Mine"]


@pytest.mark.django_db
def test_project_out_of_scope_is_404():
    project = Project.objects.create(name="Secret", department_id=9)
    with patch("apps.tasks.services.hydration.hr_interface.get_employee_brief",
               return_value={"id": USER, "department_id": 3}):
        resp = Client().get(f"{BASE}/projects/{project.id}/", **auth())
    assert resp.status_code == 404


@pytest.mark.django_db
def test_update_and_delete_project():
    """Editing now needs scope + ownership; the owner-who-is-not-admin case
    lives in test_permissions.py, where the department resolver is stubbed."""
    project = Project.objects.create(name="Old")
    resp = patch_json(Client(), f"{BASE}/projects/{project.id}/",
                      {"name": "New", "status": "archived"},
                      **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"

    assert Client().delete(f"{BASE}/projects/{project.id}/",
                           **auth(admin_token())).status_code == 204
    assert not Project.objects.filter(pk=project.id).exists()


@pytest.mark.django_db
def test_deleting_a_project_leaves_its_tasks_standalone():
    """FK is SET_NULL — the tasks survive without a project."""
    project = Project.objects.create(name="Doomed")
    task = _mk_task(project)
    Client().delete(f"{BASE}/projects/{project.id}/", **auth(admin_token()))
    task.refresh_from_db()
    assert task.project_id is None
    assert task.is_deleted is False


@pytest.mark.django_db
def test_project_tasks_endpoint():
    project = Project.objects.create(name="WithTasks")
    task = _mk_task(project)
    _mk_task(None)                       # standalone, must not appear
    resp = Client().get(f"{BASE}/projects/{project.id}/tasks/",
                        **auth(admin_token()))
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [task.id]


@pytest.mark.django_db
def test_project_tasks_404s_before_listing_when_out_of_scope():
    """The 404 must come from the project check, so this endpoint cannot be
    used to enumerate tasks of a project the caller may not see."""
    project = Project.objects.create(name="Secret", department_id=9)
    _mk_task(project)
    with patch("apps.tasks.services.hydration.hr_interface.get_employee_brief",
               return_value={"id": USER, "department_id": 3}):
        resp = Client().get(f"{BASE}/projects/{project.id}/tasks/", **auth())
    assert resp.status_code == 404


@pytest.mark.django_db
def test_project_detail_accepts_both_slash_spellings():
    project = Project.objects.create(name="Dual")
    for path in (f"{BASE}/projects/{project.id}",
                 f"{BASE}/projects/{project.id}/"):
        assert Client().get(path, **auth(admin_token())).status_code == 200


@pytest.mark.django_db
def test_owner_and_department_names_hydrate():
    Project.objects.create(name="Named", owner_id=11, department_id=3)
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=[{"id": 11, "username": "o", "email": "o@x",
                              "is_active": True, "full_name": "Оля Орлова"}]), \
         patch("apps.tasks.services.hydration.hr_interface.get_departments_brief",
               return_value=[{"id": 3, "name": "Логистика"}]):
        resp = Client().get(f"{BASE}/projects/", **auth(admin_token()))
    body = resp.json()[0]
    assert body["owner_name"] == "Оля Орлова"
    assert body["department_name"] == "Логистика"
