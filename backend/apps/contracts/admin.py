"""Регистрация домена contracts в django-admin.

Каждый ``ModelAdmin`` подмешивает ``ServiceGatedAdminMixin`` — рефлексивный
мета-тест ``apps/core/tests/test_invariants.py`` (Test 2) роняет сборку, если
появится незагейченный.

``Budget`` показывает «выделено»/«законтрактовано»/«остаток» вычисляемыми
колонками (read-only). Хранимых полей под них нет и появиться не должно — см.
докстринг ``services/budget_calc.py``: «выделено» это сумма строк, остальное
выводится из договоров.

Строки бюджета редактируются ВЛОЖЕННО (``BudgetLineInline``), а не отдельным
разделом: строка вне своего бюджета не имеет смысла — у неё нет ни года, ни
валюты, ни администратора.
"""

from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import (
    Administrator,
    AdvancePayment,
    Agreement,
    Budget,
    BudgetLine,
    Counterparty,
    Country,
    Invoice,
    Program,
)
from .services import budget_calc


@admin.register(Country)
class CountryAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "iso_code")
    search_fields = ("name", "iso_code")


@admin.register(Program)
class ProgramAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "code", "name", "expense_item", "is_active")
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


class BudgetLineInline(admin.TabularInline):
    model = BudgetLine
    extra = 0
    fields = ("program", "amount", "note", "committed_display", "remaining_display")
    readonly_fields = ("committed_display", "remaining_display")
    raw_id_fields = ("program",)

    @admin.display(description="Законтрактовано")
    def committed_display(self, obj):
        # Незаполненная строка формы «добавить» ещё не имеет pk — считать по
        # ней нечего, и запрос с pk=None вернул бы занятость чужих строк.
        return budget_calc.committed_for(obj.pk) if obj.pk else "—"

    @admin.display(description="Остаток")
    def remaining_display(self, obj):
        return budget_calc.remaining_for(obj) if obj.pk else "—"


@admin.register(Budget)
class BudgetAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "administrator", "period_year", "currency",
                    "allocated_display", "committed_display", "remaining_display",
                    "status", "approval_state")
    list_filter = ("status", "approval_state", "period_year", "currency")
    search_fields = ("administrator__project_name",
                     "lines__program__name", "lines__program__expense_item")
    readonly_fields = ("created_at", "updated_at", "allocated_display",
                       "committed_display", "remaining_display", "approval_state")
    inlines = (BudgetLineInline,)
    # ``approval_state`` показывается, но не правится: его единственный
    # писатель — ``apps.signoff.services.engine``, и он пишет его в одной
    # транзакции с состоянием процесса. Правка отсюда развела бы их, и
    # «согласовано» на объекте перестало бы значить, что согласование было.

    # Страна администратора — в `list_select_related`, потому что его
    # подпись в списке («проект страна») читает её на каждой строке.
    list_select_related = ("administrator", "administrator__country")

    def get_queryset(self, request):
        # Итоги считаются по строкам — без prefetch это запрос на бюджет.
        return super().get_queryset(request).prefetch_related("lines")

    def _totals(self, obj):
        return budget_calc.totals_for_budget(obj.lines.all())

    @admin.display(description="Выделено")
    def allocated_display(self, obj):
        return self._totals(obj)["allocated"]

    @admin.display(description="Законтрактовано")
    def committed_display(self, obj):
        return self._totals(obj)["committed"]

    @admin.display(description="Остаток")
    def remaining_display(self, obj):
        return self._totals(obj)["remaining"]


@admin.register(Counterparty)
class CounterpartyAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "bin_iin", "country", "vat", "contact_name",
                    "phone", "status", "approval_state")
    list_filter = ("status", "approval_state", "country", "vat")
    search_fields = ("name", "bin_iin", "address", "contact_name", "phone",
                     "email")
    readonly_fields = ("created_at", "updated_at", "approval_state")
    list_select_related = ("country",)


@admin.register(Agreement)
class AgreementAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "number", "name", "counterparty", "budget_line",
                    "amount", "currency", "payment_type", "status",
                    "approval_state", "signed_date")
    list_filter = ("status", "approval_state", "payment_type", "currency",
                   "budget_line__budget__period_year")
    search_fields = ("number", "name", "counterparty__name", "counterparty__bin_iin")
    readonly_fields = ("created_at", "updated_at", "file_id", "approval_state")
    raw_id_fields = ("budget_line", "counterparty")
    list_select_related = ("budget_line", "budget_line__program", "counterparty")

    # `status` правится админом напрямую, в обход
    # ``agreement_service.change_status``: django-admin — инструмент
    # исправления данных, и запретить здесь ручную починку статуса значило бы
    # оставить систему без выхода из состояния, куда её загнал баг. Проверка
    # лимита при этом НЕ выполняется — учитывайте, правя статус отсюда.


@admin.register(Invoice)
class InvoiceAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "counterparty", "budget_line", "amount",
                    "currency", "status", "approval_state", "created_at")
    list_filter = ("status", "approval_state", "currency",
                   "budget_line__budget__period_year")
    search_fields = ("name", "note", "counterparty__name",
                     "counterparty__bin_iin")
    readonly_fields = ("created_at", "updated_at", "file_id", "currency",
                       "approval_state")
    raw_id_fields = ("budget_line", "counterparty")
    list_select_related = ("budget_line", "budget_line__program", "counterparty")
    # `currency` read-only: она снимается со строки бюджета при создании, а не
    # задаётся руками (см. докстринг модели Invoice). `approval_state` тоже —
    # его единственный писатель — движок signoff.


@admin.register(AdvancePayment)
class AdvancePaymentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "agreement", "amount", "approval_state", "posting_number",
                    "paid_by", "paid_at", "created_at")
    list_filter = ("approval_state", "agreement__budget_line__budget__period_year")
    search_fields = ("agreement__number", "agreement__name", "posting_number")
    readonly_fields = ("created_at", "updated_at", "approval_state", "paid_by", "paid_at")
    raw_id_fields = ("agreement",)
    list_select_related = ("agreement", "agreement__counterparty")
