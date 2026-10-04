"""Маршруты подотчёта ``/api/bpp/v1/accountable…`` — подмодуль ``bpp_accountable``.

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``test_gate.py``) читает ``path(…, views.<имя>)``.
"""

from django.urls import path

from . import views_accountable as views

A = "accountable/<uuid:request_id>"
R = "accountable/reports/<uuid:report_id>"

urlpatterns = [
    path("accountable", views.accountable_collection),
    path("accountable/", views.accountable_collection),
    path(R + "/submit", views.report_submit),
    path(R + "/submit/", views.report_submit),
    path(R + "/file-link", views.report_file_link),
    path(R + "/file-link/", views.report_file_link),
    path(A, views.accountable_detail),
    path(A + "/", views.accountable_detail),
    path(A + "/submit", views.accountable_submit),
    path(A + "/submit/", views.accountable_submit),
    path(A + "/mark-paid", views.accountable_mark_paid),
    path(A + "/mark-paid/", views.accountable_mark_paid),
    path(A + "/reports", views.accountable_add_report),
    path(A + "/reports/", views.accountable_add_report),
]
