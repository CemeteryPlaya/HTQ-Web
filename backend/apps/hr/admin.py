"""Django-админка домена hr — вся под ServiceGatedAdminMixin.

Гейт обязателен: при выключенном сервисе `hr` админские экраны домена должны
отдавать 503-native (решение Р5), а не показывать данные выключенного домена.
Мета-тест apps/core/tests/test_invariants.py (Test 2) проверяет это
рефлексивно — незарегистрированная или не-gated модель уронит сюиту.
"""

from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import (
    Application,
    AuditLog,
    CalendarDay,
    Department,
    Document,
    Employee,
    EmployeeDayOverride,
    EmployeeDocumentBlob,
    EmployeeGroups,
    EmployeeShiftAssignment,
    EmployeeWeekTemplate,
    LevelThreshold,
    OrgSettings,
    PersonnelHistory,
    PMO,
    PMODepartment,
    PMOMember,
    PMOPosition,
    Position,
    ReportingRelation,
    ShiftPattern,
    StaffingPosition,
    TimeEntry,
    Vacancy,
    WeekTemplate,
)


@admin.register(Department)
class DepartmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "path", "unit_type", "manager", "is_active")
    list_filter = ("is_active", "unit_type")
    search_fields = ("name", "path")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("manager",)


@admin.register(Position)
class PositionAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "title", "department", "weight", "level",
                    "is_system", "is_active")
    list_filter = ("is_active", "is_system", "level")
    search_fields = ("title",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Employee)
class EmployeeAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "last_name", "first_name", "email", "department",
                    "position", "status", "is_deleted")
    list_filter = ("status", "is_deleted", "department")
    search_fields = ("last_name", "first_name", "email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(LevelThreshold)
class LevelThresholdAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("level_number", "weight_from", "weight_to", "label", "color")
    ordering = ("level_number",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ReportingRelation)
class ReportingRelationAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "superior_position", "subordinate_position", "relation_type",
                    "effective_from", "effective_to")
    list_filter = ("relation_type",)
    autocomplete_fields = ("superior_position", "subordinate_position")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OrgSettings)
class OrgSettingsAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("key", "value", "updated_at")
    search_fields = ("key",)
    readonly_fields = ("updated_at",)


@admin.register(AuditLog)
class AuditLogAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "entity_type", "entity_id", "action", "changed_by", "created_at")
    list_filter = ("entity_type", "action")
    search_fields = ("entity_type", "entity_id", "changed_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Vacancy)
class VacancyAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "title", "department", "position", "status",
                    "opened_at", "closed_at")
    list_filter = ("status", "department")
    search_fields = ("title",)
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("department", "position", "assigned_recruiter")


@admin.register(Application)
class ApplicationAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "candidate_name", "candidate_email", "vacancy", "status", "applied_at")
    list_filter = ("status",)
    search_fields = ("candidate_name", "candidate_email")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("vacancy",)


@admin.register(TimeEntry)
class TimeEntryAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "employee", "date", "start_time", "end_time", "break_minutes")
    list_filter = ("date",)
    search_fields = ("project", "task")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("employee",)


@admin.register(StaffingPosition)
class StaffingPositionAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "position", "department", "grade", "headcount", "salary")
    list_filter = ("department",)
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("position", "department")


@admin.register(PersonnelHistory)
class PersonnelHistoryAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "employee", "event_type", "event_date", "created_by")
    list_filter = ("event_type",)
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("employee", "from_department", "to_department", "from_position", "to_position")


@admin.register(WeekTemplate)
class WeekTemplateAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "is_default")
    list_filter = ("is_default",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(CalendarDay)
class CalendarDayAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "day", "day_type", "norm_hours")
    list_filter = ("day_type",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmployeeWeekTemplate)
class EmployeeWeekTemplateAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "employee", "week_template")
    autocomplete_fields = ("employee", "week_template")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ShiftPattern)
class ShiftPatternAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "holidays_off")
    list_filter = ("holidays_off",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmployeeShiftAssignment)
class EmployeeShiftAssignmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "employee", "shift_pattern", "anchor_date")
    autocomplete_fields = ("employee", "shift_pattern")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmployeeDayOverride)
class EmployeeDayOverrideAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "employee", "day", "day_type", "norm_hours")
    list_filter = ("day_type",)
    autocomplete_fields = ("employee",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Document)
class DocumentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "title", "doc_type", "employee", "uploaded_by", "file_size")
    list_filter = ("doc_type",)
    search_fields = ("title",)
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("employee", "uploaded_by")


@admin.register(EmployeeDocumentBlob)
class EmployeeDocumentBlobAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "employee_id", "doc_type", "created_at")
    list_filter = ("doc_type",)
    readonly_fields = ("created_at",)


@admin.register(EmployeeGroups)
class EmployeeGroupsAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "employee_id")


@admin.register(PMO)
class PMOAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "code", "status", "head_employee")
    list_filter = ("status",)
    search_fields = ("name", "code")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("head_employee",)


@admin.register(PMOMember)
class PMOMemberAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "pmo", "employee", "membership_type", "allocation_percent",
                    "is_primary", "from_date", "to_date")
    list_filter = ("membership_type", "is_primary")
    autocomplete_fields = ("pmo", "employee")


# PMODepartment/PMOPosition are NOT registered here — Django hard-rejects it.
# ``AdminSite.register`` (django/contrib/admin/sites.py) raises
# ``ImproperlyConfigured`` unconditionally for any model whose
# ``_meta.is_composite_pk`` is True, BEFORE any ModelAdmin subclass or mixin
# gets a say — there is no override point, ServiceGatedAdminMixin or
# otherwise. Both models use ``models.CompositePrimaryKey("pmo", ...)``
# (see models.py docstring above PMODepartment). This does not weaken the
# gate meta-test (apps/core/tests/test_invariants.py, Test 2): it only
# requires that a domain app with ≥1 model has ≥1 registered gated admin —
# ``hr`` already has dozens, including PMO/PMOMember above — not that every
# model is individually registered.
