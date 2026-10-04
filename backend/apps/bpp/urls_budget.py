"""Маршруты бюджета ``/api/bpp/v1/budgets…`` — подмодуль ``bpp_budget``.

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные,
без хелпера: сторож прав (``test_gate.py``) читает ``path(…, views.<имя>)``.
"""

from django.urls import path

from . import views_budget as views

B = "budgets/<uuid:budget_id>"

urlpatterns = [
    path("budgets", views.budgets),
    path("budgets/", views.budgets),
    path("budgets/lines", views.budget_lines),
    path("budgets/lines/", views.budget_lines),
    path("budgets/balance", views.budget_balance),
    path("budgets/balance/", views.budget_balance),
    path(B, views.budget_detail),
    path(f"{B}/", views.budget_detail),
    path(f"{B}/approve", views.budget_approve),
    path(f"{B}/approve/", views.budget_approve),
    path(f"{B}/correction", views.correction),
    path(f"{B}/correction/", views.correction),
    path(f"{B}/correction/approve", views.correction_approve),
    path(f"{B}/correction/approve/", views.correction_approve),
    path(f"{B}/correction/cancel", views.correction_cancel),
    path(f"{B}/correction/cancel/", views.correction_cancel),
    path(f"{B}/close", views.budget_close),
    path(f"{B}/close/", views.budget_close),
    path(f"{B}/reopen", views.budget_reopen),
    path(f"{B}/reopen/", views.budget_reopen),
    path(f"{B}/versions", views.budget_versions),
    path(f"{B}/versions/", views.budget_versions),
    path(f"{B}/versions/<int:version_no>", views.budget_version),
    path(f"{B}/versions/<int:version_no>/", views.budget_version),
]
