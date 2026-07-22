"""Django-admin registration for the tasks domain (DoD §6.6 п.6).

Registered here, in the domain's own phase, so phase 9 reduces to
decommissioning the old sqladmin/adminjs panels rather than re-doing this
work. Every ``ModelAdmin`` mixes in ``ServiceGatedAdminMixin`` — the
reflective meta-test ``apps/core/tests/test_invariants.py`` (Test 2) fails
the build if one is added without it, and it did exactly that while this file
was still the empty prep scaffold.

What is deliberately NOT registered standalone: ``TaskDepartmentLink``,
``TaskAssignee``/``TaskDelegate``/``TaskWatcher``, ``EventException`` and
``CalendarEventParticipant``. They are junction rows meaningless outside
their parent and are reachable as inlines instead — a changelist of
"task 41 ↔ user 7" rows is noise, and hand-editing one bypasses the
service-layer bookkeeping that keeps ``Task.assignee_id`` in step with the
``primary`` assignee row.

``TaskActivity`` is view-only: it is an append-only audit trail, and an
admin-authored or edited entry would be a forged record of who changed what.
"""

from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import (
    CalendarEvent,
    CalendarEventParticipant,
    Equipment,
    EventException,
    Label,
    Notification,
    ProductionDay,
    Project,
    Task,
    TaskActivity,
    TaskAssignee,
    TaskAssignment,
    TaskAttachment,
    TaskComment,
    TaskDelegate,
    TaskDepartmentLink,
    TaskLink,
    TaskSequence,
    TaskType,
    TaskWatcher,
)


class TaskAssigneeInline(admin.TabularInline):
    model = TaskAssignee
    extra = 0


class TaskDelegateInline(admin.TabularInline):
    model = TaskDelegate
    extra = 0


class TaskWatcherInline(admin.TabularInline):
    model = TaskWatcher
    extra = 0


class TaskDepartmentLinkInline(admin.TabularInline):
    model = TaskDepartmentLink
    extra = 0


@admin.register(Task)
class TaskAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "key", "summary", "status", "priority",
                    "progress_percent", "assignee_id", "supervisor_id",
                    "department_id", "project", "is_deleted", "created_at")
    list_filter = ("status", "priority", "is_deleted", "task_type", "project")
    search_fields = ("key", "summary", "description")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("parent",)
    filter_horizontal = ("labels",)
    inlines = (TaskAssigneeInline, TaskDelegateInline, TaskWatcherInline,
               TaskDepartmentLinkInline)


@admin.register(TaskType)
class TaskTypeAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "slug", "name", "color", "icon", "is_system")
    list_filter = ("is_system",)
    search_fields = ("slug", "name")
    readonly_fields = ("created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        # System rows back historical data (Task.task_type is SET_NULL, so
        # deleting "Задача" silently untypes every task pointing at it). The
        # API refuses this with 403; the admin must not be the back door.
        if obj is not None and obj.is_system:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Project)
class ProjectAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "status", "owner_id", "department_id",
                    "start_date", "end_date", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Label)
class LabelAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "color")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Equipment)
class EquipmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "inventory_no", "category", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("name", "inventory_no")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TaskAssignment)
class TaskAssignmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "task", "employee_id", "equipment", "role",
                    "allocation")
    raw_id_fields = ("task",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(TaskLink)
class TaskLinkAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "source", "link_type", "target", "created_by_id")
    list_filter = ("link_type",)
    raw_id_fields = ("source", "target")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TaskComment)
class TaskCommentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "task", "author_id", "created_at")
    raw_id_fields = ("task",)
    search_fields = ("body",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(TaskAttachment)
class TaskAttachmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "task", "filename", "uploaded_by_id", "created_at")
    raw_id_fields = ("task",)
    search_fields = ("filename", "file_path")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TaskActivity)
class TaskActivityAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "task", "actor_id", "field_name", "old_value",
                    "new_value", "created_at")
    list_filter = ("field_name",)
    raw_id_fields = ("task",)
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request):
        # Append-only audit trail written by the service layer — a
        # hand-authored entry is a forged record of who changed what.
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "recipient_id", "actor_id", "verb", "target_type",
                    "target_id", "is_read", "read_at", "created_at")
    list_filter = ("is_read", "target_type")
    raw_id_fields = ("task",)
    search_fields = ("verb",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(TaskSequence)
class TaskSequenceAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "current_value", "updated_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProductionDay)
class ProductionDayAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "date", "day_type", "working_days_since_epoch",
                    "note")
    list_filter = ("day_type",)
    search_fields = ("note",)
    readonly_fields = ("created_at", "updated_at")


class EventExceptionInline(admin.TabularInline):
    model = EventException
    extra = 0


class CalendarEventParticipantInline(admin.TabularInline):
    model = CalendarEventParticipant
    extra = 0


@admin.register(CalendarEvent)
class CalendarEventAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "title", "event_type", "start_at", "end_at",
                    "is_all_day", "is_global", "department_id", "creator_id")
    list_filter = ("event_type", "is_all_day", "is_global")
    search_fields = ("title", "description")
    readonly_fields = ("created_at", "updated_at")
    inlines = (EventExceptionInline, CalendarEventParticipantInline)
