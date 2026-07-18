"""Repositories for task-related models."""

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.comment import TaskComment
from app.models.attachment import TaskAttachment
from app.models.link import TaskLink
from app.models.activity import TaskActivity
from app.models.label import Label
from app.models.project import Project
from app.models.task_type import TaskTypeRef
from app.models.notification import Notification
from app.models.task import Status, Task
from app.models.user_replica import User
from app.repositories.base_repo import BaseRepository


class CommentRepository(BaseRepository[TaskComment]):
    """Repository for TaskComment."""

    def __init__(self, session: AsyncSession):
        super().__init__(TaskComment, session)


class AttachmentRepository(BaseRepository[TaskAttachment]):
    """Repository for TaskAttachment."""

    def __init__(self, session: AsyncSession):
        super().__init__(TaskAttachment, session)


class LinkRepository(BaseRepository[TaskLink]):
    """Repository for TaskLink."""

    def __init__(self, session: AsyncSession):
        super().__init__(TaskLink, session)


class ActivityRepository(BaseRepository[TaskActivity]):
    """Repository for TaskActivity."""

    def __init__(self, session: AsyncSession):
        super().__init__(TaskActivity, session)


class LabelRepository(BaseRepository[Label]):
    """Repository for Label."""

    def __init__(self, session: AsyncSession):
        super().__init__(Label, session)


_CYRILLIC_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "қ": "q", "ғ": "g", "ұ": "u", "ү": "u", "һ": "h", "ң": "n", "ө": "o",
    "ә": "a", "і": "i",
}


def slugify_name(name: str) -> str:
    """Transliterate + slugify a display name into an ascii slug.

    Russian/Kazakh letters are romanised so e.g. "Обслуживание" → "obsluzhivanie".
    Falls back to "type" if the name has no slug-able characters.
    """
    out: list[str] = []
    for ch in name.strip().lower():
        if ch in _CYRILLIC_MAP:
            out.append(_CYRILLIC_MAP[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
        # everything else (punctuation, non-mapped unicode) is dropped
    slug = "".join(out)
    # collapse repeated dashes and trim
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or "type"


class TaskTypeRepository(BaseRepository[TaskTypeRef]):
    """Repository for TaskTypeRef (the user-configurable task types)."""

    def __init__(self, session: AsyncSession):
        super().__init__(TaskTypeRef, session)

    async def list_all(self) -> list[TaskTypeRef]:
        result = await self.session.execute(
            select(TaskTypeRef).order_by(
                TaskTypeRef.is_system.desc(), TaskTypeRef.name.asc()
            )
        )
        return list(result.scalars().all())

    async def get_by_slug(self, slug: str) -> TaskTypeRef | None:
        result = await self.session.execute(
            select(TaskTypeRef).where(TaskTypeRef.slug == slug)
        )
        return result.scalar_one_or_none()

    async def generate_unique_slug(self, name: str) -> str:
        """Auto-derive a unique slug from a display name."""
        base = slugify_name(name)
        candidate = base
        suffix = 2
        while await self.get_by_slug(candidate) is not None:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate


class ProjectRepository(BaseRepository[Project]):
    """Repository for Project — the Roadmap-level grouping of tasks.

    Mirrors the old VersionRepository shape so existing callers
    (Roadmap UI, task creation) translate cleanly. Aggregated metrics
    (task_count / done_count / progress) are computed on demand.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Project, session)

    async def get_user_department_id(self, user_id: int) -> int | None:
        result = await self.session.execute(
            select(User.department_id).where(User.id == user_id, User.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_visible_projects(
        self,
        *,
        employee_department_id: int | None = None,
        employee_scope: bool = False,
    ) -> list[Project]:
        if employee_scope and employee_department_id is None:
            return []

        query = (
            select(Project)
            .options(
                selectinload(Project.department),
                selectinload(Project.owner),
            )
            .order_by(Project.start_date.asc().nulls_last(), Project.created_at.desc())
        )
        if employee_scope:
            query = query.where(Project.department_id == employee_department_id)

        projects = list((await self.session.execute(query)).scalars().all())
        await self._attach_metrics(projects)
        return projects

    async def get_visible_by_id(
        self,
        project_id: int,
        *,
        employee_department_id: int | None = None,
        employee_scope: bool = False,
    ) -> Project | None:
        if employee_scope and employee_department_id is None:
            return None

        query = (
            select(Project)
            .where(Project.id == project_id)
            .options(
                selectinload(Project.department),
                selectinload(Project.owner),
            )
        )
        if employee_scope:
            query = query.where(Project.department_id == employee_department_id)

        project = (await self.session.execute(query)).scalar_one_or_none()
        if project:
            await self._attach_metrics([project])
        return project

    async def _attach_metrics(self, projects: list[Project]) -> None:
        if not projects:
            return
        project_ids = [p.id for p in projects]
        metrics_result = await self.session.execute(
            select(
                Task.project_id,
                func.count(Task.id),
                func.sum(case((Task.status.in_([Status.DONE, Status.CANCELLED]), 1), else_=0)),
            )
            .where(Task.is_deleted.is_(False), Task.project_id.in_(project_ids))
            .group_by(Task.project_id)
        )
        metrics = {
            row[0]: {
                "task_count": row[1] or 0,
                "done_count": row[2] or 0,
            }
            for row in metrics_result.all()
        }
        for project in projects:
            data = metrics.get(project.id, {"task_count": 0, "done_count": 0})
            project.task_count = int(data["task_count"])
            project.done_count = int(data["done_count"])
            project.progress = (
                round(project.done_count / project.task_count * 100, 1)
                if project.task_count
                else 0.0
            )


class NotificationRepository(BaseRepository[Notification]):
    """Repository for Notification."""

    def __init__(self, session: AsyncSession):
        super().__init__(Notification, session)
