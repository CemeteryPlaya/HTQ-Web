"""Маршрут фоновой выгрузки — ``/api/bpp/v1/exports/<id>`` (задача 6).

Подключается сам: ``bpp/urls.py`` собирает все ``urls_*.py`` подмодулей.
``APPEND_SLASH = False``: путь в обоих написаниях, как у остальных
``urls_*.py`` модуля. В адресе ``str``, а не ``uuid``: неверный UUID вьюха
превращает в 404 с конвертом ``{"detail": …}``, а не в HTML-страницу Django.
"""

from django.urls import path

from . import views_exports as views

urlpatterns = [
    path("exports/<str:job_id>", views.export_download),
    path("exports/<str:job_id>/", views.export_download),
]
