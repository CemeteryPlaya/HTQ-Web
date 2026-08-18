"""Платформенные (не доменные) HTTP-вьюхи: liveness/readiness, реестр
вкл/выкл сервисов и админ-панель инфраструктуры.

Пути объявляются ПОЛНОСТЬЮ в apps/core/urls.py (аппка смонтирована в корень
"" — у неё нет API_PREFIX, см. htqweb/urls.py), поэтому здесь соседствуют
``/health/``, ``/api/core/v1/...`` и ``/api/admin/v1/...``.
"""
import os
from datetime import datetime, timezone

from django.db import connection
from django.http import HttpResponse, JsonResponse
from prometheus_client import CollectorRegistry, exposition, multiprocess
from prometheus_client.registry import REGISTRY
from pydantic import BaseModel, Field

from htqweb.http import api_view, json_error

from apps.core import infrastructure
from apps.core import metrics as business_metrics
from apps.core.models import KNOWN_SERVICES
from apps.core.services import service_enabled


def health(request):
    return JsonResponse({"status": "ok", "service": "backend",
                         "timestamp": datetime.now(timezone.utc).isoformat()})


def ready(request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def services_status(request):
    return JsonResponse(
        {"services": {name: service_enabled(name) for name in KNOWN_SERVICES}})


def metrics(request):
    """Экспозиция метрик для Prometheus.

    Своя вьюха вместо ``django_prometheus.exports.ExportToDjangoView``, и
    ровно по одной причине: ``backend-web`` — это ``gunicorn --workers 4``.
    Каждый воркер держит СВОЙ реестр в памяти, а скрейп попадает в случайный
    из четырёх, поэтому без общего хранилища графики пилили бы вчетверо.
    ``prometheus_client`` решает это мультипроцессным режимом: воркеры пишут
    в файлы каталога ``PROMETHEUS_MULTIPROC_DIR``, а собирает их
    ``MultiProcessCollector`` — вот он здесь и подключается.

    Без переменной (dev-``runserver``, ``backend-asgi``, тесты) отдаём
    обычный глобальный ``REGISTRY``: там процесс один, и городить каталог
    незачем.

    Аутентификации намеренно нет — эндпоинт не публикуется наружу: nginx
    его не проксирует, а порты бэкенда в проде не издаются на хост
    (docker-compose.yml). Prometheus ходит сюда по внутренней сети.
    """
    # Читаем бизнес-снимок ДО сбора и вне его. Внутри collect() обращаться к
    # кэшу нельзя: он обёрнут django-prometheus и сам инкрементит метрику,
    # то есть менял бы реестр во время его обхода — процесс вставал намертво
    # (воспроизводилось на ASGI; на WSGI маскировалось мультипроцессным
    # реестром, который пишет в файлы).
    business_metrics.refresh()

    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        # Бизнес-метрики читаются из общего кэша, а не из памяти процесса,
        # поэтому их коллектор кладётся на реестр отдельно: MultiProcessCollector
        # знает только про файлы воркеров и такую метрику не увидел бы.
        registry.register(business_metrics.BusinessMetricsCollector())
    else:
        registry = REGISTRY
        business_metrics.register(REGISTRY)

    # Prometheus сам просит нужный формат заголовком Accept (текст или
    # protobuf) — отдаём то, что он запросил, а не гадаем.
    encoder, content_type = exposition.choose_encoder(
        request.META.get("HTTP_ACCEPT", ""))
    return HttpResponse(encoder(registry), content_type=content_type)


# ═══════════════════════════════════════════════════════════════════════════
#  /api/admin/v1/infrastructure/* — порт services/admin/app/api/v1/
#  infrastructure.py (6 эндпойнтов). Логика — apps/core/infrastructure.py,
#  там же расписаны все отличия от источника.
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация: ``require_admin`` источника -> ``api_view(auth="jwt",
# admin=True)`` на всех шести. Страница отдаёт пароли инфраструктуры —
# ослаблять гейт нельзя ни на одном роуте, включая health-check'и (они
# раскрывают внутреннюю топологию).


class _RevealCredentialsRequest(BaseModel):
    """Порт ``RevealCredentialsRequest``."""

    password: str = Field(min_length=1)


def _no_store(response):
    """Порт ``_no_store``: ответы содержат (или могут содержать) секреты —
    ни браузеру, ни промежуточным кэшам их держать нельзя."""
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


@api_view(methods=("GET",), auth="jwt", admin=True)
def infrastructure_overview(request):
    """Порт ``get_infrastructure`` — GET /infrastructure/ (секреты замаскированы)."""
    return _no_store(JsonResponse(infrastructure.build_response(reveal=False)))


@api_view(methods=("POST",), auth="jwt", body=_RevealCredentialsRequest)
def infrastructure_reveal(request, data: _RevealCredentialsRequest):
    """Порт ``reveal_credentials`` — POST /infrastructure/credentials/reveal.

    ``admin=True`` здесь НЕ у декоратора, а проверяется вручную: гейт
    ``api_view(admin=True)`` отвечает 403 раньше, чем мы успели бы посчитать
    попытку в rate-limit'е, а этот роут — единственный, куда подбирают
    пароль. Порядок проверок источника сохранён: админство -> лимит ->
    пароль."""
    token = request.token
    if not token.is_elevated:
        return json_error("Admin privileges required", 403)

    try:
        infrastructure.check_reveal_rate_limit(token.user_id)
    except infrastructure.RateLimited as exc:
        return json_error(str(exc), 429)

    if not infrastructure.verify_admin_password(token, data.password):
        return json_error("Invalid admin password", 401)

    infrastructure.record_reveal(
        user_id=token.user_id,
        email=getattr(token, "email", None),
        ip=infrastructure.client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
    return _no_store(JsonResponse(infrastructure.build_response(reveal=True)))


@api_view(methods=("GET",), auth="jwt", admin=True)
def infrastructure_audit(request):
    """Порт ``audit_reveals`` — GET /infrastructure/audit/reveals."""
    return _no_store(JsonResponse(infrastructure.reveal_audit()))


@api_view(methods=("GET",), auth="jwt", admin=True)
def infrastructure_health(request):
    """Порт ``health_check_all`` — GET /infrastructure/health-check."""
    return _no_store(JsonResponse(infrastructure.health_all()))


@api_view(methods=("GET",), auth="jwt", admin=True)
def infrastructure_health_history(request):
    """Порт ``health_history`` — GET /infrastructure/health-history."""
    return _no_store(JsonResponse(infrastructure.health_history()))


@api_view(methods=("POST",), auth="jwt", admin=True)
def infrastructure_health_one(request, resource_id: str):
    """Порт ``health_check_one`` — POST /infrastructure/{resource_id}/health-check."""
    if resource_id not in infrastructure.HEALTH_CHECKS:
        return json_error("Unknown resource", 404)
    result = infrastructure.run_health(resource_id)
    infrastructure.invalidate_health_cache()
    return _no_store(JsonResponse(result))
