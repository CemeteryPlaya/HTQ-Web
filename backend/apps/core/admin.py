"""Admin registration for apps.core.

``ServiceStatus`` is the operator-facing rubильник (switch) for every other
app's admin section (see ``htqweb.admin_gate.ServiceGatedAdminMixin``, which
every *other* app's ModelAdmin is wrapped in). This admin is deliberately
NOT wrapped in that mixin: gating the switch behind its own service-enabled
check would be a lockout footgun — if a superuser ever disabled ``core``
(or fat-fingered a row for it), the ONLY place to turn things back on would
itself refuse to load, with no other affordance to fix it. So ServiceStatus
stays reachable unconditionally (bounded only by the normal Django admin
permission model — an active superuser, per decision Р1).
"""

from django.contrib import admin
from django.core.cache import cache

from .models import ServiceStatus


@admin.register(ServiceStatus)
class ServiceStatusAdmin(admin.ModelAdmin):
    # Deliberately NOT ServiceGatedAdminMixin — see module docstring.

    list_display = ("app_label", "enabled", "message", "updated_at")
    list_editable = ("enabled",)
    search_fields = ("app_label", "message")
    list_filter = ("enabled",)
    readonly_fields = ("updated_at",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Must match apps.core.services.service_status()'s cache key EXACTLY,
        # or a flip here would still take up to _CACHE_TTL (5s) to take
        # effect instead of applying immediately.
        cache.delete(f"svc-status:{obj.app_label}")
