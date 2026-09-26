"""Межаппный интерфейс «Проекта» (мастер-план §2.6)."""

from __future__ import annotations

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


def search_projects(query: str, *, user_id: int, only_member: bool,
                    limit: int = 20) -> list[dict]:
    require_service("project")
    return projects.search(query, user_id=user_id, only_member=only_member, limit=limit)
