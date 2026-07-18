from datetime import datetime, timezone

from django.db import connection
from django.http import JsonResponse

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
