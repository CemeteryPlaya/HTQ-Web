"""Межаппный интерфейс «Проекта» (мастер-план §2.6)."""

from __future__ import annotations

import uuid

from apps.core.services import require_service

from .models import Project, ProjectMember
from .services import projects


def project_brief(ids: list[str]) -> dict[str, dict]:
    require_service("project")
    return {str(p.id): projects.brief(p) for p in Project.objects.filter(id__in=ids)}


def is_member(project_id: str, user_id: int) -> bool:
    require_service("project")
    return ProjectMember.objects.filter(project_id=project_id, user_id=user_id).exists()


def member_project_ids(user_id: int) -> list[str]:
    require_service("project")
    return [str(pid) for pid in ProjectMember.objects.filter(user_id=user_id)
            .values_list("project_id", flat=True)]


def member_user_ids(project_id: str) -> list[int]:
    """Кого уведомлять по проекту: руководитель плюс участники, без повторов,
    по возрастанию. Руководитель — участник и так (``services.projects.
    _ensure_member``), но берётся и из самого проекта: строку участия могли
    удалить в обход сервиса. Неизвестный или неверный ключ — пустой список."""
    require_service("project")
    try:
        key = uuid.UUID(str(project_id))
    except (ValueError, AttributeError, TypeError):
        return []
    project = Project.objects.filter(pk=key).only("manager_user_id").first()
    if project is None:
        return []
    ids = set(ProjectMember.objects.filter(project_id=key).values_list("user_id", flat=True))
    if project.manager_user_id:
        ids.add(project.manager_user_id)
    return sorted(ids)


def search_projects(query: str, *, user_id: int, only_member: bool,
                    limit: int = 20) -> list[dict]:
    require_service("project")
    return projects.search(query, user_id=user_id, only_member=only_member, limit=limit)
