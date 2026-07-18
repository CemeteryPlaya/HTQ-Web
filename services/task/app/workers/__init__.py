"""Dramatiq broker setup for task-service workers.

Worker process command (docker-compose):
    dramatiq app.workers.actors --processes 2 --threads 4
"""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.settings import settings


broker = RedisBroker(url=settings.redis_url)
dramatiq.set_broker(broker)
