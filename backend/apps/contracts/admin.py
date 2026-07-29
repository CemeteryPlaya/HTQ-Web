"""Регистрация домена contracts в django-admin.

Каждый ``ModelAdmin`` подмешивает ``ServiceGatedAdminMixin`` — рефлексивный
мета-тест ``apps/core/tests/test_invariants.py`` (Test 2) роняет сборку, если
появится незагейченный.

``Budget`` показывает «законтрактовано»/«остаток» вычисляемыми колонками
(read-only). Хранимых полей под них нет и появиться не должно — см. докстринг
``services/budget_calc.py``.
"""

from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import Administrator, Agreement, Budget, Counterparty, Country, Program
from .services import budget_calc


@admin.register(Country)
class CountryAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "iso_code")
    search_fields = ("name", "iso_code")


@admin.register(Program)
class ProgramAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "expense_item", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "expense_item", "code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Administrator)
class AdministratorAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "project_name", "country", "user_id", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("project_name", "country__name")
    list_select_related = ("country",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Budget)
class BudgetAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "administrator", "program", "period_year",
                    "amount", "currency", "committed_display", "remaining_display",
                    "status", "approval_state")
    list_filter = ("status", "approval_state", "period_year", "currency")
    search_fields = ("administrator__project_name", "program__name", "program__expense_item")
    readonly_fields = ("created_at", "updated_at", "committed_display",
                       "remaining_display", "approval_state")
    # ``approval_state`` показывается, но не правится: его единственный
    # писатель — ``apps.signoff.services.engine``, и он пишет его в одной
    # транзакции с состоянием процесса. Правка отсюда развела бы их, и
    # «согласовано» на объекте перестало бы значить, что согласование было.

    # Страна администратора — в `list_select_related`, потому что его
    # подпись в списке («проект страна») читает её на каждой строке.
    list_select_related = ("administrator", "administrator__country", "program")

    @admin.display(description="Законтрактовано")
    def committed_display(self, obj):
        return budget_calc.committed_for(obj.pk)

    @admin.display(description="Остаток")
    def remaining_display(self, obj):
        return budget_calc.remaining_for(obj)


@admin.register(Counterparty)
class CounterpartyAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "bin_iin", "country", "vat", "status",
                    "approval_state")
    list_filter = ("status", "approval_state", "country")
    search_fields = ("name", "bin_iin", "address", "contacts")
    readonly_fields = ("created_at", "updated_at", "approval_state")
    list_select_related = ("country",)


@admin.register(Agreement)
class AgreementAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "number", "name", "counterparty", "budget",
                    "amount", "currency", "payment_type", "status",
                    "approval_state", "signed_date")
    list_filter = ("status", "approval_state", "payment_type", "currency",
                   "budget__period_year")
    search_fields = ("number", "name", "counterparty__name", "counterparty__bin_iin")
    readonly_fields = ("created_at", "updated_at", "file_id", "approval_state")
    raw_id_fields = ("budget", "counterparty")
    list_select_related = ("budget", "counterparty")

    # `status` правится админом напрямую, в обход
    # ``agreement_service.change_status``: django-admin — инструмент
    # исправления данных, и запретить здесь ручную починку статуса значило бы
    # оставить систему без выхода из состояния, куда её загнал баг. Проверка
    # лимита при этом НЕ выполняется — учитывайте, правя статус отсюда.
