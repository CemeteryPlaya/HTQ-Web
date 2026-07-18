"""sqladmin ModelViews for task-service."""

from sqladmin import ModelView

from app.models.activity import TaskActivity
from app.models.attachment import TaskAttachment
from app.models.comment import TaskComment
from app.models.label import Label
from app.models.link import TaskLink
from app.models.notification import Notification
from app.models.project import Project
from app.models.sequence import ProductionDay, TaskSequence
from app.models.task import Task
from app.models.task_type import TaskTypeRef


class TaskAdmin(ModelView, model=Task):
    name_plural = "Tasks"
    icon = "fa-solid fa-list-check"
    column_list = ["id", "key", "summary", "status", "priority", "task_type_id", "assignee_id", "due_date"]
    column_searchable_list = ["key", "summary"]
    column_sortable_list = ["id", "key", "due_date", "status", "priority"]
    column_default_sort = [("id", True)]


class TaskCommentAdmin(ModelView, model=TaskComment):
    name_plural = "Comments"
    icon = "fa-solid fa-comment"
    column_list = ["id", "task_id", "author_id", "created_at"]
    column_default_sort = [("created_at", True)]


class TaskAttachmentAdmin(ModelView, model=TaskAttachment):
    name_plural = "Attachments"
    icon = "fa-solid fa-paperclip"
    column_list = ["id", "task_id", "filename", "uploaded_by_id", "created_at"]


class TaskLinkAdmin(ModelView, model=TaskLink):
    name_plural = "Task links"
    icon = "fa-solid fa-link"
    column_list = ["id", "source_id", "target_id", "link_type", "created_by_id"]


class TaskActivityAdmin(ModelView, model=TaskActivity):
    name_plural = "Activity log"
    icon = "fa-solid fa-clock-rotate-left"
    column_list = ["id", "task_id", "actor_id", "field_name", "created_at"]
    column_default_sort = [("created_at", True)]
    can_create = False
    can_edit = False


class LabelAdmin(ModelView, model=Label):
    name_plural = "Labels"
    icon = "fa-solid fa-tag"
    column_list = ["id", "name", "color"]
    column_searchable_list = ["name"]


class ProjectAdmin(ModelView, model=Project):
    name_plural = "Projects"
    icon = "fa-solid fa-folder-tree"
    column_list = ["id", "name", "status", "start_date", "end_date", "owner_id"]
    column_searchable_list = ["name"]


class TaskTypeAdmin(ModelView, model=TaskTypeRef):
    name_plural = "Task types"
    icon = "fa-solid fa-shapes"
    column_list = ["id", "slug", "name", "color", "is_system"]
    column_searchable_list = ["name", "slug"]


class NotificationAdmin(ModelView, model=Notification):
    name_plural = "Notifications"
    icon = "fa-solid fa-bell"
    column_list = ["id", "recipient_id", "actor_id", "task_id", "verb", "is_read", "created_at"]
    column_default_sort = [("created_at", True)]


class TaskSequenceAdmin(ModelView, model=TaskSequence):
    name_plural = "Task sequences"
    icon = "fa-solid fa-arrow-up-9-1"
    column_list = ["id", "name", "current_value"]
    can_create = False
    can_delete = False


class ProductionDayAdmin(ModelView, model=ProductionDay):
    name_plural = "Production calendar"
    icon = "fa-solid fa-calendar-days"
    column_list = ["id", "date", "day_type", "note", "working_days_since_epoch"]
    column_sortable_list = ["date", "day_type"]
    column_default_sort = [("date", True)]
