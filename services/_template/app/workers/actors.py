"""Dramatiq actors — register here so the worker entrypoint discovers them.

    dramatiq app.workers.actors

Every @dramatiq.actor function is auto-registered with the broker initialised
in app/workers/__init__.py.
"""

import logging

import dramatiq

# Ensure the broker is set up before any @dramatiq.actor declarations.
from app.workers import broker  # noqa: F401

logger = logging.getLogger(__name__)


@dramatiq.actor
def example_task(payload: dict) -> None:
    """Replace with real actors. Enqueue via `example_task.send({...})`."""
    logger.info("example_task received: %s", payload)
