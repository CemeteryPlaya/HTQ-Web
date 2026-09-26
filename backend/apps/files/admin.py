"""Django-admin для файловой подсистемы.

* «Типы файлов» — справочник фиксирован разделом 21 ТЗ: строки не заводятся
  и не удаляются, меняется только размер (ТЗ стр. 61: «Нет / размеры /
  нет»), и не выше потолка шлюза ``FILES_UPLOAD_CEILING_MB``.
* «Файлы объектов» — только просмотр: версия неизменяема по ТЗ, а удаление
  строки отправленного документа нарушило бы «файлы не удаляются физически
  после отправки». Удаление — только через API владельца.
* «Журнал файлов» — только просмотр: аудит (ТЗ §25.2) пишется вставкой и не
  правится никем.
"""

from django import forms
from django.conf import settings
from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import FileEvent, FileObject, FileType


class FileTypeForm(forms.ModelForm):
    class Meta:
        model = FileType
        fields = ("max_mb",)

    def clean_max_mb(self):
        value = self.cleaned_data["max_mb"]
        ceiling = settings.FILES_UPLOAD_CEILING_MB
        if not 1 <= value <= ceiling:
            raise forms.ValidationError(
                f"От 1 до {ceiling} МБ: больший файл не пропустит шлюз.")
        return value


@admin.register(FileType)
class FileTypeAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    form = FileTypeForm
    list_display = ("code", "name", "owner_type", "max_mb", "updated_at")
    list_filter = ("owner_type",)
    readonly_fields = ("code", "owner_type", "name", "formats", "sort_order",
                       "updated_at", "updated_by_id")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by_id = request.user.pk
        super().save_model(request, obj, form, change)


@admin.register(FileObject)
class FileObjectAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "owner_type", "owner_id", "company_slug", "file_type",
                    "name", "version_no", "is_replaced", "uploaded_by_name",
                    "uploaded_at", "deleted_at")
    list_filter = ("owner_type", "file_type", "is_replaced")
    search_fields = ("name", "sha256", "storage_key")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FileEvent)
class FileEventAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "event", "owner_type", "owner_id", "company_slug",
                    "file_id", "actor_id", "ip")
    list_filter = ("event", "owner_type")
    search_fields = ("=owner_id", "=file_id", "=actor_id", "ip")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
