from django.contrib import admin
from django.db import models as db_models

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import Item, User

try:
    from django_json_widget.widgets import JSONEditorWidget
    _HAS_JSON_WIDGET = True
except ImportError:  # pragma: no cover - only if the package is ever removed
    _HAS_JSON_WIDGET = False


@admin.register(User)
class UserAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    # `password` (db_column password_hash) is intentionally excluded: this
    # admin has no password-change form/flow (unlike django.contrib.auth's
    # stock UserAdmin, which we don't use — decision Р1 dropped
    # PermissionsMixin), so exposing the raw hash field for direct editing
    # would let an operator overwrite it with a plaintext value that
    # check_password() would then treat as a valid pbkdf2/bcrypt hash — or
    # just leak the hash in the rendered form. Never add it back without
    # also building a real "set new password" control.
    exclude = ("password",)

    list_display = ("id", "username", "email", "status", "is_staff",
                     "is_superuser", "date_joined")
    list_filter = ("status", "is_staff", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name")
    readonly_fields = ("date_joined", "created_at", "updated_at", "last_login")
    ordering = ("-date_joined",)

    if _HAS_JSON_WIDGET:
        formfield_overrides = {
            db_models.JSONField: {"widget": JSONEditorWidget},
        }


@admin.register(Item)
class ItemAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "title", "owner", "created_at")
    search_fields = ("title", "description")
    list_filter = ("created_at",)
    readonly_fields = ("created_at",)
    autocomplete_fields = ("owner",)
