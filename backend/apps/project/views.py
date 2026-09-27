"""Ручки «Проекта» — под гейтом модуля project с явным уровнем.

Создание и правка — ``write`` плюс узел ``project.projects`` (директора,
администраторы сайта, Q-B16). Участники — узел ``project.members`` (ПМ и
HR, Q-B17). Ключи узлов проверяет ``access.interface.flags_for``.
"""

from __future__ import annotations

from django.http import Http404

from apps.access import interface as access
from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from . import schemas
from .models import Project
from .services import projects


def _need(request, node: str, flag: str) -> None:
    company = (getattr(request, "company", None) or {}).get("slug")
    if flag not in access.flags_for(request.token, node, company):
        raise DomainError("E-ACC-01", "Недостаточно прав для этого действия.", status=403)


def _sees_all(request) -> bool:
    company = (getattr(request, "company", None) or {}).get("slug")
    return "view" in access.flags_for(request.token, "project.all", company)


def _project(request, project_id: str) -> Project:
    """Проект, видимый вызывающему. Без узла ``project.all`` — только проект,
    где он участник; чужой отвечает 404, как несуществующий (мастер-план A1.3)."""
    project = Project.objects.filter(pk=project_id).first()
    if project is None or not (
            _sees_all(request) or project.members.filter(user_id=request.token.user_id).exists()):
        raise Http404("Проект не найден")
    return project


@api_view(methods=("GET",), module="project", level="read")
def _list(request):
    only_member = request.GET.get("mine") == "1" or not _sees_all(request)
    return projects.search(request.GET.get("q", ""), user_id=request.token.user_id,
                           only_member=only_member, limit=200)


@api_view(methods=("POST",), module="project", level="write", body=schemas.ProjectIn,
          status=201)
def _create(request, data: schemas.ProjectIn):
    _need(request, "project.projects", "create")
    try:
        project = projects.create(actor_id=request.token.user_id, **data.model_dump())
    except projects.ProjectError as exc:
        raise DomainError("E-PRJ-01", str(exc)) from exc
    return projects.brief(project)


def project_collection(request):
    if request.method == "GET":
        return _list(request)
    if request.method == "POST":
        return _create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="project", level="read")
def _get(request, project_id: str):
    return projects.brief(_project(request, project_id))


@api_view(methods=("PATCH",), module="project", level="write", body=schemas.ProjectPatch)
def _patch(request, project_id: str, data: schemas.ProjectPatch):
    _need(request, "project.projects", "edit")
    project = projects.update(_project(request, project_id), actor_id=request.token.user_id,
                              **data.model_dump(exclude_unset=True))
    return projects.brief(project)


def project_item(request, project_id: str):
    if request.method == "GET":
        return _get(request, project_id=project_id)
    if request.method == "PATCH":
        return _patch(request, project_id=project_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="project", level="read")
def _members(request, project_id: str):
    return sorted(_project(request, project_id).members.values_list("user_id", flat=True))


@api_view(methods=("POST",), module="project", level="write", body=schemas.MemberIn,
          status=201)
def _add_member(request, project_id: str, data: schemas.MemberIn):
    _need(request, "project.members", "edit")
    projects.add_member(_project(request, project_id), data.user_id, actor_id=request.token.user_id)
    return {"user_id": data.user_id}


def project_members(request, project_id: str):
    if request.method == "GET":
        return _members(request, project_id=project_id)
    if request.method == "POST":
        return _add_member(request, project_id=project_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("DELETE",), module="project", level="write", status=204)
def _remove_member(request, project_id: str, user_id: int):
    _need(request, "project.members", "edit")
    try:
        projects.remove_member(_project(request, project_id), user_id, actor_id=request.token.user_id)
    except projects.ProjectError as exc:
        raise DomainError("E-PRJ-02", str(exc)) from exc
    return {}


def project_member(request, project_id: str, user_id: int):
    if request.method == "DELETE":
        return _remove_member(request, project_id=project_id, user_id=user_id)
    return json_error("Method Not Allowed", 405)
