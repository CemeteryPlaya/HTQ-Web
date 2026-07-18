"""Authorization helpers for the requests domain."""

from fastapi import HTTPException, status

from htqweb_auth import TokenPayload
from app.repositories.project_repo import ProjectRepository


async def ensure_can_manage_project(
    repo: ProjectRepository, project_id: int, user: TokenPayload
) -> None:
    """Raise 403 unless the user is a global admin or an admin of this project."""
    if user.is_elevated:
        return
    if await repo.is_project_admin(project_id, user.user_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not allowed to manage this project",
    )


async def ensure_can_manage_template(
    repo: ProjectRepository, project_id: int | None, user: TokenPayload
) -> None:
    """Global templates (project_id is None) require elevated. Project-scoped
    templates allow elevated OR an admin of that project."""
    if user.is_elevated:
        return
    if project_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only elevated admins manage global templates",
        )
    if await repo.is_project_admin(project_id, user.user_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not allowed to manage templates for this project",
    )
