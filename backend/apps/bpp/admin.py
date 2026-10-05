from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import AuditLog, NumberSequence
from .models.counterparties import Counterparty, CounterpartyBankAccount
from .models.settings import ModuleSetting


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


class CounterpartyBankAccountInline(admin.TabularInline):
    model = CounterpartyBankAccount
    extra = 0
    fields = ("iban", "bank_name", "bic", "currency", "is_primary", "is_active")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Counterparty)
class CounterpartyAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Просмотр справочника. Правка — через API модуля: там проверки БИН/ИИН,
    уникальность, версия и журнал; форма админки их обошла бы."""

    list_display = ("name", "reg_number", "country_code", "kind", "status",
                    "successful_documents", "verified_override")
    list_filter = ("status", "kind", "country_code")
    search_fields = ("name", "short_name", "reg_number")
    readonly_fields = ("id", "version", "created_at", "created_by", "updated_at", "updated_by",
                       "status", "block_reason", "blocked_at", "blocked_by",
                       "successful_documents", "verified_override", "kind", "country_code",
                       "reg_number")
    inlines = (CounterpartyBankAccountInline,)

    # Справочник архивный (ТЗ §18): на контрагента ссылаются договоры и счета,
    # удаление оставило бы их без стороны сделки.
    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


@admin.register(CounterpartyBankAccount)
class CounterpartyBankAccountAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("iban", "counterparty", "bic", "currency", "is_primary", "is_active")
    list_filter = ("is_active", "currency")
    search_fields = ("iban", "bic", "counterparty__name")
    readonly_fields = ("id", "counterparty", "iban", "bic", "created_at", "created_by",
                       "updated_at", "updated_by")

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


@admin.register(ModuleSetting)
class ModuleSettingAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("key", "value", "updated_at", "updated_by")
    readonly_fields = ("updated_at", "updated_by")

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user.pk
        super().save_model(request, obj, form, change)
