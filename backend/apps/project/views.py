"""Ручки «Проекта» — под гейтом модуля project с явным уровнем.

Создание и правка — ``write`` плюс узел ``project.projects`` (директора,
администраторы сайта, Q-B16). Участники — узел ``project.members`` (ПМ и
HR, Q-B17). Ключи узлов проверяет ``access.interface.flags_for``.
"""

from __future__ import annotations

from django.http import Http404

from apps.access import interface as access
from apps.users import interface as users
from htqweb.errors import DomainError
from htqweb.http import api_view, json_error, uuid_or_404

from . import schemas
from .models import Project, ProjectMember
from .services import projects


#: Потолок ``user_id`` (int4).
_MAX_USER_ID = 2**31 - 1


def _need(request, node: str, flag: str) -> None:
    company = (getattr(request, "company", None) or {}).get("slug")
    if flag not in access.flags_for(request.token, node, company):
        raise DomainError("E-ACC-01", "Недостаточно прав для этого действия.", status=403)


def _sees_all(request) -> bool:
    """Все проекты, а не только участия: узел ``project.all`` или право
    править структуру любого проекта (``project.structure``, спек
    2026-10-06 PS-9) — без видимости «правит любой» упирался бы в 404."""
    company = (getattr(request, "company", None) or {}).get("slug")
    return ("view" in access.flags_for(request.token, "project.all", company)
            or "edit" in access.flags_for(request.token, "project.structure", company))


def _project(request, project_id: str) -> Project:
    """Проект, видимый вызывающему. Без узла ``project.all`` — только проект,
    где он участник; чужой отвечает 404, как несуществующий (мастер-план A1.3)."""
    project = Project.objects.filter(pk=uuid_or_404(project_id)).first()
    if project is None or not (
            _sees_all(request) or project.members.filter(user_id=request.token.user_id).exists()):
        raise Http404("Проект не найден")
    return project


def _dates_error(exc: projects.ProjectDatesError) -> DomainError:
    return DomainError("E-VAL-01", str(exc),
                       fields=[{"field": "date_end", "message": "Раньше даты начала"}])


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
    except projects.ProjectDatesError as exc:
        raise _dates_error(exc) from exc
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
    try:
        project = projects.update(_project(request, project_id), actor_id=request.token.user_id,
                                  **data.model_dump(exclude_unset=True))
    except projects.ProjectDatesError as exc:
        raise _dates_error(exc) from exc
    except projects.ProjectChangeRejected as exc:
        # Правку не принял сосед, повторяющий поля «Проекта» (доска задач).
        raise DomainError("E-PRJ-04", str(exc), status=409) from exc
    except projects.ProjectError as exc:
        raise DomainError("E-PRJ-01", str(exc)) from exc
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


@api_view(methods=("GET",), module="project", level="read")
def user_names(request):
    """ФИО по ``?ids=1,2,3`` (до 200) — подписи руководителя и участников в
    карточке «Проекта». Берутся из учёток ``users``: кадровый список
    сотрудников закрыт ТД/ОД/ПМ. Раскрываются только руководители и
    участники ВИДИМЫХ вызывающему проектов — это не справочник пользователей. Ответ
    ``{id строкой: ФИО}``; чужие и невозможные id в него не попадают."""
    wanted: set[int] = set()
    for raw in request.GET.get("ids", "").split(",")[:200]:
        raw = raw.strip()
        # ``isdecimal``, а не ``isdigit``: «²» — «цифра», но не число для int();
        # потолок — int4 колонки ``user_id``, иначе запрос отвечал бы 500.
        if raw.isascii() and raw.isdecimal() and int(raw) <= _MAX_USER_ID:
            wanted.add(int(raw))
    if not wanted:
        return {}
    # Видимость — как у списка проектов: без ``project.all`` (у ПМ) только
    # проекты, где вызывающий участник; чужой состав не раскрывается (A1.3).
    visible = Project.objects.all()
    if not _sees_all(request):
        visible = visible.filter(members__user_id=request.token.user_id)
    known = (set(visible.filter(manager_user_id__in=wanted)
                 .values_list("manager_user_id", flat=True))
             | set(ProjectMember.objects.filter(project__in=visible, user_id__in=wanted)
                   .values_list("user_id", flat=True)))
    return {str(row["id"]): row["full_name"] for row in users.get_users_brief(known)}
