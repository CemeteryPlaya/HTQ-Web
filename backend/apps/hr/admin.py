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
    Department,
    Employee,
    LevelThreshold,
    OrgSettings,
    Position,
    ReportingRelation,
    Vacancy,
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
