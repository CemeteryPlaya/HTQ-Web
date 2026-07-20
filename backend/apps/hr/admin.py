"""Django-админка домена hr — вся под ServiceGatedAdminMixin.

Гейт обязателен: при выключенном сервисе `hr` админские экраны домена должны
отдавать 503-native (решение Р5), а не показывать данные выключенного домена.
Мета-тест apps/core/tests/test_invariants.py (Test 2) проверяет это
рефлексивно — незарегистрированная или не-gated модель уронит сюиту.
"""

from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import Department, Employee, LevelThreshold, OrgSettings, Position


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


@admin.register(OrgSettings)
class OrgSettingsAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("key", "value", "updated_at")
    search_fields = ("key",)
    readonly_fields = ("updated_at",)
