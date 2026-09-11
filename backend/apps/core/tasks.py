import logging

import httpx
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.core import digest, metrics
from apps.core.services import require_service
from htqweb.fallback import fallback

logger = logging.getLogger(__name__)


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


@shared_task
def send_daily_digest() -> str:
    """Утренняя сводка по бизнес-метрикам во второй Telegram-чат.

    Guard'а ``require_service`` нет по той же причине, что у
    ``collect_business_metrics``: наблюдаемость не принадлежит ни одному
    домену. (Мета-тест инвариантов проверяет только доменные аппки, core из
    выборки исключён.)

    Читает ГОТОВЫЙ снимок из кэша — ноль дополнительных запросов к базе.

    Не ретраится и не поднимает исключений НИКОГДА: несостоявшаяся сводка не
    повод будить дежурного и тем более не повод, чтобы Celery отправил её
    повторно четыре раза подряд в один и тот же чат.
    """
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_DIGEST_CHAT_ID", "")
    if not token or not chat_id:
        # Молчаливый no-op: тестовые стеки поднимаются без .env и не должны ни
        # ходить в сеть, ни писать тревожных строк. Та же форма, что у
        # apps/messenger/tasks.py::dispatch_push_notification без ключей FCM.
        logger.info("daily_digest_skipped: TELEGRAM_* не настроены")
        return "skipped"

    current = metrics.load()
    if not current:
        # Считать не из чего. load() уже сообщил об этом подменой
        # core.metrics.cache_empty, а вставший сборщик отдельно ловит правило
        # htqweb-business-metrics-stale — дублировать тревогу незачем.
        return "no-metrics"

    text = digest.render(
        current,
        cache.get(metrics.DIGEST_BASELINE_KEY),
        now=timezone.localtime(),
        base_url=getattr(settings, "PUBLIC_BASE_URL", ""),
    )

    try:
        response = httpx.post(
            "https://api.telegram.org/bot%s/sendMessage" % token,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
                # Сводка не будит — её читают, когда сядут за стол.
                "disable_notification": True,
            },
            timeout=10.0,
        )
        response.raise_for_status()
    except Exception as exc:
        # expected=True — не поблажка, а два конкретных требования:
        #  1) strict-режим (машина разработчика, pytest) не должен ронять beat
        #     из-за недоступного api.telegram.org;
        #  2) исключение здесь означало бы ретрай Celery, то есть ту же сводку
        #     в чат ещё раз.
        # Слышимость при этом НЕ теряется: строка FALLBACK уходит в лог
        # воркера, а её ловит правило htqweb-fallback-worker-logs — то есть
        # несостоявшаяся сводка станет предупреждением в ИНЦИДЕНТНОМ чате,
        # там, где на него посмотрят.
        fallback("core.digest.telegram_send_failed", None,
                 reason="не удалось отправить утреннюю сводку",
                 exc=exc, expected=True)
        return "failed"

    # Базовая линия обновляется ТОЛЬКО после успешной отправки: иначе
    # неудачная сводка съела бы «вчера», и завтрашние дельты соврали бы.
    cache.set(metrics.DIGEST_BASELINE_KEY, current, metrics.DIGEST_BASELINE_TTL)
    return "sent"
