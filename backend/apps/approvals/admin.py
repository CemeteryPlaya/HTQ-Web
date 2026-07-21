"""Django-admin registration for the approvals domain (DoD §6.6 п.6).

Registered in the domain's own phase so phase 9 reduces to decommissioning
the old panels. Every ``ModelAdmin`` mixes in ``ServiceGatedAdminMixin``;
the reflective meta-test ``apps/core/tests/test_invariants.py`` (Test 2)
fails the build otherwise, and it did exactly that while this file was still
the empty prep scaffold.

Read-only by design, because these rows are written by the workflow engine
and hand-editing one would desync a live approval route:

* ``RequestFormTemplateVersion`` — immutable by contract. Instances pin a
  version id; editing a published schema would retroactively change the form
  someone already filled in.
* ``ApprovalAction`` — the engine creates one row per assignee and stamps it
  on action. Hand-setting ``action='approve'`` would advance a request
  without the runtime ever running its transition logic.
* ``RequestActivity`` / ``AuditLog`` — append-only trails; an edited entry is
  a forged record.
* ``NotificationsLog`` — ``dedup_key`` IS the de-duplication mechanism.
  Deleting a row silently re-enables a duplicate notification.

``JSONField`` columns get the platform's JSON editor widget where it is
available (``django_json_widget``, already an INSTALLED_APPS dependency) —
a raw textarea for a workflow document is unusable in practice.
"""

from django.contrib import admin
from django.db import models as db_models

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import (
    ApprovalAction,
    AuditLog,
    NotificationsLog,
    RequestActivity,
    RequestFormTemplate,
    RequestFormTemplateVersion,
    RequestInstance,
    RequestProject,
    RequestProjectMember,
    RequestReferenceRow,
    RequestReferenceSource,
    RequestStatsDaily,
    RequestWatcher,
)

try:
    from django_json_widget.widgets import JSONEditorWidget
    _JSON_OVERRIDE = {db_models.JSONField: {"widget": JSONEditorWidget}}
except ImportError:  # pragma: no cover - only if the package is removed
    _JSON_OVERRIDE = {}


class _ReadOnlyAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Browsable but not writable — see the module docstring for why each
    subclass must stay that way. ``has_delete_permission`` is left at the
    mixin's default: deleting is already gated by the service switch and the
    normal permission system, and it does not corrupt a running workflow the
    way an edit does."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class RequestProjectMemberInline(admin.TabularInline):
    model = RequestProjectMember
    extra = 0


@admin.register(RequestProject)
class RequestProjectAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "status", "owner_id", "department_id",
                    "currency", "budget_limit", "start_date", "end_date")
    list_filter = ("status", "currency")
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")
    inlines = (RequestProjectMemberInline,)


class RequestFormTemplateVersionInline(admin.TabularInline):
    model = RequestFormTemplateVersion
    extra = 0
    readonly_fields = ("version", "schema_json", "workflow_json",
                       "published_at", "published_by")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RequestFormTemplate)
class RequestFormTemplateAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "slug", "project", "status", "is_active",
                    "current_version_id", "created_by", "created_at")
    list_filter = ("status", "is_active", "project")
    search_fields = ("name", "slug", "description")
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = _JSON_OVERRIDE
    inlines = (RequestFormTemplateVersionInline,)


@admin.register(RequestFormTemplateVersion)
class RequestFormTemplateVersionAdmin(_ReadOnlyAdmin):
    list_display = ("id", "template", "version", "published_at",
                    "published_by")
    list_filter = ("template",)
    formfield_overrides = _JSON_OVERRIDE


class ApprovalActionInline(admin.TabularInline):
    model = ApprovalAction
    extra = 0
    readonly_fields = ("node_id", "step_index", "approver_id", "assigned_at",
                       "action", "comment", "acted_at", "due_at",
                       "reminded_at", "reminders_sent")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class RequestWatcherInline(admin.TabularInline):
    model = RequestWatcher
    extra = 0


@admin.register(RequestInstance)
class RequestInstanceAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "code", "title", "template", "project", "status",
                    "current_node_id", "initiator_id", "total_amount",
                    "currency", "requires_admin_attention", "submitted_at",
                    "finalized_at")
    list_filter = ("status", "requires_admin_attention", "template",
                   "project")
    search_fields = ("code", "title")
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = _JSON_OVERRIDE
    inlines = (ApprovalActionInline, RequestWatcherInline)


@admin.register(ApprovalAction)
class ApprovalActionAdmin(_ReadOnlyAdmin):
    list_display = ("id", "request", "node_id", "step_index", "approver_id",
                    "action", "acted_at", "due_at", "reminders_sent")
    list_filter = ("action",)
    search_fields = ("node_id", "comment")


@admin.register(RequestActivity)
class RequestActivityAdmin(_ReadOnlyAdmin):
    list_display = ("id", "request", "actor_id", "event_type", "created_at")
    list_filter = ("event_type",)
    formfield_overrides = _JSON_OVERRIDE


@admin.register(NotificationsLog)
class NotificationsLogAdmin(_ReadOnlyAdmin):
    list_display = ("id", "request", "recipient_id", "kind", "channel",
                    "dedup_key", "created_at")
    list_filter = ("kind", "channel")
    search_fields = ("dedup_key",)


@admin.register(RequestStatsDaily)
class RequestStatsDailyAdmin(_ReadOnlyAdmin):
    """Read-only: rows are UPSERTed by the rollup at finalisation and by the
    nightly reconciliation. A hand-edited counter would be overwritten on the
    next reconcile anyway — worse than useless, actively confusing."""

    list_display = ("id", "date", "project_id", "template_id", "created",
                    "approved", "rejected", "cancelled",
                    "sum_approved_amount")
    list_filter = ("date",)


class RequestReferenceRowInline(admin.TabularInline):
    model = RequestReferenceRow
    extra = 0
    formfield_overrides = _JSON_OVERRIDE


@admin.register(RequestReferenceSource)
class RequestReferenceSourceAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "slug", "name", "template_id", "created_by",
                    "created_at")
    search_fields = ("slug", "name")
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = _JSON_OVERRIDE
    inlines = (RequestReferenceRowInline,)


@admin.register(RequestReferenceRow)
class RequestReferenceRowAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Editable, unlike the other row-level models: manual reference sources
    are exactly the kind of lookup data an administrator is meant to curate
    by hand. Rows mirroring a request instance carry ``instance_id`` and are
    re-upserted by the runtime, so an edit there is transient — surfaced in
    the changelist rather than blocked, since the manual case is the common
    one."""

    list_display = ("id", "source", "instance_id")
    list_filter = ("source",)
    formfield_overrides = _JSON_OVERRIDE


@admin.register(AuditLog)
class AuditLogAdmin(_ReadOnlyAdmin):
    list_display = ("id", "user_id", "action", "resource_type", "resource_id",
                    "correlation_id", "created_at")
    list_filter = ("action", "resource_type")
    search_fields = ("resource_id", "correlation_id")
    formfield_overrides = _JSON_OVERRIDE
