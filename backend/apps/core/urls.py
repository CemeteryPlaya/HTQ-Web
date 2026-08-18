"""Маршруты apps.core. Аппка смонтирована В КОРЕНЬ ("" в htqweb/urls.py — у
неё нет API_PREFIX), поэтому пути здесь пишутся полностью, вместе с
``api/<домен>/v1/``.

``APPEND_SLASH = False``, поэтому каждое написание регистрируется явно (та же
конвенция, что в apps/hr/urls.py, apps/cms/urls.py и т.д.) — фронт зовёт
инфраструктурные роуты и со слешем (``infrastructure/``), и без
(``infrastructure/health-check``), см. frontend/src/pages/AdminInfrastructure.tsx.
"""
from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("health/ready/", views.ready),
    path("api/core/v1/services/", views.services_status),

    # Метрики для Prometheus. В корне, а не под /api/<домен>/: это не часть
    # публичного API, и ServiceGateMiddleware гейтит только api-префиксы —
    # выключение любого домена не должно гасить наблюдаемость.
    path("metrics", views.metrics),
    path("metrics/", views.metrics),

    # ── /api/admin/v1/infrastructure/* — порт снесённого admin-сервиса ─────
    # Литеральные под-пути идут ДО общего <str:resource_id>, иначе
    # "credentials", "audit", "health-check" и "health-history" совпали бы
    # с ним как с именем ресурса.
    path("api/admin/v1/infrastructure/credentials/reveal", views.infrastructure_reveal),
    path("api/admin/v1/infrastructure/credentials/reveal/", views.infrastructure_reveal),

    path("api/admin/v1/infrastructure/audit/reveals", views.infrastructure_audit),
    path("api/admin/v1/infrastructure/audit/reveals/", views.infrastructure_audit),

    path("api/admin/v1/infrastructure/health-check", views.infrastructure_health),
    path("api/admin/v1/infrastructure/health-check/", views.infrastructure_health),

    path("api/admin/v1/infrastructure/health-history", views.infrastructure_health_history),
    path("api/admin/v1/infrastructure/health-history/", views.infrastructure_health_history),

    path("api/admin/v1/infrastructure/<str:resource_id>/health-check", views.infrastructure_health_one),
    path("api/admin/v1/infrastructure/<str:resource_id>/health-check/", views.infrastructure_health_one),

    path("api/admin/v1/infrastructure/", views.infrastructure_overview),
    path("api/admin/v1/infrastructure", views.infrastructure_overview),
]
