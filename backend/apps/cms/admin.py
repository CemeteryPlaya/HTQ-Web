from django.contrib import admin
from django.db import models as db_models

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import AuditLog, Category, ContactRequest, News, NewsAttachment, Tag

try:
    from django_json_widget.widgets import JSONEditorWidget
    _HAS_JSON_WIDGET = True
except ImportError:  # pragma: no cover - only if the package is ever removed
    _HAS_JSON_WIDGET = False


@admin.register(Category)
class CategoryAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "slug", "name", "created_at")
    search_fields = ("slug", "name")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "slug", "name", "created_at")
    search_fields = ("slug", "name")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(News)
class NewsAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "title", "slug", "status", "published",
                     "published_at", "created_at")
    list_filter = ("status", "published", "category")
    search_fields = ("title", "slug", "content")
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("category_ref",)
    filter_horizontal = ("tags",)


@admin.register(ContactRequest)
class ContactRequestAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "first_name", "last_name", "email", "handled",
                     "created_at")
    list_filter = ("handled",)
    search_fields = ("first_name", "last_name", "email", "message")
    readonly_fields = ("created_at",)


@admin.register(NewsAttachment)
class NewsAttachmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "news", "role", "filename", "size", "content_type",
                     "created_at")
    list_filter = ("role",)
    search_fields = ("filename", "storage_path")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("news",)


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
        # Audit log rows are written by the app, not authored by hand.
        return False
