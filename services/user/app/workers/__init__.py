"""Dramatiq broker setup for user-service workers.

Worker process command (docker-compose):
    dramatiq app.workers.actors --processes 2 --threads 4

The web process must also import this module (transitively via app.workers.actors)
to enqueue tasks via `actor.send(...)`.
"""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.settings import settings


broker = RedisBroker(url=settings.redis_url)
dramatiq.set_broker(broker)
