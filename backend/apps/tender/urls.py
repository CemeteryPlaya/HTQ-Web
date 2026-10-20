"""Маршруты /api/tender/v1/. Каждая ручка — под api_view(module="tender",
level=…): аппка в TRANSLATED_APPS с рождения.

Подраздел держит маршруты в ``urls_<подраздел>.py`` и вьюхи в
``views_<подраздел>.py`` — пару видит сторож прав (``test_gate.py``).
"""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.tender.urls_requests")),
    path("", include("apps.tender.urls_tenders")),
    path("", include("apps.tender.urls_suppliers")),
    path("", include("apps.tender.urls_supplier")),
]
