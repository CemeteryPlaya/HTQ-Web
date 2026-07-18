"""Structured logging configuration.

JSON output via structlog. Correlation ID is bound via contextvars, so every
log line inside a request carries correlation_id, service, and level.
"""

import logging
import sys

import structlog

from app.core.settings import settings


STANDARD_EVENTS = frozenset(
    {
        "service_startup",
        "service_shutdown",
        "request_received",
        "request_completed",
        "request_failed",
        "dramatiq_task_received",
        "dramatiq_task_completed",
        "dramatiq_task_failed",
        "apscheduler_job_run",
        "apscheduler_job_failed",
        "db_query_slow",
        "audit_log_recorded",
    }
)


def configure_logging() -> None:
    """Configure structlog + stdlib logging for JSON stdout output."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _add_service_name,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _add_service_name(_, __, event_dict: dict) -> dict:
    event_dict.setdefault("service", settings.service_name)
    return event_dict


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger. Use __name__ as the default."""
    return structlog.get_logger(name)
