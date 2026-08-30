"""Django-админка доступа — вся под ``ServiceGatedAdminMixin``.

Второй вход в те же данные, поэтому ограничения целостности стоят в БД, а не
только в схемах запросов: администратор правит строки мимо вьюх.
"""

from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import PositionRole, Role, RoleAssignment, RolePermission


class PermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0


@admin.register(Role)
class RoleAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("code", "title", "is_system")
    list_filter = ("is_system",)
    search_fields = ("code", "title")
    inlines = [PermissionInline]


@admin.register(PositionRole)
class PositionRoleAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("company_slug", "position_id", "role")
    list_filter = ("company_slug",)
    search_fields = ("company_slug",)


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("company_slug", "user_id", "role", "scope_kind", "scope_id")
    list_filter = ("company_slug", "scope_kind")
    search_fields = ("company_slug",)
