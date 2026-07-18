"""Dramatiq workers — background processing for this service.

Worker process command (docker-compose):
    dramatiq app.workers.actors --processes 2 --threads 4

The web process MUST also import this module (or app.workers.actors directly)
if it wants to enqueue tasks via `actor.send(...)`. See app/workers/actors.py.
"""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.settings import settings


broker = RedisBroker(url=settings.redis_url)
dramatiq.set_broker(broker)
