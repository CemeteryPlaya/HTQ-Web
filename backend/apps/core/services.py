import logging

from django.core.cache import cache

from .models import ServiceStatus

logger = logging.getLogger(__name__)

_CACHE_TTL = 5  # секунд; рубильник срабатывает быстро, но БД не дёргается на каждый запрос

# Обязательное ядро платформы: эти домены есть у КАЖДОЙ компании и на уровне
# компании не выключаются (требование заказчика — «основной монолит функций,
# который точно будет у всех»). Глобальный рубильник ServiceStatus на них
# по-прежнему действует: он гасит домен на всей платформе, а не у одной
# компании, и нужен для регламентных работ.
CORE_MODULES = frozenset({"users", "companies", "core", "hr", "messenger",
                          "media", "cms"})


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
    _require_company_module(name)


def _require_company_module(name: str) -> None:
    """Второй, независимый слой рубильника — на уровне компании.

    Импорт локальный: apps.core грузится раньше apps.companies, а на уровне
    модуля это была бы циклическая зависимость фундамента от реестра.

    Вне контекста компании (Celery без company_slug, служебные роуты,
    общие домены) проверка не выполняется — там компанейского рубильника
    просто нет, и подставлять вместо него какой-либо дефолт было бы
    молчаливой подменой.
    """
    if name in CORE_MODULES:
        return
    from apps.companies.interface import module_enabled
    from htqweb.tenancy.context import current_company_or_none

    slug = current_company_or_none()
    if slug is None:
        return
    enabled, message = module_enabled(slug, name)
    if not enabled:
        raise ServiceDisabled(name, message)
