from django.core.cache import cache

from .models import ServiceStatus

_CACHE_TTL = 5  # секунд; рубильник срабатывает быстро, но БД не дёргается на каждый запрос


class ServiceDisabled(Exception):
    def __init__(self, service: str, message: str):
        self.service = service
        self.message = message
        super().__init__(f"{service}: {message}")


def _status(name: str) -> tuple[bool, str]:
    key = f"svc-status:{name}"
    cached = cache.get(key)
    if cached is None:
        row = ServiceStatus.objects.filter(app_label=name).first()
        cached = (True, "") if row is None else (row.enabled, row.message)
        cache.set(key, cached, _CACHE_TTL)
    return cached


def service_enabled(name: str) -> bool:
    return _status(name)[0]


def require_service(name: str) -> None:
    enabled, message = _status(name)
    if not enabled:
        raise ServiceDisabled(name, message)
