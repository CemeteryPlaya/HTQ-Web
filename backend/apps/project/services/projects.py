"""Операции над проектами. Руководитель — участник автоматически и не
снимается, пока он руководитель (Q-E26)."""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.project.models import Project, ProjectMember, ProjectStatus


class ProjectError(Exception):
    pass


def _ensure_member(project: Project, user_id: int | None, actor_id: int | None) -> None:
    if user_id:
        ProjectMember.objects.get_or_create(project=project, user_id=user_id,
                                            defaults={"added_by": actor_id})


@transaction.atomic
def create(*, code: str, name: str, country_code: str, actor_id: int,
           manager_user_id: int | None = None, **fields) -> Project:
    try:
        with transaction.atomic():
            project = Project.objects.create(code=code, name=name, country_code=country_code,
                                             manager_user_id=manager_user_id,
                                             created_by=actor_id, **fields)
    except IntegrityError as exc:
        raise ProjectError(f"Проект с кодом «{code}» уже есть") from exc
    _ensure_member(project, manager_user_id, actor_id)
    return project


@transaction.atomic
def update(project: Project, *, actor_id: int, **fields) -> Project:
    for key, value in fields.items():
        setattr(project, key, value)
    project.save()
    _ensure_member(project, project.manager_user_id, actor_id)
    return project


def add_member(project: Project, user_id: int, *, actor_id: int) -> None:
    _ensure_member(project, user_id, actor_id)


def remove_member(project: Project, user_id: int, *, actor_id: int) -> None:
    if project.manager_user_id == user_id:
        raise ProjectError("Руководитель проекта остаётся участником, пока он руководитель")
    ProjectMember.objects.filter(project=project, user_id=user_id).delete()


def brief(project: Project) -> dict:
    return {"id": str(project.id), "code": project.code, "name": project.name,
            "kind": project.kind, "status": project.status,
            "country_code": project.country_code, "manager_user_id": project.manager_user_id,
            "customer_name": project.customer_name,
            "customer_counterparty_id": project.customer_counterparty_id or None}


def search(query: str, *, user_id: int, only_member: bool, limit: int = 20) -> list[dict]:
    rows = Project.objects.exclude(status=ProjectStatus.ARCHIVED)
    if query:
        rows = rows.filter(Q(code__icontains=query) | Q(name__icontains=query))
    if only_member:
        rows = rows.filter(members__user_id=user_id)
    return [brief(p) for p in rows.order_by("code")[:limit]]
