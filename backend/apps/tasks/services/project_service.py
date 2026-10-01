"""Projects — the top level of the work hierarchy.

Ниже проекта: объекты (``site_service``), на объектах пакеты работ
(``roadmap_service``), в пакетах задачи. Заголовок раньше говорил
«Roadmap-level grouping of tasks» — до появления ``Roadmap`` отдельной
таблицей это было верно, теперь роудмап это соседний модуль.

Ported from ``services/task/app/api/v1/projects.py`` and the
``ProjectRepository``. ``task_count`` / ``done_count`` / ``progress`` were
``ClassVar`` scratch-space stamped onto the SQLAlchemy instance by the
repository; here they are computed into the response payload instead, which
is what they always were semantically.
"""

from __future__ import annotations

import operator
from functools import reduce

from django.db.models import Case, Count, F, IntegerField, Q, Sum, When

from htqweb import date_rules
from django.http import Http404

from .. import schemas
from ..models import TERMINAL_STATUSES, Project, ProjectSite, Task
from . import board_scope
from . import hydration
from . import project_link
from . import site_service


def scope_for(token) -> tuple[bool, int | None]:
    """``(employee_scope, department_id)`` — elevated callers see everything."""
    if token.is_elevated:
        return False, None
    return True, hydration.employee_department_id(token.user_id)


def _visible(employee_scope: bool, department_id: int | None, refs=None):
    """Доски в зоне видимости. ``refs`` — доски «Проектов» держателя «Доски
    задач проекта» (``board_scope.board_refs_for``), в добавок к отделу."""
    qs = Project.objects.all()
    if not employee_scope:
        return qs
    conds = [Q(department_id=department_id)] if department_id is not None else []
    linked = board_scope.board_q(refs)
    if linked is not None:
        conds.append(linked)
    if not conds:
        # No resolvable department -> nothing is in scope. The original
        # returned an empty list rather than falling back to "all".
        return Project.objects.none()
    return qs.filter(reduce(operator.or_, conds))


def list_projects(*, employee_scope: bool, department_id: int | None, refs=None,
                  project_ref: str | None = None) -> list[Project]:
    qs = _visible(employee_scope, department_id, refs)
    if project_ref:
        # Доска «Проекта» — для ссылки с его карточки (одна на проект).
        qs = qs.filter(project_ref=project_ref)
    # start_date ASC NULLS LAST, then newest first — projects with no start
    # date sort to the bottom (the original's ``.asc().nulls_last()``).
    return list(qs.order_by(F("start_date").asc(nulls_last=True), "-created_at"))


def get_project(project_id: int, *, employee_scope: bool,
                department_id: int | None, refs=None) -> Project:
    project = _visible(employee_scope, department_id, refs).filter(
        pk=project_id).first()
    if project is None:
        raise Http404("Project not found")
    return project


def create_project(payload: dict) -> Project:
    """Доска — только к «Проекту» БЗО; владелец — его руководитель
    (``project_link.create_linked``). Прежнее «владелец — создатель» ушло
    вместе с правом доски на собственное название и сроки."""
    return project_link.create_linked(payload)


def update_project(project_id: int, changes: dict) -> Project:
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise Http404("Project not found")
    changes = project_link.strip_mirrored(project, changes)
    for field, value in changes.items():
        setattr(project, field, value)
    # По СЛИТОЙ паре, а не по присланным полям: в PATCH может приехать одна
    # дата, вторая лежит в строке. У проекта, в отличие от блока и роудмапа,
    # нет даже CheckConstraint — до этой проверки перепутанные даты просто
    # сохранялись.
    # TODO: добавить ck_project_dates миграцией, сперва проверив боевую базу
    # на уже сохранённые строки с нарушенным порядком.
    date_rules.assert_instance_ordered(project)
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
    platform = hydration.project_briefs([p.project_ref for p in projects])
    # Объекты — модель этого же аппа, поэтому один prefetch, а не батч через
    # hydration (в отличие от владельцев и отделов, которыми владеют
    # users/hr). Собираем на весь список сразу: иначе роадмап делал бы
    # запрос на каждый проект.
    site_links: dict[int, list] = {}
    for link in (ProjectSite.objects
                 .filter(project_id__in=[p.id for p in projects])
                 .select_related("site")
                 .order_by("-is_primary", "site__name")):
        site_links.setdefault(link.project_id, []).append(link)

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
            "sites": [site_service.build_project_site_ref(link)
                      for link in site_links.get(project.id, [])],
            "site_ids": [link.site_id for link in site_links.get(project.id, [])],
            "use_production_calendar": project.use_production_calendar,
            "project_ref": project.project_ref,
            "project_code": (platform.get(project.project_ref) or {}).get("code"),
            "linked": bool(project.project_ref),
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
