"""Dramatiq workers for messenger service."""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.settings import settings

broker = RedisBroker(url=settings.redis_url)
dramatiq.set_broker(broker)
