"""Django-admin registration for the media domain (R2 remediation).

Final review of phases 2-3 flagged that ``apps.media_files`` had NO
``admin.py`` at all — its three models (``FileMetadata``, ``FileVariant``,
``AuditLog``) were silently unregistered and therefore un-gated (nothing for
``ServiceGatedAdminMixin`` to even sit on). See ``docs/superpowers/plans/
2026-07-20-remediation-phases-2-3-findings.md``, ``## R2``.

Decision Д4 (same doc): ``FileMetadata``/``FileVariant`` are READ-ONLY here.
Rows are created by the upload pipeline (``apps.media_files.services.
upload_service`` writing the file to storage AND the DB row together, plus
the variant-generation task deriving ``FileVariant`` rows from an existing
``FileMetadata``) — an admin-authored row would have no corresponding object
in storage (or vice versa: hand-adding a variant row with no rendition
actually written), i.e. an orphan the moment it's saved. Per the task brief,
the chosen shape is the simplest one that prevents that: ``has_add_permission``
and ``has_change_permission`` both hardcoded False (browsing/searching via
``has_view_permission`` still works), ``has_delete_permission`` left at its
default (gated by ``ServiceGatedAdminMixin`` + the normal permission system,
same as every other model here) — deleting a row through the admin doesn't
by itself desync anything worse than deleting it via the API/a purge job
would, so there's no need to also block delete to keep the pipeline honest.
"""

from django.contrib import admin
from django.db import models as db_models

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import AuditLog, FileMetadata, FileVariant

try:
    from django_json_widget.widgets import JSONEditorWidget
    _HAS_JSON_WIDGET = True
except ImportError:  # pragma: no cover - only if the package is ever removed
    _HAS_JSON_WIDGET = False


@admin.register(FileMetadata)
class FileMetadataAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "path", "owner_id", "scope", "kind", "mime", "size",
                     "is_public", "deleted_at", "created_at")
    list_filter = ("scope", "kind", "is_public", "storage_backend")
    search_fields = ("path", "sha256", "original_filename")
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request):
        # Д4: rows come from the upload pipeline (storage write + DB row
        # together); a hand-added row here would have nothing behind it in
        # storage. See module docstring.
        return False

    def has_change_permission(self, request, obj=None):
        # Д4: hand-editing (e.g. flipping `path` or `sha256`) would desync
        # this row from the actual object in storage without touching it.
        # Browsing/search (has_view_permission, left at the mixin's default)
        # still works — this is view-only, not hidden.
        return False


@admin.register(FileVariant)
class FileVariantAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "file", "variant", "path", "mime", "size", "width",
                     "height", "created_at")
    list_filter = ("variant",)
    search_fields = ("path", "variant", "file__path")
    autocomplete_fields = ("file",)
    readonly_fields = ("created_at",)

    def has_add_permission(self, request):
        # Д4: same reasoning as FileMetadataAdmin — variants are derived by
        # the make_variants task from an existing original, never hand-made.
        return False

    def has_change_permission(self, request, obj=None):
        # Д4: editing a variant's path/dimensions here wouldn't touch the
        # actual rendition sitting in storage.
        return False


@admin.register(AuditLog)
class AuditLogAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "user_id", "action", "resource_type", "resource_id",
                     "created_at")
    list_filter = ("action", "resource_type")
    search_fields = ("action", "resource_type", "resource_id", "correlation_id")
    readonly_fields = ("created_at",)

    if _HAS_JSON_WIDGET:
        formfield_overrides = {
            db_models.JSONField: {"widget": JSONEditorWidget},
        }

    def has_add_permission(self, request):
        # Intentionally hardcoded False, NOT `super().has_add_permission(...)
        # and self._service_enabled()`: audit rows are written by code only,
        # never authored by hand, so this is unconditionally stricter than
        # the service gate (denying add regardless of media's enabled state)
        # rather than a stand-in for it. Mirrors apps.cms.admin.AuditLogAdmin.
        return False
