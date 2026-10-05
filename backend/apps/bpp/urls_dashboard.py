"""Маршруты дашбордов модуля — ``/api/bpp/v1/dashboard/…`` (D-01 «Оплаты»,
A4.3).

Подключается сам: ``bpp/urls.py`` собирает все ``urls_*.py`` подмодулей.
``APPEND_SLASH = False``: путь в обоих написаниях.
"""

from django.urls import path

from . import views_dashboard as views

urlpatterns = [
    path("dashboard/payments", views.payments_dashboard),
    path("dashboard/payments/", views.payments_dashboard),
]
