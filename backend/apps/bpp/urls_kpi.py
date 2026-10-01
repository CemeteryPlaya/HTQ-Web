"""Маршруты «KPI снабжения» — ``/api/bpp/v1/kpi/…`` (A5.2).

Подключается сам: ``bpp/urls.py`` собирает все ``urls_*.py`` подмодулей.
``APPEND_SLASH = False``: путь в обоих написаниях.
"""

from django.urls import path

from . import views_kpi as views

urlpatterns = [
    path("kpi/report", views.kpi_report),
    path("kpi/report/", views.kpi_report),
    path("kpi/report/export", views.kpi_report_export),
    path("kpi/report/export/", views.kpi_report_export),
    path("kpi/records", views.kpi_records),
    path("kpi/records/", views.kpi_records),
    path("kpi/records/<str:kpi_id>", views.kpi_card),
    path("kpi/records/<str:kpi_id>/", views.kpi_card),
    path("kpi/records/<str:kpi_id>/annul", views.kpi_annul),
    path("kpi/records/<str:kpi_id>/annul/", views.kpi_annul),
]
