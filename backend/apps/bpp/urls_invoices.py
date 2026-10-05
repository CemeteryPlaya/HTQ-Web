"""Маршруты счёта ``/api/bpp/v1/invoices…`` — подмодуль ``bpp_invoices``.

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``test_gate.py``) читает ``path(…, views.<имя>)``.
"""

from django.urls import path

from . import views_invoices as views

INV = "invoices/<uuid:invoice_id>"

urlpatterns = [
    path("invoices", views.invoices_collection),
    path("invoices/", views.invoices_collection),
    path("invoices/batch-decision", views.invoice_batch_decision),
    path("invoices/batch-decision/", views.invoice_batch_decision),
    path("invoices/threshold", views.invoice_threshold),
    path("invoices/threshold/", views.invoice_threshold),
    path("invoices/export-queue", views.invoice_export_queue),
    path("invoices/export-queue/", views.invoice_export_queue),
    path(INV, views.invoice_detail),
    path(f"{INV}/", views.invoice_detail),
    path(f"{INV}/submit", views.invoice_submit),
    path(f"{INV}/submit/", views.invoice_submit),
    path(f"{INV}/cancel", views.invoice_cancel),
    path(f"{INV}/cancel/", views.invoice_cancel),
    path(f"{INV}/decision", views.invoice_decision),
    path(f"{INV}/decision/", views.invoice_decision),
    path(f"{INV}/select-alternative", views.invoice_select_alternative),
    path(f"{INV}/select-alternative/", views.invoice_select_alternative),
    path(f"{INV}/payments", views.invoice_payment),
    path(f"{INV}/payments/", views.invoice_payment),
    path(f"{INV}/payments/<uuid:mark_id>/cancel", views.invoice_payment_cancel),
    path(f"{INV}/payments/<uuid:mark_id>/cancel/", views.invoice_payment_cancel),
    path(f"{INV}/request-docs", views.invoice_request_docs),
    path(f"{INV}/request-docs/", views.invoice_request_docs),
    path(f"{INV}/submit-docs", views.invoice_submit_docs),
    path(f"{INV}/submit-docs/", views.invoice_submit_docs),
    path(f"{INV}/accept-docs", views.invoice_accept_docs),
    path(f"{INV}/accept-docs/", views.invoice_accept_docs),
    path(f"{INV}/return-docs", views.invoice_return_docs),
    path(f"{INV}/return-docs/", views.invoice_return_docs),
]
