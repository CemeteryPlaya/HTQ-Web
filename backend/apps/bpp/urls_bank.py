"""Маршруты «Счета организации и шаблоны выписок» ``/api/bpp/v1/bank/…``
(A3.1) и загрузок выписок (A4.1) — подмодуль ``bpp_bank`` (рубильник по
префиксу ``/api/bpp/v1/bank``).

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``test_gate.py``) читает ``path(…, views.<имя>)``. Ключ в
адресе — ``str``, а не ``uuid``: неверный UUID вьюха превращает в 404 с
конвертом ``{"detail": …}`` (``uuid_or_404``).
"""

from django.urls import path

from . import views_bank as views

A = "bank/accounts/<str:account_id>"
T = "bank/templates/<str:template_id>"
IMP = "bank/imports/<str:import_id>"
LINE = "bank/lines/<str:line_id>"

urlpatterns = [
    path("bank/accounts", views.accounts_collection),
    path("bank/accounts/", views.accounts_collection),
    path(A, views.account_detail),
    path(f"{A}/", views.account_detail),
    path("bank/templates", views.templates_collection),
    path("bank/templates/", views.templates_collection),
    path(T, views.template_detail),
    path(f"{T}/", views.template_detail),
    path(f"{T}/preview", views.template_preview),
    path(f"{T}/preview/", views.template_preview),
    # Загрузки выписок (A4.1, задача 3).
    path("bank/imports", views.imports_collection),
    path("bank/imports/", views.imports_collection),
    path(IMP, views.import_get),
    path(f"{IMP}/", views.import_get),
    path(f"{IMP}/lines", views.import_lines),
    path(f"{IMP}/lines/", views.import_lines),
    # Сверка (A4.2, этап 4 A, задача 3).
    path(f"{IMP}/reconcile", views.import_reconcile),
    path(f"{IMP}/reconcile/", views.import_reconcile),
    path(f"{IMP}/impact", views.import_impact),
    path(f"{IMP}/impact/", views.import_impact),
    path(f"{IMP}/cancel", views.import_cancel),
    path(f"{IMP}/cancel/", views.import_cancel),
    path(f"{IMP}/export", views.import_export),
    path(f"{IMP}/export/", views.import_export),
    path(f"{LINE}/candidates", views.line_candidates),
    path(f"{LINE}/candidates/", views.line_candidates),
    path(f"{LINE}/match", views.line_match),
    path(f"{LINE}/match/", views.line_match),
    path(f"{LINE}/confirm", views.line_confirm),
    path(f"{LINE}/confirm/", views.line_confirm),
    path(f"{LINE}/cancel-match", views.line_cancel_match),
    path(f"{LINE}/cancel-match/", views.line_cancel_match),
    path(f"{LINE}/exclude", views.line_exclude),
    path(f"{LINE}/exclude/", views.line_exclude),
]
