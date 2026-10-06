"""Ручки проектной структуры (docs/plans/2026-10-06-project-structure-spec.md §3–§4).

Видит структуру тот, кто видит проект (``views._project``: участник, держатель
``project.all`` или ``project.structure``). Правит — руководитель СВОЕГО
проекта (``manager_user_id``, без узла) или держатель ``project.structure``
(``edit``) — любого. Справочник ролей читают все с ``project:read``, правят
держатели ``project.roles``. Логика — ``services/structure.py``.
"""

from __future__ import annotations

from datetime import date

from django.http import Http404
from django.utils import timezone

from apps.access import interface as access
from apps.hr import interface as hr
from htqweb.errors import DomainError
from htqweb.http import api_view, json_error, uuid_or_404

from . import schemas
from .models import Project, ProjectAssignment, ProjectRole, ProjectSlot
from .services import structure
from .views import _project

_FORBIDDEN = "Недостаточно прав для этого действия."


def _has(request, node: str) -> bool:
    company = (getattr(request, "company", None) or {}).get("slug")
    return "edit" in access.flags_for(request.token, node, company)


def _can_edit(request, project: Project) -> bool:
    return (project.manager_user_id == request.token.user_id
            or _has(request, "project.structure"))


def _require_edit(request, project: Project) -> None:
    if not _can_edit(request, project):
        raise DomainError("E-ACC-01", _FORBIDDEN, status=403)


def _call(fn, *args, **kwargs):
    """Ошибки сервиса → конверт D-28 с кодами спека §4."""
    try:
        return fn(*args, **kwargs)
    except structure.StructureError as exc:
        raise DomainError("E-PRJ-05", str(exc), status=409) from exc
    except structure.EmployeeError as exc:
        raise DomainError("E-PRJ-06", str(exc),
                          fields=[{"field": "employee_id", "message": str(exc)}]) from exc
    except structure.RoleError as exc:
        raise DomainError("E-PRJ-07", str(exc), status=409) from exc


def _slot(request, slot_id: str) -> ProjectSlot:
    slot = ProjectSlot.objects.filter(pk=uuid_or_404(slot_id)).first()
    if slot is None:
        raise Http404("Место не найдено")
    slot.project = _project(request, str(slot.project_id))
    return slot


def _assignment(request, assignment_id: str) -> ProjectAssignment:
    row = (ProjectAssignment.objects.select_related("slot")
           .filter(pk=uuid_or_404(assignment_id)).first())
    if row is None:
        raise Http404("Назначение не найдено")
    row.slot.project = _project(request, str(row.slot.project_id))
    return row


# ── Справочник ролей ────────────────────────────────────────────────────────

@api_view(methods=("GET",), module="project", level="read")
def _roles(request):
    return structure.list_roles(active_only=request.GET.get("active") == "1")


@api_view(methods=("POST",), module="project", level="write", body=schemas.RoleIn, status=201)
def _role_create(request, data: schemas.RoleIn):
    if not _has(request, "project.roles"):
        raise DomainError("E-ACC-01", _FORBIDDEN, status=403)
    return _call(structure.create_role, **data.model_dump())


def project_roles(request):
    if request.method == "GET":
        return _roles(request)
    if request.method == "POST":
        return _role_create(request)
    return json_error("Method Not Allowed", 405)


def _role_or_404(role_id: int) -> ProjectRole:
    role = ProjectRole.objects.filter(pk=role_id).first()
    if role is None:
        raise Http404("Роль не найдена")
    return role


@api_view(methods=("PATCH",), module="project", level="write", body=schemas.RolePatch)
def _role_patch(request, role_id: int, data: schemas.RolePatch):
    if not _has(request, "project.roles"):
        raise DomainError("E-ACC-01", _FORBIDDEN, status=403)
    return _call(structure.update_role, _role_or_404(role_id),
                 **data.model_dump(exclude_unset=True))


@api_view(methods=("DELETE",), module="project", level="write", status=204)
def _role_delete(request, role_id: int):
    if not _has(request, "project.roles"):
        raise DomainError("E-ACC-01", _FORBIDDEN, status=403)
    _call(structure.delete_role, _role_or_404(role_id))
    return {}


def project_role(request, role_id: int):
    if request.method == "PATCH":
        return _role_patch(request, role_id=role_id)
    if request.method == "DELETE":
        return _role_delete(request, role_id=role_id)
    return json_error("Method Not Allowed", 405)


# ── Структура проекта ───────────────────────────────────────────────────────

@api_view(methods=("GET",), module="project", level="read")
def project_structure(request, project_id: str):
    project = _project(request, project_id)
    raw = request.GET.get("on", "")
    try:
        on = date.fromisoformat(raw) if raw else timezone.localdate()
    except ValueError as exc:
        raise DomainError("E-VAL-01", "Дата — в формате ГГГГ-ММ-ДД.",
                          fields=[{"field": "on", "message": "Неверная дата"}]) from exc
    return {"project_id": str(project.id), "on": on, "can_edit": _can_edit(request, project),
            "slots": structure.structure(project, on)}


@api_view(methods=("POST",), module="project", level="write", body=schemas.SlotIn, status=201)
def _slot_create(request, project_id: str, data: schemas.SlotIn):
    project = _project(request, project_id)
    _require_edit(request, project)
    slot = _call(structure.create_slot, project, actor_id=request.token.user_id,
                 **data.model_dump())
    return {"id": str(slot.id)}


def project_slots(request, project_id: str):
    if request.method == "POST":
        return _slot_create(request, project_id=project_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PATCH",), module="project", level="write", body=schemas.SlotPatch)
def _slot_patch(request, slot_id: str, data: schemas.SlotPatch):
    slot = _slot(request, slot_id)
    _require_edit(request, slot.project)
    _call(structure.update_slot, slot, actor_id=request.token.user_id,
          **data.model_dump(exclude_unset=True))
    return {"id": str(slot.id)}


def slot_item(request, slot_id: str):
    if request.method == "PATCH":
        return _slot_patch(request, slot_id=slot_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="project", level="write", body=schemas.AssignmentIn,
          status=201)
def _assignment_create(request, slot_id: str, data: schemas.AssignmentIn):
    slot = _slot(request, slot_id)
    _require_edit(request, slot.project)
    row = _call(structure.create_assignment, slot, actor_id=request.token.user_id,
                **data.model_dump())
    return {"id": str(row.id)}


def slot_assignments(request, slot_id: str):
    if request.method == "POST":
        return _assignment_create(request, slot_id=slot_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PATCH",), module="project", level="write", body=schemas.AssignmentPatch)
def _assignment_patch(request, assignment_id: str, data: schemas.AssignmentPatch):
    row = _assignment(request, assignment_id)
    _require_edit(request, row.slot.project)
    _call(structure.update_assignment, row, actor_id=request.token.user_id,
          **data.model_dump(exclude_unset=True))
    return {"id": str(row.id)}


@api_view(methods=("DELETE",), module="project", level="write", status=204)
def _assignment_delete(request, assignment_id: str):
    row = _assignment(request, assignment_id)
    _require_edit(request, row.slot.project)
    _call(structure.delete_assignment, row)
    return {}


def assignment_item(request, assignment_id: str):
    if request.method == "PATCH":
        return _assignment_patch(request, assignment_id=assignment_id)
    if request.method == "DELETE":
        return _assignment_delete(request, assignment_id=assignment_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="project", level="read")
def employees(request):
    """Поиск действующих сотрудников компании для назначения (до 20). Кадровых
    прав не требует, но и не справочник для всех: только тем, кто правит
    структуру хоть одного проекта — держателю ``project.structure`` или
    руководителю проекта."""
    if not (_has(request, "project.structure")
            or Project.objects.filter(manager_user_id=request.token.user_id).exists()):
        raise DomainError("E-ACC-01", _FORBIDDEN, status=403)
    query = request.GET.get("q", "").strip()[:100]
    if not query:
        return []
    return [{k: e[k] for k in ("id", "full_name", "position_title")}
            for e in hr.employees_brief(query=query, limit=20)]
