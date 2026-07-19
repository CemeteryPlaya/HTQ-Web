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

    def delete_model(self, request, obj):
        # Single-object delete view. A deleted row falls back to fail-open
        # "enabled" per service_status()'s ``row is None`` branch, so a
        # stale cached "disabled" would wrongly keep the service gated (or
        # vice versa) for up to _CACHE_TTL. Read app_label before super()
        # deletes the row (obj is a Python object, still readable after, but
        # do it up front for symmetry with delete_queryset below).
        app_label = obj.app_label
        super().delete_model(request, obj)
        cache.delete(f"svc-status:{app_label}")

    def delete_queryset(self, request, queryset):
        # Bulk "Delete selected" action. Must collect app_labels BEFORE
        # deleting — the rows (and thus obj.app_label) are gone after.
        app_labels = list(queryset.values_list("app_label", flat=True))
        super().delete_queryset(request, queryset)
        for app_label in app_labels:
            cache.delete(f"svc-status:{app_label}")
