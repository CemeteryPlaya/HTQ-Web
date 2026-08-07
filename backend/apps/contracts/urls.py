"""Маршруты ``/api/contracts/v1/*``.

Монтируются автоматически по ``ContractsConfig.API_PREFIX`` — ``htqweb/urls.py``
не правится (правило №3, backend/README.md).

Вьюхи class-based (``htqweb.http.ApiView``), поэтому в ``path()`` идёт
``.as_view()``. Разведение по HTTP-методу делает ``View.dispatch``, а не
рукописный диспетчер, как в функциональных аппках.

``APPEND_SLASH = False``: Django сам не редиректит ``/foo`` → ``/foo/``, и
такой редирект на части клиентов теряет заголовок ``Authorization``. Поэтому
каждый путь зарегистрирован в обоих написаниях — со слэшем и без. Фронтенда
у модуля пока нет, поэтому «какое написание он реально шлёт» подсмотреть
негде: регистрируются оба, чтобы вопрос не всплыл при интеграции.
"""

from django.urls import path

from . import views

urlpatterns = [
    # ── Справочник choice-полей ──
    path("enums", views.EnumsView.as_view()),
    path("enums/", views.EnumsView.as_view()),

    # ── Страны ──
    path("countries", views.CountryCollectionView.as_view()),
    path("countries/", views.CountryCollectionView.as_view()),
    path("countries/<int:country_id>", views.CountryDetailView.as_view()),
    path("countries/<int:country_id>/", views.CountryDetailView.as_view()),

    # ── Программы (+ статья расходов) ──
    path("programs", views.ProgramCollectionView.as_view()),
    path("programs/", views.ProgramCollectionView.as_view()),
    path("programs/<int:program_id>", views.ProgramDetailView.as_view()),
    path("programs/<int:program_id>/", views.ProgramDetailView.as_view()),

    # ── Администраторы бюджета ──
    path("administrators", views.AdministratorCollectionView.as_view()),
    path("administrators/", views.AdministratorCollectionView.as_view()),
    path("administrators/<int:administrator_id>", views.AdministratorDetailView.as_view()),
    path("administrators/<int:administrator_id>/", views.AdministratorDetailView.as_view()),

    # ── Бюджеты и их строки ──
    # Вложенный `agreements` регистрируется РАНЬШЕ `<int:budget_id>`: Django
    # перебирает шаблоны сверху вниз, и хотя эти два не пересекаются (разное
    # число сегментов), более специфичный путь выше — порядок, который не
    # сломается при добавлении соседних вложенных маршрутов.
    path("budgets/<int:budget_id>/agreements", views.BudgetAgreementsView.as_view()),
    path("budgets/<int:budget_id>/agreements/", views.BudgetAgreementsView.as_view()),
    path("budgets/<int:budget_id>/submit", views.BudgetSubmitView.as_view()),
    path("budgets/<int:budget_id>/submit/", views.BudgetSubmitView.as_view()),
    path("budgets/<int:budget_id>/lines", views.BudgetLinesView.as_view()),
    path("budgets/<int:budget_id>/lines/", views.BudgetLinesView.as_view()),
    # Составное создание (форма-заявка). Регистрируется ДО `<int:budget_id>`,
    # иначе "full" попал бы в конвертер int и дал бы 404 вместо маршрута.
    path("budgets/full", views.BudgetFullCreateView.as_view()),
    path("budgets/full/", views.BudgetFullCreateView.as_view()),
    path("budgets", views.BudgetCollectionView.as_view()),
    path("budgets/", views.BudgetCollectionView.as_view()),
    path("budgets/<int:budget_id>", views.BudgetDetailView.as_view()),
    path("budgets/<int:budget_id>/", views.BudgetDetailView.as_view()),

    # Строки бюджета. Плоский список `budget-lines` — отдельный ресурс, а не
    # вложенный в бюджет: форма договора выбирает программу среди ВСЕХ
    # бюджетов сразу, и собирать её из вложенных списков значило бы звать
    # эндпоинт по разу на бюджет.
    path("budget-lines", views.BudgetLineCollectionView.as_view()),
    path("budget-lines/", views.BudgetLineCollectionView.as_view()),
    path("budget-lines/<int:line_id>", views.BudgetLineDetailView.as_view()),
    path("budget-lines/<int:line_id>/", views.BudgetLineDetailView.as_view()),

    # ── Реестр контрагентов ──
    # Составное создание (форма). До `<int:counterparty_id>` — иначе "full"
    # ушло бы в int-конвертер и дало 404.
    path("counterparties/<int:counterparty_id>/submit", views.CounterpartySubmitView.as_view()),
    path("counterparties/<int:counterparty_id>/submit/", views.CounterpartySubmitView.as_view()),
    path("counterparties/full", views.CounterpartyFullCreateView.as_view()),
    path("counterparties/full/", views.CounterpartyFullCreateView.as_view()),
    path("counterparties", views.CounterpartyCollectionView.as_view()),
    path("counterparties/", views.CounterpartyCollectionView.as_view()),
    path("counterparties/<int:counterparty_id>", views.CounterpartyDetailView.as_view()),
    path("counterparties/<int:counterparty_id>/", views.CounterpartyDetailView.as_view()),

    # ── Договоры ──
    path("agreements/<int:agreement_id>/submit", views.AgreementSubmitView.as_view()),
    path("agreements/<int:agreement_id>/submit/", views.AgreementSubmitView.as_view()),
    path("agreements/<int:agreement_id>/status", views.AgreementStatusView.as_view()),
    path("agreements/<int:agreement_id>/status/", views.AgreementStatusView.as_view()),
    path("agreements/<int:agreement_id>/file", views.AgreementFileView.as_view()),
    path("agreements/<int:agreement_id>/file/", views.AgreementFileView.as_view()),
    path("agreements/<int:agreement_id>/file-url", views.AgreementFileUrlView.as_view()),
    path("agreements/<int:agreement_id>/file-url/", views.AgreementFileUrlView.as_view()),
    path("agreements", views.AgreementCollectionView.as_view()),
    path("agreements/", views.AgreementCollectionView.as_view()),
    path("agreements/<int:agreement_id>", views.AgreementDetailView.as_view()),
    path("agreements/<int:agreement_id>/", views.AgreementDetailView.as_view()),

    # ── Счета на оплату (без договора) ──
    # submit/status/file/file-url — до `<int:invoice_id>`, иначе более общий
    # путь перехватил бы их (как у договоров).
    path("invoices/<int:invoice_id>/submit", views.InvoiceSubmitView.as_view()),
    path("invoices/<int:invoice_id>/submit/", views.InvoiceSubmitView.as_view()),
    path("invoices/<int:invoice_id>/status", views.InvoiceStatusView.as_view()),
    path("invoices/<int:invoice_id>/status/", views.InvoiceStatusView.as_view()),
    path("invoices/<int:invoice_id>/file", views.InvoiceFileView.as_view()),
    path("invoices/<int:invoice_id>/file/", views.InvoiceFileView.as_view()),
    path("invoices/<int:invoice_id>/file-url", views.InvoiceFileUrlView.as_view()),
    path("invoices/<int:invoice_id>/file-url/", views.InvoiceFileUrlView.as_view()),
    path("invoices", views.InvoiceCollectionView.as_view()),
    path("invoices/", views.InvoiceCollectionView.as_view()),
    path("invoices/<int:invoice_id>", views.InvoiceDetailView.as_view()),
    path("invoices/<int:invoice_id>/", views.InvoiceDetailView.as_view()),

    # ── Предоплаты на основании договоров ───────────────────────────────
    path("advance-payments/<int:payment_id>/submit", views.AdvancePaymentSubmitView.as_view()),
    path("advance-payments/<int:payment_id>/submit/", views.AdvancePaymentSubmitView.as_view()),
    path("advance-payments/<int:payment_id>/payment-order", views.AdvancePaymentPaymentOrderView.as_view()),
    path("advance-payments/<int:payment_id>/payment-order/", views.AdvancePaymentPaymentOrderView.as_view()),
    path("advance-payments/<int:payment_id>/payment-order-url", views.AdvancePaymentPaymentOrderUrlView.as_view()),
    path("advance-payments/<int:payment_id>/payment-order-url/", views.AdvancePaymentPaymentOrderUrlView.as_view()),
    path("advance-payments", views.AdvancePaymentCollectionView.as_view()),
    path("advance-payments/", views.AdvancePaymentCollectionView.as_view()),
    path("advance-payments/<int:payment_id>", views.AdvancePaymentDetailView.as_view()),
    path("advance-payments/<int:payment_id>/", views.AdvancePaymentDetailView.as_view()),
]
