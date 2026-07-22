"""Projects — the Roadmap-level grouping of tasks.

Ported from ``services/task/app/api/v1/projects.py`` and the
``ProjectRepository``. ``task_count`` / ``done_count`` / ``progress`` were
``ClassVar`` scratch-space stamped onto the SQLAlchemy instance by the
repository; here they are computed into the response payload instead, which
is what they always were semantically.
"""

from __future__ import annotations

from django.db.models import Case, Count, F, IntegerField, Sum, When
from django.http import Http404

from .. import schemas
from ..models import TERMINAL_STATUSES, Project, Task
from . import hydration


def scope_for(token) -> tuple[bool, int | None]:
    """``(employee_scope, department_id)`` — elevated callers see everything."""
    if token.is_elevated:
        return False, None
    return True, hydration.employee_department_id(token.user_id)


def _visible(employee_scope: bool, department_id: int | None):
    qs = Project.objects.all()
    if employee_scope:
        if department_id is None:
            # No resolvable department -> nothing is in scope. The original
            # returned an empty list rather than falling back to "all".
            return Project.objects.none()
        qs = qs.filter(department_id=department_id)
    return qs


def list_projects(*, employee_scope: bool,
                  department_id: int | None) -> list[Project]:
    # start_date ASC NULLS LAST, then newest first — projects with no start
    # date sort to the bottom (the original's ``.asc().nulls_last()``).
    return list(_visible(employee_scope, department_id)
                .order_by(F("start_date").asc(nulls_last=True), "-created_at"))


def get_project(project_id: int, *, employee_scope: bool,
                department_id: int | None) -> Project:
    project = _visible(employee_scope, department_id).filter(
        pk=project_id).first()
    if project is None:
        raise Http404("Project not found")
    return project


def create_project(payload: dict, *, creator_id: int | None) -> Project:
    if payload.get("owner_id") is None:
        payload["owner_id"] = creator_id
    return Project.objects.create(**payload)


def update_project(project_id: int, changes: dict) -> Project:
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise Http404("Project not found")
    for field, value in changes.items():
        setattr(project, field, value)
    project.save()
    return project


def delete_project(project_id: int) -> None:
    """Tasks keep existing and lose their project link (FK is SET_NULL)."""
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise Http404("Project not found")
    project.delete()


def _metrics(project_ids: list[int]) -> dict[int, dict]:
    rows = (Task.objects.filter(is_deleted=False, project_id__in=project_ids)
            .values("project_id")
            .annotate(
                task_count=Count("id", distinct=True),
                done_count=Sum(Case(
                    When(status__in=list(TERMINAL_STATUSES), then=1),
                    default=0, output_field=IntegerField())),
            ))
    return {row["project_id"]: row for row in rows}


def build_responses(projects: list[Project]) -> list[schemas.ProjectResponse]:
    """One hydration pass and one metrics query for the whole batch."""
    metrics = _metrics([p.id for p in projects])
    users = hydration.user_briefs([p.owner_id for p in projects])
    departments = hydration.department_briefs(
        [p.department_id for p in projects])

    out = []
    for project in projects:
        counts = metrics.get(project.id, {})
        task_count = int(counts.get("task_count") or 0)
        done_count = int(counts.get("done_count") or 0)
        out.append(schemas.ProjectResponse.model_validate({
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "color": project.color,
            "start_date": project.start_date,
            "end_date": project.end_date,
            "owner_id": project.owner_id,
            "owner_name": hydration.user_name(users, project.owner_id),
            "department_id": project.department_id,
            "department_name": hydration.department_name(
                departments, project.department_id),
            "task_count": task_count,
            "done_count": done_count,
            "progress": (round(done_count / task_count * 100, 1)
                         if task_count else 0.0),
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }))
    return out


def build_response(project: Project) -> schemas.ProjectResponse:
    return build_responses([project])[0]
