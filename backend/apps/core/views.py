"""Платформенные (не доменные) HTTP-вьюхи: liveness/readiness, реестр
вкл/выкл сервисов и админ-панель инфраструктуры.

Пути объявляются ПОЛНОСТЬЮ в apps/core/urls.py (аппка смонтирована в корень
"" — у неё нет API_PREFIX, см. htqweb/urls.py), поэтому здесь соседствуют
``/health/``, ``/api/core/v1/...`` и ``/api/admin/v1/...``.
"""
from datetime import datetime, timezone

from django.db import connection
from django.http import JsonResponse
from pydantic import BaseModel, Field

from htqweb.http import api_view, json_error

from apps.core import infrastructure
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
