"""Django-admin registration for the tasks domain (DoD §6.6 п.6).

Registered here, in the domain's own phase, so phase 9 reduces to
decommissioning the old sqladmin/adminjs panels rather than re-doing this
work. Every ``ModelAdmin`` mixes in ``ServiceGatedAdminMixin`` — the
reflective meta-test ``apps/core/tests/test_invariants.py`` (Test 2) fails
the build if one is added without it, and it did exactly that while this file
was still the empty prep scaffold.

``ProjectSite`` follows the same rule as the other junctions: it is edited
as an inline on the project, never as a standalone changelist. So does
``ContractorWorker`` — a person outside their organisation means nothing.
``ContractorEngagement`` is the exception among junctions: it carries a
contract, dates and a scope, and is searched by project and by site, so it
gets its own section.

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
    EquipmentCategory,
    EventException,
    Contractor,
    ContractorEngagement,
    ContractorWorker,
    DailyReport,
    DailyReportRevision,
    ProjectSite,
    ProjectStaffReport,
    ProjectStaffReportLine,
    ProjectStaffReportRevision,
    ResourceAllocation,
    ResourceRequirement,
    Roadmap,
    Site,
    SiteBlock,
    SiteBlockVolume,
    Label,
    Notification,
    ProductionDay,
    Project,
    Task,
    TaskActivity,
    TaskAssignee,
    TaskAttachment,
    TaskComment,
    TaskDelegate,
    TaskDepartmentLink,
    TaskLink,
    TaskSequence,
    TaskType,
    TaskWatcher,
    WorkRole,
    WorkVolumeType,
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


class ProjectSiteInline(admin.TabularInline):
    """Объекты проекта. Инлайн, а не отдельный раздел: строка «проект ↔
    объект» вне своего проекта не значит ничего."""

    model = ProjectSite
    extra = 0
    autocomplete_fields = ("site",)
    readonly_fields = ("created_at", "updated_at")


class SiteBlockInline(admin.TabularInline):
    """Блоки площадки. Инлайн: блок вне своего объекта не значит ничего —
    «блок 1» есть на каждой площадке и это разные блоки."""

    model = SiteBlock
    extra = 0
    readonly_fields = ("created_at", "updated_at")


@admin.register(Site)
class SiteAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "code", "status", "region",
                    "department_id", "created_at")
    list_filter = ("status", "region")
    search_fields = ("name", "code", "address")
    readonly_fields = ("created_at", "updated_at")
    inlines = (SiteBlockInline,)


class SiteBlockVolumeInline(admin.TabularInline):
    """Плановые объёмы блока — инлайн по тому же правилу, что ProjectSite."""

    model = SiteBlockVolume
    extra = 0
    autocomplete_fields = ("volume_type",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(SiteBlock)
class SiteBlockAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Свой раздел вдобавок к инлайну на площадке: объёмы правят из карточки
    блока, а вложенный инлайн внутри инлайна Django не умеет."""

    list_display = ("id", "site", "name", "code", "order", "status",
                    "start_date", "end_date")
    list_filter = ("status", "site")
    search_fields = ("name", "code", "site__name")
    autocomplete_fields = ("site",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (SiteBlockVolumeInline,)


@admin.register(WorkVolumeType)
class WorkVolumeTypeAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "slug", "name", "unit", "is_active")
    list_filter = ("is_active", "unit")
    search_fields = ("slug", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Roadmap)
class RoadmapAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Пакет работ на блоке. Свой раздел, а не инлайн проекта: роудмап
    ищут по блоку и площадке не реже, чем по проекту, и правят как
    самостоятельный план со сроками и владельцем."""

    list_display = ("id", "name", "project", "site_block", "site_name",
                    "status", "order", "planned_start_date",
                    "planned_end_date", "owner_id")
    # Площадка фильтром через блок: своей колонки у роудмапа нет и не должно
    # быть — она выводится из блока (см. докстринг модели).
    list_filter = ("status", "site_block__site")
    search_fields = ("name", "description", "project__name",
                     "site_block__name", "site_block__site__name")
    autocomplete_fields = ("project", "site_block")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("project", "site_block", "site_block__site")

    @admin.display(description="Площадка", ordering="site_block__site__name")
    def site_name(self, obj):
        return obj.site_block.site.name


@admin.register(Project)
class ProjectAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "status", "owner_id", "department_id",
                    "start_date", "end_date", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")
    inlines = (ProjectSiteInline,)


@admin.register(Label)
class LabelAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "color")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(EquipmentCategory)
class EquipmentCategoryAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "slug", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("slug", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WorkRole)
class WorkRoleAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "slug", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("slug", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Equipment)
class EquipmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "inventory_no", "category_name", "ownership",
                    "contractor", "is_active")
    list_filter = ("is_active", "ownership", "category")
    search_fields = ("name", "inventory_no")
    autocomplete_fields = ("contractor", "category")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("category", "contractor")

    @admin.display(description="Категория", ordering="category__name")
    def category_name(self, obj):
        # Не голый ``category``: модели этого аппа принципиально не
        # определяют ``__str__`` (только ``__repr__`` для отладки), так что
        # FK в колонке отрисовался бы как «EquipmentCategory object (3)» —
        # хуже, чем текст, который тут был до перевода на справочник.
        return obj.category.name if obj.category else "—"


class ContractorWorkerInline(admin.TabularInline):
    """Представители партнёра. Инлайн: человек вне своей организации не
    значит ничего, а ``user_id`` тут только читается — привязка аккаунта
    появится вместе с механизмом входа."""

    model = ContractorWorker
    extra = 0
    readonly_fields = ("user_id", "created_at", "updated_at")


@admin.register(Contractor)
class ContractorAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "bin_iin", "status", "contact_person",
                    "phone", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "short_name", "bin_iin", "contact_person")
    readonly_fields = ("created_at", "updated_at")
    inlines = (ContractorWorkerInline,)


@admin.register(ContractorEngagement)
class ContractorEngagementAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Отдельным разделом, а не инлайном: привлечение осмысленно само по
    себе (договор, сроки, объект) и его ищут по проекту и по объекту, а не
    только по партнёру."""

    list_display = ("id", "contractor", "project", "site", "roadmap",
                    "contract_no", "start_date", "end_date", "is_active")
    list_filter = ("is_active",)
    search_fields = ("contractor__name", "contract_no", "scope")
    autocomplete_fields = ("contractor", "project", "site", "roadmap")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ResourceRequirement)
class ResourceRequirementAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Потребность количеством — план, из которого растёт метрика
    роудмапа. Свой раздел: она осмысленна и до того, как появятся имена."""

    list_display = ("id", "kind", "quantity", "roadmap", "task", "work_role",
                    "equipment_category", "start_date", "end_date")
    list_filter = ("kind",)
    search_fields = ("note", "roadmap__name", "task__key", "task__summary")
    autocomplete_fields = ("roadmap", "work_role", "equipment_category")
    raw_id_fields = ("task",)
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("roadmap", "task", "work_role", "equipment_category")


@admin.register(ResourceAllocation)
class ResourceAllocationAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "task", "roadmap", "employee_id", "equipment",
                    "role", "allocation")
    raw_id_fields = ("task", "requirement")
    autocomplete_fields = ("roadmap",)
    readonly_fields = ("created_at", "updated_at")


class DailyReportRevisionInline(admin.TabularInline):
    """Лента версий — только чтение. Ревизия это снимок случившегося;
    отредактированная задним числом ревизия — подделка отчётности, ровно
    как отредактированная запись TaskActivity. Тот же приём, что у
    ``approvals.RequestFormTemplateVersion``."""

    model = DailyReportRevision
    extra = 0
    can_delete = False
    readonly_fields = ("revision_no", "work_date", "quantity", "headcount",
                       "comment", "edited_by_id", "edited_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DailyReport)
class DailyReportAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Единственный источник факта выполнения.

    ``work_date`` в списке первым столбцом после задачи: это дата
    ВЫПОЛНЕНИЯ работ, по которой всё и считается, а ``created_at`` (дата
    заполнения) — служебная и стоит в конце.
    """

    list_display = ("id", "task", "work_date", "volume_type", "quantity",
                    "headcount", "author_id", "current_revision",
                    "is_deleted", "created_at")
    list_filter = ("is_deleted", "volume_type", "work_date")
    search_fields = ("task__key", "task__summary", "comment")
    raw_id_fields = ("task",)
    autocomplete_fields = ("volume_type",)
    readonly_fields = ("current_revision", "created_at", "updated_at")
    date_hierarchy = "work_date"
    list_select_related = ("task", "volume_type")
    inlines = (DailyReportRevisionInline,)


class ProjectStaffReportLineInline(admin.TabularInline):
    """Строки «роль — сколько людей». Редактируемые, в отличие от ревизий:
    это текущее состояние отчёта, а не снимок случившегося."""

    model = ProjectStaffReportLine
    extra = 0
    autocomplete_fields = ("work_role",)


class ProjectStaffReportRevisionInline(admin.TabularInline):
    """Лента версий — только чтение, по той же причине, что у
    ``DailyReportRevisionInline``. ``lines`` показывается сырым JSON:
    снимок неизменяем, и разбирать его в виджет незачем."""

    model = ProjectStaffReportRevision
    extra = 0
    can_delete = False
    readonly_fields = ("revision_no", "work_date", "total_headcount", "lines",
                       "comment", "edited_by_id", "edited_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ProjectStaffReport)
class ProjectStaffReportAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Численность проекта по дням и блокам.

    ``work_date`` — дата ВЫХОДА людей, по ней всё и считается;
    ``created_at`` (дата заполнения) служебная и стоит в конце — то же
    расположение и по той же причине, что у ``DailyReportAdmin``.
    """

    list_display = ("id", "project", "site_block", "work_date",
                    "total_headcount", "author_id", "current_revision",
                    "is_deleted", "created_at")
    list_filter = ("is_deleted", "work_date", "project")
    search_fields = ("project__name", "site_block__name", "comment")
    raw_id_fields = ("project", "site_block")
    readonly_fields = ("current_revision", "created_at", "updated_at")
    date_hierarchy = "work_date"
    list_select_related = ("project", "site_block")
    inlines = (ProjectStaffReportLineInline, ProjectStaffReportRevisionInline)

    @admin.display(description="Всего людей")
    def total_headcount(self, obj) -> int:
        return sum(line.headcount for line in obj.lines.all())

    def get_queryset(self, request):
        # Итог в списке считается по строкам — без prefetch это N+1 на
        # каждую страницу админки.
        return super().get_queryset(request).prefetch_related("lines")


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
