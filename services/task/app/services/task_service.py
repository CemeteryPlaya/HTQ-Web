"""Task service layer with business logic.

Jira + SharePoint workflow:

- ``Task.assignee_id`` is the *primary* assignee. Source of truth for the
  full crew is the ``task_assignees`` row set, which carries a role
  (primary | collaborator). Service-level helpers keep the two in sync.
- ``Task.supervisor_id`` is single. The supervisor can grant edit rights
  to delegates (``task_delegates``).
- Watchers (``task_watchers``) follow a task — read-only but visible.
- ``progress_percent`` is independent of status; reaching ``done`` auto-
  fills it to 100.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, Status
from app.models.sequence import TaskSequence, ProductionDay
from app.models.participants import (
    AssigneeRole,
    TaskAssignee,
    TaskDelegate,
    TaskWatcher,
)
from app.repositories.task_repo import TaskRepository
from app.repositories import (
    CommentRepository,
    AttachmentRepository,
    LinkRepository,
    ActivityRepository,
    LabelRepository,
    NotificationRepository,
)
from app.schemas.task import (
    AssigneeAssignment,
    TaskCreate,
    TaskUpdate,
)


class TaskService:
    """Business logic for task management."""

    TRACKED_FIELDS = [
        "summary",
        "description",
        "task_type_id",
        "priority",
        "status",
        "assignee_id",
        "supervisor_id",
        "project_id",
        "progress_percent",
        "due_date",
        "start_date",
        "estimated_working_days",
    ]

    def __init__(self, session: AsyncSession):
        self.session = session
        self.task_repo = TaskRepository(session)
        self.comment_repo = CommentRepository(session)
        self.attachment_repo = AttachmentRepository(session)
        self.link_repo = LinkRepository(session)
        self.activity_repo = ActivityRepository(session)
        self.label_repo = LabelRepository(session)
        self.notification_repo = NotificationRepository(session)

    # ------------------------------------------------------------------ #
    # CRUD                                                                #
    # ------------------------------------------------------------------ #

    async def create_task(
        self,
        data: TaskCreate,
        user_id: int | None = None,
    ) -> Task:
        """Create a new task with auto-generated key."""
        next_val = await TaskSequence.get_next_value(self.session, "TASK")
        key = f"TASK-{next_val}"

        due_date = data.due_date
        if data.estimated_working_days and data.start_date:
            due_date = await self._calculate_due_date(
                data.start_date, data.estimated_working_days
            )

        # Resolve task_type — accept either an FK id or a slug. If neither
        # supplied, default to the seeded 'task' row.
        task_type_id = await self._resolve_task_type_id(
            data.task_type_id, data.task_type
        )

        # Compose the final assignee crew. ``assignee_id`` (legacy / single
        # field) takes precedence as the primary; the explicit
        # ``assignees`` list fills in collaborators (and may also set a
        # primary if ``assignee_id`` is None).
        crew = self._compose_initial_crew(data.assignee_id, data.assignees)
        primary_id = next(
            (a.user_id for a in crew if a.role == AssigneeRole.PRIMARY), None
        )

        # Resolve the department set. ``department_id`` (legacy single) and
        # ``department_ids`` (multi) are merged; the primary is the explicit
        # ``department_id`` or the first of the list.
        dept_ids = list(dict.fromkeys(
            ([data.department_id] if data.department_id else []) + list(data.department_ids)
        ))
        primary_dept = data.department_id or (dept_ids[0] if dept_ids else None)

        task = await self.task_repo.create(
            key=key,
            summary=data.summary,
            description=data.description,
            task_type_id=task_type_id,
            priority=data.priority,
            status=data.status,
            reporter_id=data.reporter_id or user_id,
            assignee_id=primary_id,
            supervisor_id=data.supervisor_id,
            department_id=primary_dept,
            project_id=data.project_id,
            parent_id=data.parent_id,
            progress_percent=data.progress_percent,
            due_date=due_date,
            start_date=data.start_date,
            estimated_working_days=data.estimated_working_days,
        )

        # Link departments / labels via direct junction INSERTs rather than
        # assigning the ORM collection. The task was just flushed and is now
        # persistent with UNLOADED collections — assigning would trigger an
        # implicit (sync) lazy-load of the old value, which blows up under
        # the async session ("MissingGreenlet"). A core insert sidesteps that.
        if dept_ids:
            # Only link departments that actually exist in the local replica
            # so we never violate the FK (the replica can lag hr-service).
            existing = await self._get_departments_by_ids(dept_ids)
            existing_ids = [d.id for d in existing]
            if existing_ids:
                from app.models.task import task_department_links
                await self.session.execute(
                    task_department_links.insert(),
                    [{"task_id": task.id, "department_id": d} for d in existing_ids],
                )

        if data.label_ids:
            from app.models.task import task_labels
            # Guard label ids the same way — keep only ones that exist.
            valid_labels = await self._get_labels_by_ids(data.label_ids)
            if valid_labels:
                await self.session.execute(
                    task_labels.insert(),
                    [{"task_id": task.id, "label_id": lbl.id} for lbl in valid_labels],
                )

        # Persist the assignee crew.
        for assignment in crew:
            self.session.add(
                TaskAssignee(
                    task_id=task.id,
                    user_id=assignment.user_id,
                    role=assignment.role,
                )
            )

        await self.session.flush()

        # Notify everyone who got assigned (primary + collaborators).
        for assignment in crew:
            await self._create_notification(
                recipient_id=assignment.user_id,
                actor_id=user_id,
                task_id=task.id,
                verb=f"task_assigned:{task.key}",
            )

        return task

    async def update_task(
        self,
        task_id: int,
        data: TaskUpdate,
        user_id: int | None = None,
    ) -> Task:
        """Update task with activity logging and validation."""
        task = await self.task_repo.get_with_relations(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        update_data = data.model_dump(exclude_unset=True)
        label_ids = update_data.pop("label_ids", None)
        department_ids = update_data.pop("department_ids", None)

        # Resolve task_type slug→id if the caller sent the slug form.
        slug = update_data.pop("task_type", None)
        if slug is not None and "task_type_id" not in update_data:
            update_data["task_type_id"] = await self._resolve_task_type_id(None, slug)

        # Multi-department sync. Setting department_ids also realigns the
        # primary department_id to the first of the set (unless the caller
        # explicitly set department_id in the same request).
        if department_ids is not None:
            if "department_id" not in update_data:
                update_data["department_id"] = department_ids[0] if department_ids else None

        if "status" in update_data:
            new_status = Status(update_data.pop("status"))
            task.apply_transition(new_status)

            if task.assignee_id:
                await self._create_notification(
                    recipient_id=task.assignee_id,
                    actor_id=user_id,
                    task_id=task.id,
                    verb=f"status_changed:{task.key}",
                )

        # Activity log for tracked scalar fields.
        for field_name in self.TRACKED_FIELDS:
            if field_name in update_data:
                old_value = getattr(task, field_name)
                new_value = update_data[field_name]
                if old_value != new_value:
                    await self.activity_repo.create(
                        task_id=task.id,
                        actor_id=user_id,
                        field_name=field_name,
                        old_value=str(old_value) if old_value is not None else None,
                        new_value=str(new_value) if new_value is not None else None,
                    )

        await self.task_repo.update(task, **update_data)

        # If the primary assignee changed via the legacy single-field
        # update, mirror it into the M:M table so the crew stays
        # consistent.
        if "assignee_id" in update_data:
            await self._sync_primary_assignment(task, update_data["assignee_id"])

        if label_ids is not None:
            labels = await self._get_labels_by_ids(label_ids)
            task.labels = labels

        if department_ids is not None:
            task.departments = await self._get_departments_by_ids(department_ids)

        if "assignee_id" in update_data and update_data["assignee_id"]:
            await self._create_notification(
                recipient_id=update_data["assignee_id"],
                actor_id=user_id,
                task_id=task.id,
                verb=f"task_assigned:{task.key}",
            )

        await self.session.flush()
        return task

    async def delete_task(self, task_id: int) -> None:
        """Soft delete a task."""
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        task.is_deleted = True
        await self.session.flush()

    async def get_available_transitions(self, task_id: int) -> list[Status]:
        """Get available status transitions for a task."""
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        from app.models.task import TRANSITIONS
        return list(TRANSITIONS.get(task.status, set()))

    # ------------------------------------------------------------------ #
    # Participant management                                              #
    # ------------------------------------------------------------------ #

    async def replace_assignees(
        self,
        task_id: int,
        assignments: list[AssigneeAssignment],
        actor_id: int | None,
    ) -> Task:
        """Atomically replace the task's assignee crew.

        The list passed in is the new full crew — anyone not in it is
        removed. ``Task.assignee_id`` is synced to the (single) primary
        in the new crew (or NULL if no primary is supplied).
        """
        task = await self.task_repo.get_with_relations(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        existing = {a.user_id: a for a in task.assignees}
        new_ids = {a.user_id for a in assignments}

        # Drop missing.
        for user_id, row in existing.items():
            if user_id not in new_ids:
                await self.session.delete(row)

        # Upsert keep/add.
        for a in assignments:
            if a.user_id in existing:
                existing[a.user_id].role = a.role
            else:
                self.session.add(
                    TaskAssignee(task_id=task.id, user_id=a.user_id, role=a.role)
                )
                # Notify newly added crew members.
                await self._create_notification(
                    recipient_id=a.user_id,
                    actor_id=actor_id,
                    task_id=task.id,
                    verb=f"task_assigned:{task.key}",
                )

        # Mirror the primary onto the denormalized column.
        primary = next(
            (a.user_id for a in assignments if a.role == AssigneeRole.PRIMARY), None
        )
        if task.assignee_id != primary:
            await self.activity_repo.create(
                task_id=task.id,
                actor_id=actor_id,
                field_name="assignee_id",
                old_value=str(task.assignee_id) if task.assignee_id else None,
                new_value=str(primary) if primary else None,
            )
            task.assignee_id = primary

        await self.session.flush()
        return task

    async def set_supervisor(
        self, task_id: int, supervisor_id: int | None, actor_id: int | None
    ) -> Task:
        """Set or clear the task supervisor."""
        task = await self.task_repo.get_with_relations(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if task.supervisor_id == supervisor_id:
            return task

        await self.activity_repo.create(
            task_id=task.id,
            actor_id=actor_id,
            field_name="supervisor_id",
            old_value=str(task.supervisor_id) if task.supervisor_id else None,
            new_value=str(supervisor_id) if supervisor_id else None,
        )
        task.supervisor_id = supervisor_id
        await self.session.flush()
        if supervisor_id:
            await self._create_notification(
                recipient_id=supervisor_id,
                actor_id=actor_id,
                task_id=task.id,
                verb=f"task_supervisor_set:{task.key}",
            )
        return task

    async def add_delegate(
        self, task_id: int, user_id: int, granted_by: int | None
    ) -> Task:
        """Grant a user delegate rights on a task."""
        task = await self.task_repo.get_with_relations(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Idempotent — no-op if already a delegate.
        if any(d.user_id == user_id for d in task.delegates):
            return task

        self.session.add(
            TaskDelegate(
                task_id=task.id, user_id=user_id, granted_by_id=granted_by
            )
        )
        await self.activity_repo.create(
            task_id=task.id,
            actor_id=granted_by,
            field_name="delegates",
            old_value=None,
            new_value=f"+{user_id}",
        )
        await self._create_notification(
            recipient_id=user_id,
            actor_id=granted_by,
            task_id=task.id,
            verb=f"task_delegated:{task.key}",
        )
        await self.session.flush()
        return task

    async def remove_delegate(
        self, task_id: int, user_id: int, actor_id: int | None
    ) -> Task:
        task = await self.task_repo.get_with_relations(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        for row in list(task.delegates):
            if row.user_id == user_id:
                await self.session.delete(row)
                await self.activity_repo.create(
                    task_id=task.id,
                    actor_id=actor_id,
                    field_name="delegates",
                    old_value=str(user_id),
                    new_value=None,
                )
                break
        await self.session.flush()
        return task

    async def add_watcher(self, task_id: int, user_id: int) -> Task:
        task = await self.task_repo.get_with_relations(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if any(w.user_id == user_id for w in task.watchers):
            return task
        self.session.add(TaskWatcher(task_id=task.id, user_id=user_id))
        await self.session.flush()
        return task

    async def remove_watcher(self, task_id: int, user_id: int) -> Task:
        task = await self.task_repo.get_with_relations(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        for row in list(task.watchers):
            if row.user_id == user_id:
                await self.session.delete(row)
                break
        await self.session.flush()
        return task

    async def set_progress(
        self, task_id: int, percent: int, actor_id: int | None
    ) -> Task:
        task = await self.task_repo.get_with_relations(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        percent = max(0, min(100, int(percent)))
        if task.progress_percent == percent:
            return task
        await self.activity_repo.create(
            task_id=task.id,
            actor_id=actor_id,
            field_name="progress_percent",
            old_value=str(task.progress_percent),
            new_value=str(percent),
        )
        task.progress_percent = percent
        await self.session.flush()
        return task

    # ------------------------------------------------------------------ #
    # Permissions                                                         #
    # ------------------------------------------------------------------ #

    def can_user_edit(self, task: Task, user_id: int, is_elevated: bool) -> bool:
        """Full-edit permission: elevated / reporter / supervisor / delegate."""
        if is_elevated:
            return True
        if task.reporter_id == user_id:
            return True
        if task.supervisor_id == user_id:
            return True
        if any(d.user_id == user_id for d in (task.delegates or [])):
            return True
        return False

    def can_user_progress(self, task: Task, user_id: int, is_elevated: bool) -> bool:
        """Soft-edit (status / progress / comments): + any assignee."""
        if self.can_user_edit(task, user_id, is_elevated):
            return True
        if task.assignee_id == user_id:
            return True
        if any(a.user_id == user_id for a in (task.assignees or [])):
            return True
        return False

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compose_initial_crew(
        primary_id: int | None,
        explicit: list[AssigneeAssignment],
    ) -> list[AssigneeAssignment]:
        """Merge legacy single-assignee + explicit list into one crew.

        - If both supply a primary, the explicit primary wins.
        - The legacy ``primary_id`` always counts as primary if no other
          assignment for that user exists.
        """
        by_user: dict[int, AssigneeAssignment] = {}
        for a in explicit:
            by_user[a.user_id] = AssigneeAssignment(
                user_id=a.user_id, role=a.role
            )
        if primary_id is not None and primary_id not in by_user:
            by_user[primary_id] = AssigneeAssignment(
                user_id=primary_id, role=AssigneeRole.PRIMARY
            )
        # At most one primary — if the caller passed multiple primaries
        # the schema already rejected it. If they passed exactly one but
        # also gave a different primary_id, demote the legacy id.
        primaries = [a for a in by_user.values() if a.role == AssigneeRole.PRIMARY]
        if len(primaries) > 1:
            # Demote everyone except the first primary that came from
            # ``explicit``; legacy ``primary_id`` loses.
            explicit_primary_ids = {
                a.user_id for a in explicit if a.role == AssigneeRole.PRIMARY
            }
            for a in by_user.values():
                if a.role == AssigneeRole.PRIMARY and a.user_id not in explicit_primary_ids:
                    a.role = AssigneeRole.COLLABORATOR
        return list(by_user.values())

    async def _sync_primary_assignment(
        self, task: Task, new_primary_id: int | None
    ) -> None:
        """Ensure ``task_assignees`` reflects a primary change.

        Called from update_task when the legacy ``assignee_id`` field
        changes. The M:M row for the new primary is created/promoted
        and the old primary (if different) is demoted to collaborator.
        """
        # Demote anyone currently primary that isn't the new primary.
        for row in task.assignees:
            if row.role == AssigneeRole.PRIMARY and row.user_id != new_primary_id:
                row.role = AssigneeRole.COLLABORATOR

        if new_primary_id is None:
            return

        existing = next(
            (a for a in task.assignees if a.user_id == new_primary_id), None
        )
        if existing:
            existing.role = AssigneeRole.PRIMARY
        else:
            self.session.add(
                TaskAssignee(
                    task_id=task.id,
                    user_id=new_primary_id,
                    role=AssigneeRole.PRIMARY,
                )
            )

    async def _resolve_task_type_id(
        self, type_id: int | None, slug: str | None
    ) -> int | None:
        """Return the task_types FK id for the given input.

        Accepts either an explicit id (preferred — fast lookup) or a slug
        which we resolve through the registry. ``None`` for both falls
        back to the seeded 'task' slug so the form's optional Type field
        never produces a NULL classification.
        """
        if type_id is not None:
            return type_id
        from app.models.task_type import TaskTypeRef
        target_slug = (slug or "task").strip().lower()
        result = await self.session.execute(
            select(TaskTypeRef.id).where(TaskTypeRef.slug == target_slug)
        )
        return result.scalar_one_or_none()

    async def _calculate_due_date(
        self, start_date: date, working_days: int
    ) -> date | None:
        """Calculate due date using production calendar."""
        return await ProductionDay.get_date_by_working_days(
            self.session, start_date, working_days
        )

    async def _get_labels_by_ids(self, label_ids: list[int]):
        if not label_ids:
            return []
        from app.models.label import Label
        result = await self.session.execute(
            select(Label).where(Label.id.in_(label_ids))
        )
        return list(result.scalars().all())

    async def _get_departments_by_ids(self, department_ids: list[int]):
        if not department_ids:
            return []
        from app.models.department_replica import Department
        result = await self.session.execute(
            select(Department).where(Department.id.in_(department_ids))
        )
        return list(result.scalars().all())

    async def _create_notification(
        self,
        recipient_id: int,
        actor_id: int | None,
        task_id: int,
        verb: str,
    ) -> None:
        """Create a notification (non-blocking)."""
        try:
            await self.notification_repo.create(
                recipient_id=recipient_id,
                actor_id=actor_id,
                task_id=task_id,
                verb=verb,
            )
        except Exception:
            pass
