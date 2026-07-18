"""Task repository with specialized queries."""

from datetime import date, datetime

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.department_replica import Department
from app.models.participants import TaskAssignee, TaskDelegate, TaskWatcher
from app.models.task import Task, Status, TERMINAL_STATUSES
from app.models.user_replica import User
from app.repositories.base_repo import BaseRepository


class TaskRepository(BaseRepository[Task]):
    """Specialized repository for Task model."""

    def __init__(self, session: AsyncSession):
        super().__init__(Task, session)

    async def get_user_department_id(self, user_id: int) -> int | None:
        """Resolve the current user's HR department from the local replica."""
        result = await self.session.execute(
            select(User.department_id).where(User.id == user_id, User.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    def _user_is_participant(self, user_id: int):
        """Match tasks where the user appears in any role.

        Includes legacy ``assignee_id`` and the new ``task_assignees`` /
        ``task_delegates`` / ``task_watchers`` tables, plus supervisor and
        reporter — basically anything that gives a user a stake in the task.
        """
        return or_(
            Task.assignee_id == user_id,
            Task.reporter_id == user_id,
            Task.supervisor_id == user_id,
            Task.assignees.any(TaskAssignee.user_id == user_id),
            Task.delegates.any(TaskDelegate.user_id == user_id),
            Task.watchers.any(TaskWatcher.user_id == user_id),
        )

    def _employee_task_visibility(self, user_id: int, department_id: int | None):
        conditions = [self._user_is_participant(user_id)]
        if department_id is not None:
            conditions.append(
                and_(
                    Task.department_id == department_id,
                    Task.assignee_id.is_(None),
                    Task.status.in_([Status.BACKLOG, Status.TODO]),
                )
            )
        return or_(*conditions)

    def _employee_report_visibility(self, user_id: int, department_id: int | None):
        terminal = list(TERMINAL_STATUSES)
        conditions = [
            and_(
                or_(
                    Task.assignee_id == user_id,
                    Task.assignees.any(TaskAssignee.user_id == user_id),
                ),
                Task.status.in_(terminal),
            )
        ]
        if department_id is not None:
            conditions.append(
                and_(
                    Task.department_id == department_id,
                    Task.assignee_id.is_(None),
                    Task.status.in_([Status.BACKLOG, Status.TODO]),
                )
            )
        return or_(*conditions)

    def _visibility_filter(
        self,
        *,
        visibility: str,
        user_id: int | None,
        department_id: int | None,
    ):
        if visibility == "all":
            return None
        if user_id is None:
            return false()
        if visibility == "employee":
            return self._employee_task_visibility(user_id, department_id)
        if visibility == "reports":
            return self._employee_report_visibility(user_id, department_id)
        return false()

    def _filtered_task_condition(
        self,
        *,
        status: Status | None = None,
        priority: str | None = None,
        task_type: str | None = None,
        task_type_id: int | None = None,
        assignee_id: int | None = None,
        reporter_id: int | None = None,
        supervisor_id: int | None = None,
        department_id: int | None = None,
        project_id: int | None = None,
        project_unset: bool = False,
        parent_id: int | None = None,
        search: str | None = None,
        visibility: str = "all",
        visibility_user_id: int | None = None,
        visibility_department_id: int | None = None,
    ):
        conditions = [Task.is_deleted.is_(False)]
        visibility_condition = self._visibility_filter(
            visibility=visibility,
            user_id=visibility_user_id,
            department_id=visibility_department_id,
        )
        if visibility_condition is not None:
            conditions.append(visibility_condition)
        if status:
            conditions.append(Task.status == status)
        if priority:
            conditions.append(Task.priority == priority)
        if task_type:
            # Resolve by slug through the new task_types join.
            from app.models.task_type import TaskTypeRef
            conditions.append(
                Task.task_type_ref.has(TaskTypeRef.slug == task_type)
            )
        if task_type_id is not None:
            conditions.append(Task.task_type_id == task_type_id)
        if assignee_id is not None:
            # Match across either the denormalized primary FK or the M:M
            # table so a "tasks where X is involved as worker" filter is
            # correct regardless of whether X is primary or collaborator.
            conditions.append(
                or_(
                    Task.assignee_id == assignee_id,
                    Task.assignees.any(TaskAssignee.user_id == assignee_id),
                )
            )
        if reporter_id is not None:
            conditions.append(Task.reporter_id == reporter_id)
        if supervisor_id is not None:
            conditions.append(Task.supervisor_id == supervisor_id)
        if department_id is not None:
            conditions.append(Task.department_id == department_id)
        if project_id is not None:
            conditions.append(Task.project_id == project_id)
        if project_unset:
            # Filter for "standalone" tasks — no project attached.
            conditions.append(Task.project_id.is_(None))
        if parent_id is not None:
            conditions.append(Task.parent_id == parent_id)
        if search:
            conditions.append(
                Task.summary.ilike(f"%{search}%")
                | Task.description.ilike(f"%{search}%")
                | Task.key.ilike(f"%{search}%")
            )
        return and_(*conditions)

    def _detail_load_options(self):
        """Eager-load options for any "full task" fetch.

        Shared between key/id lookups so list views and detail views see
        the same shape of preloaded relationships.
        """
        return (
            selectinload(Task.comments),
            selectinload(Task.attachments),
            selectinload(Task.labels),
            selectinload(Task.activities),
            selectinload(Task.outgoing_links),
            selectinload(Task.incoming_links),
            selectinload(Task.subtasks),
            selectinload(Task.reporter),
            selectinload(Task.assignee),
            selectinload(Task.supervisor),
            selectinload(Task.department),
            selectinload(Task.departments),
            selectinload(Task.project),
            selectinload(Task.task_type_ref),
            selectinload(Task.parent),
            selectinload(Task.assignees).selectinload(TaskAssignee.user),
            selectinload(Task.delegates).selectinload(TaskDelegate.user),
            selectinload(Task.delegates).selectinload(TaskDelegate.granted_by),
            selectinload(Task.watchers).selectinload(TaskWatcher.user),
        )

    async def get_by_key(self, key: str) -> Task | None:
        """Get task by unique key (e.g., TASK-123)."""
        result = await self.session.execute(
            select(Task)
            .where(Task.key == key, Task.is_deleted.is_(False))
            .options(*self._detail_load_options())
        )
        return result.scalar_one_or_none()

    async def get_with_relations(
        self,
        id: int,
        *,
        visibility: str = "all",
        visibility_user_id: int | None = None,
        visibility_department_id: int | None = None,
    ) -> Task | None:
        """Get task with all related data loaded."""
        result = await self.session.execute(
            select(Task)
            .where(
                Task.id == id,
                self._filtered_task_condition(
                    visibility=visibility,
                    visibility_user_id=visibility_user_id,
                    visibility_department_id=visibility_department_id,
                ),
            )
            .options(*self._detail_load_options())
        )
        return result.scalar_one_or_none()

    async def get_list(
        self,
        offset: int = 0,
        limit: int = 100,
        status: Status | None = None,
        priority: str | None = None,
        task_type: str | None = None,
        assignee_id: int | None = None,
        reporter_id: int | None = None,
        supervisor_id: int | None = None,
        department_id: int | None = None,
        project_id: int | None = None,
        project_unset: bool = False,
        task_type_id: int | None = None,
        parent_id: int | None = None,
        label_id: int | None = None,
        search: str | None = None,
        visibility: str = "all",
        visibility_user_id: int | None = None,
        visibility_department_id: int | None = None,
    ) -> list[Task]:
        """Get filtered task list."""
        query = (
            select(Task)
            .where(
                self._filtered_task_condition(
                    status=status,
                    priority=priority,
                    task_type=task_type,
                    task_type_id=task_type_id,
                    assignee_id=assignee_id,
                    reporter_id=reporter_id,
                    supervisor_id=supervisor_id,
                    department_id=department_id,
                    project_id=project_id,
                    project_unset=project_unset,
                    parent_id=parent_id,
                    search=search,
                    visibility=visibility,
                    visibility_user_id=visibility_user_id,
                    visibility_department_id=visibility_department_id,
                )
            )
            .options(
                selectinload(Task.labels),
                selectinload(Task.reporter),
                selectinload(Task.assignee),
                selectinload(Task.supervisor),
                selectinload(Task.department),
                selectinload(Task.departments),
                selectinload(Task.project),
                selectinload(Task.task_type_ref),
                selectinload(Task.parent),
                selectinload(Task.subtasks),
                selectinload(Task.assignees).selectinload(TaskAssignee.user),
            )
            .order_by(Task.created_at.desc())
        )

        if label_id is not None:
            query = query.where(Task.labels.any(id=label_id))

        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_stats(
        self,
        department_id: int | None = None,
        project_id: int | None = None,
        visibility: str = "all",
        visibility_user_id: int | None = None,
        visibility_department_id: int | None = None,
    ) -> dict:
        """Get task statistics."""
        base_filter = self._filtered_task_condition(
            department_id=department_id,
            project_id=project_id,
            visibility=visibility,
            visibility_user_id=visibility_user_id,
            visibility_department_id=visibility_department_id,
        )

        # Total count
        total_result = await self.session.execute(
            select(func.count(Task.id)).where(base_filter)
        )
        total = total_result.scalar_one()

        # By status
        status_result = await self.session.execute(
            select(Task.status, func.count(Task.id))
            .where(base_filter)
            .group_by(Task.status)
        )
        by_status = {row[0]: row[1] for row in status_result.all()}

        # By priority
        priority_result = await self.session.execute(
            select(Task.priority, func.count(Task.id))
            .where(base_filter)
            .group_by(Task.priority)
        )
        by_priority = {row[0]: row[1] for row in priority_result.all()}

        # By type — join with the task_types registry to expose slugs in
        # the stats payload. NULL ``task_type_id`` (unclassified) is
        # bucketed under the literal string 'unknown' so the response
        # shape stays Dict[str, int].
        from app.models.task_type import TaskTypeRef
        type_result = await self.session.execute(
            select(TaskTypeRef.slug, func.count(Task.id))
            .select_from(Task)
            .outerjoin(TaskTypeRef, Task.task_type_id == TaskTypeRef.id)
            .where(base_filter)
            .group_by(TaskTypeRef.slug)
        )
        by_type = {(row[0] or "unknown"): row[1] for row in type_result.all()}

        # Created per day (last 30 days)
        thirty_days_ago = datetime.utcnow().date() - date.resolution * 30
        created_daily_result = await self.session.execute(
            select(
                func.date(Task.created_at).label("day"),
                func.count(Task.id),
            )
            .where(base_filter & (Task.created_at >= thirty_days_ago))
            .group_by(func.date(Task.created_at))
            .order_by(func.date(Task.created_at))
        )
        created_per_day = [
            {"day": str(row[0]), "count": row[1]} for row in created_daily_result.all()
        ]

        # Resolved per day (last 30 days)
        resolved_daily_result = await self.session.execute(
            select(
                func.date(Task.completed_at).label("day"),
                func.count(Task.id),
            )
            .where(
                base_filter
                & (Task.completed_at.isnot(None))
                & (Task.completed_at >= thirty_days_ago)
            )
            .group_by(func.date(Task.completed_at))
            .order_by(func.date(Task.completed_at))
        )
        resolved_per_day = [
            {"day": str(row[0]), "count": row[1]} for row in resolved_daily_result.all()
        ]

        # By department
        department_result = await self.session.execute(
            select(
                Task.department_id,
                Department.name,
                func.count(Task.id),
            )
            .outerjoin(Department, Task.department_id == Department.id)
            .where(base_filter)
            .group_by(Task.department_id, Department.name)
            .order_by(func.count(Task.id).desc())
        )
        by_department = [
            {
                "department__id": row[0],
                "department__name": row[1] or "Без отдела",
                "count": row[2],
            }
            for row in department_result.all()
        ]

        # By assignee
        assignee_result = await self.session.execute(
            select(
                Task.assignee_id,
                User.first_name,
                User.last_name,
                User.username,
                func.count(Task.id),
            )
            .outerjoin(User, Task.assignee_id == User.id)
            .where(base_filter, Task.assignee_id.isnot(None))
            .group_by(Task.assignee_id, User.first_name, User.last_name, User.username)
            .order_by(func.count(Task.id).desc())
        )
        by_assignee = [
            {
                "assignee__id": row[0],
                "assignee__first_name": row[1] or "",
                "assignee__last_name": row[2] or "",
                "assignee__username": row[3] or "",
                "count": row[4],
            }
            for row in assignee_result.all()
        ]

        return {
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
            "by_type": by_type,
            "by_department": by_department,
            "by_assignee": by_assignee,
            "created_per_day": created_per_day,
            "resolved_per_day": resolved_per_day,
        }
