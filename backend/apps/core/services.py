import logging

from django.core.cache import cache

from .models import ServiceStatus

logger = logging.getLogger(__name__)

_CACHE_TTL = 5  # секунд; рубильник срабатывает быстро, но БД не дёргается на каждый запрос


class ServiceDisabled(Exception):
    def __init__(self, service: str, message: str):
        self.service = service
        self.message = message
        super().__init__(f"{service}: {message}")


def disabled_payload(service: str, message: str) -> dict:
    """Единственный источник тела 503-envelope для отключённого сервиса.

    Используется и HTTP-гейтом (ServiceGateMiddleware), и api_view при
    перехвате ServiceDisabled из require_service() — межаппный вызов должен
    деградировать в тот же контракт, что и внешний HTTP-запрос.
    """
    return {"detail": message or "Сервис в данный момент недоступен",
            "code": "service_disabled", "service": service}


def service_status(name: str) -> tuple[bool, str]:
    """Публичный геттер статуса сервиса (кэш 5с, БД — источник истины).

    Fail-open по кэшу: недоступный Redis не должен ронять весь трафик
    (см. ServiceGateMiddleware, который дёргает это на каждый запрос) —
    ошибка cache.get/set логируется и запрос уходит напрямую в БД. Ошибка
    самой БД НЕ глушится и пробрасывается выше как есть.
    """
    key = f"svc-status:{name}"
    try:
        cached = cache.get(key)
    except Exception:
        logger.warning("cache.get failed for key %s; falling back to DB", key,
                       exc_info=True)
        cached = None
    if cached is None:
        row = ServiceStatus.objects.filter(app_label=name).first()
        cached = (True, "") if row is None else (row.enabled, row.message)
        try:
            cache.set(key, cached, _CACHE_TTL)
        except Exception:
            logger.warning("cache.set failed for key %s; continuing without cache",
                           key, exc_info=True)
    return cached


def service_enabled(name: str) -> bool:
    return service_status(name)[0]


def require_service(name: str) -> None:
    enabled, message = service_status(name)
    if not enabled:
        raise ServiceDisabled(name, message)
