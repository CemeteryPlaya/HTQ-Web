"""Маршруты сводки группы — ``/api/bpp/v1/holding/summary`` (A8.1).

Подключается сам: ``bpp/urls.py`` собирает все ``urls_*.py``.
``APPEND_SLASH = False``: путь в обоих написаниях.
"""

from django.urls import path

from . import views_holding as views

urlpatterns = [
    path("holding/summary", views.holding_summary),
    path("holding/summary/", views.holding_summary),
]
