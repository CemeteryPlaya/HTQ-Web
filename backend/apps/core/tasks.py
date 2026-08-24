from celery import shared_task

from apps.core import metrics
from apps.core.services import require_service


@shared_task
def ping(value: str) -> str:
    return f"pong:{value}"


@shared_task
def guarded_ping(service: str, value: str) -> str:
    """Образец для доменных tasks.py: первая строка — guard отключаемости."""
    require_service(service)
    return f"pong:{value}"


@shared_task
def collect_business_metrics() -> int:
    """Пересчитать бизнес-метрики и положить в кэш.

    Guard'а ``require_service`` здесь намеренно НЕТ, в отличие от доменных
    задач: наблюдаемость не принадлежит ни одному домену и обязана работать
    как раз тогда, когда домен выключили. Опрос отдельных аппок и так
    защищён — падение одной не роняет остальные (``metrics.collect_all``).

    Считается здесь, а не на скрейпе: гейдж с походом в БД при четырёх
    воркерах gunicorn'а превращается в пачку одинаковых запросов и не
    работает в мультипроцессном режиме. Возвращает число аппок, давших
    цифры — попадает в результат задачи и видно в Flower.
    """
    values = metrics.collect_all()
    metrics.store(values)
    return len(values)
