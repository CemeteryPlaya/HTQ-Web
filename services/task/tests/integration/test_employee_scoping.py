"""Employee visibility rules for task lists, reports, and roadmaps."""

from datetime import datetime

import pytest
import pytest_asyncio

from app.models.department_replica import Department
from app.models.task import Status, Task
from app.models.user_replica import User
from app.models.project import Project
from tests.conftest import admin_headers, make_user_token, user_headers


@pytest_asyncio.fixture
async def scoped_data(session):
    dept_1 = Department(id=10, name="Engineering")
    dept_2 = Department(id=20, name="Finance")
    employee = User(
        id=2,
        username="employee",
        email="employee@example.com",
        first_name="Regular",
        last_name="Employee",
        department_id=10,
        is_active=True,
    )
    other_employee = User(
        id=3,
        username="other",
        email="other@example.com",
        first_name="Other",
        last_name="Employee",
        department_id=20,
        is_active=True,
    )
    no_department = User(
        id=4,
        username="floating",
        email="floating@example.com",
        first_name="Floating",
        last_name="Employee",
        department_id=None,
        is_active=True,
    )
    session.add_all([dept_1, dept_2, employee, other_employee, no_department])
    await session.flush()

    project_1 = Project(name="Eng roadmap", department_id=10)
    project_2 = Project(name="Finance roadmap", department_id=20)
    session.add_all([project_1, project_2])
    await session.flush()

    now = datetime.utcnow()
    tasks = [
        Task(
            key="TASK-1",
            summary="Employee done",
            status=Status.DONE,
            assignee_id=2,
            reporter_id=2,
            department_id=10,
            project_id=project_1.id,
            completed_at=now,
        ),
        Task(
            key="TASK-2",
            summary="Employee closed",
            status=Status.CANCELLED,
            assignee_id=2,
            reporter_id=2,
            department_id=10,
            project_id=project_1.id,
            completed_at=now,
        ),
        Task(
            key="TASK-3",
            summary="Employee active",
            status=Status.IN_PROGRESS,
            assignee_id=2,
            reporter_id=2,
            department_id=10,
            project_id=project_1.id,
        ),
        Task(
            key="TASK-4",
            summary="New department task",
            status=Status.TODO,
            assignee_id=None,
            reporter_id=3,
            department_id=10,
            project_id=project_1.id,
        ),
        Task(
            key="TASK-5",
            summary="Assigned same department task",
            status=Status.TODO,
            assignee_id=3,
            reporter_id=3,
            department_id=10,
            project_id=project_1.id,
        ),
        Task(
            key="TASK-6",
            summary="Other done",
            status=Status.DONE,
            assignee_id=3,
            reporter_id=3,
            department_id=20,
            project_id=project_2.id,
            completed_at=now,
        ),
        Task(
            key="TASK-7",
            summary="Other department open",
            status=Status.TODO,
            assignee_id=None,
            reporter_id=3,
            department_id=20,
            project_id=project_2.id,
        ),
    ]
    session.add_all(tasks)
    await session.commit()
    return {"project_1": project_1.id, "project_2": project_2.id}


@pytest.mark.asyncio
async def test_admin_sees_unscoped_task_list(client, scoped_data):
    resp = await client.get("/api/tasks/v1/tasks/?limit=100", headers=admin_headers())

    assert resp.status_code == 200
    keys = {item["key"] for item in resp.json()}
    assert keys == {"TASK-1", "TASK-2", "TASK-3", "TASK-4", "TASK-5", "TASK-6", "TASK-7"}


@pytest.mark.asyncio
async def test_employee_reports_include_completed_own_and_new_department_tasks(client, scoped_data):
    resp = await client.get("/api/tasks/v1/tasks/stats/", headers=user_headers())

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["by_status"] == {"cancelled": 1, "done": 1, "todo": 1}


@pytest.mark.asyncio
async def test_employee_task_list_excludes_other_department_and_assigned_department_work(client, scoped_data):
    resp = await client.get("/api/tasks/v1/tasks/?limit=100", headers=user_headers())

    assert resp.status_code == 200
    keys = {item["key"] for item in resp.json()}
    assert keys == {"TASK-1", "TASK-2", "TASK-3", "TASK-4"}


@pytest.mark.asyncio
async def test_employee_roadmap_and_project_tasks_are_department_scoped(client, scoped_data):
    projects = await client.get("/api/tasks/v1/projects/", headers=user_headers())
    assert projects.status_code == 200
    assert [item["name"] for item in projects.json()] == ["Eng roadmap"]

    hidden = await client.get(
        f"/api/tasks/v1/projects/{scoped_data['project_2']}/",
        headers=user_headers(),
    )
    assert hidden.status_code == 404

    project_tasks = await client.get(
        f"/api/tasks/v1/projects/{scoped_data['project_1']}/tasks/",
        headers=user_headers(),
    )
    assert project_tasks.status_code == 200
    keys = {item["key"] for item in project_tasks.json()}
    assert keys == {"TASK-1", "TASK-2", "TASK-3", "TASK-4", "TASK-5"}


@pytest.mark.asyncio
async def test_employee_without_department_does_not_fall_back_to_all_department_data(client, scoped_data):
    headers = {"Authorization": f"Bearer {make_user_token(user_id=4)}"}

    stats = await client.get("/api/tasks/v1/tasks/stats/", headers=headers)
    assert stats.status_code == 200
    assert stats.json()["total"] == 0

    versions = await client.get("/api/tasks/v1/versions/", headers=headers)
    assert versions.status_code == 200
    assert versions.json() == []
