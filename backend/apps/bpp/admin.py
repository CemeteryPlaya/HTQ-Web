from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import AuditLog, NumberSequence


@admin.register(NumberSequence)
class NumberSequenceAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("prefix", "year", "last")
    readonly_fields = ("prefix", "year", "last")


@admin.register(AuditLog)
class AuditLogAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "object_type", "object_id", "action", "actor_id")
    list_filter = ("object_type", "action")

    # Журнал «только для записи» пишет только код модуля (services/core/audit):
    # строка, дописанная руками, была бы подделкой с произвольным actor_id.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
