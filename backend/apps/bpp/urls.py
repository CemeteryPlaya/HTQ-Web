"""Маршруты /api/bpp/v1/.

Подмодуль держит маршруты в ``urls_<подмодуль>.py`` и вьюхи в
``views_<подмодуль>.py`` (импорт ``from . import views_<подмодуль> as views``) —
так у двух исполнителей нет общего файла, а сторожа прав
(``apps/access/tests/test_gate.py``) видят пару ``urls_x.py`` ↔ ``views_x.py``.
Здесь — только ``include`` подмодулей.
"""

from django.urls import include, path

from . import views

urlpatterns = [
    path("history/<str:object_type>/<str:object_id>", views.object_history),
    path("history/<str:object_type>/<str:object_id>/", views.object_history),
    path("", include("apps.bpp.urls_budget")),    # B2.1
    path("", include("apps.bpp.urls_requests")),  # B2.2, B2.3
    path("", include("apps.bpp.urls_accountable")),  # B4.1
]
