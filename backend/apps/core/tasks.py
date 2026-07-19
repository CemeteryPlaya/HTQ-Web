from celery import shared_task

from apps.core.services import require_service


@shared_task
def ping(value: str) -> str:
    return f"pong:{value}"


@shared_task
def guarded_ping(service: str, value: str) -> str:
    """Образец для доменных tasks.py: первая строка — guard отключаемости."""
    require_service(service)
    return f"pong:{value}"
