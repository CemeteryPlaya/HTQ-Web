"""Celery background tasks for ``cms`` — ported from
``services/cms/app/workers/actors.py`` (Dramatiq actors) and
``services/cms/app/workers/scheduler.py`` (APScheduler cron job).

Every task below starts with ``require_service("cms")`` — same pattern as
``apps/core/tasks.py``'s ``guarded_ping`` — so a disabled ``cms`` app stops
processing enqueued/scheduled work in the background too, not just at the
HTTP layer (``ServiceGateMiddleware`` only gates the request/response
cycle; a queued task or a cron tick has no request to gate).

The FastAPI original's actors are ``sync`` functions running under an
``async``-only SQLAlchemy engine, hence their "no DB I/O here" comments —
that constraint does not apply here: the Django ORM is sync, so this port
does its DB work directly.
"""

from __future__ import annotations

import logging

import httpx
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.core.services import require_service

from .models import News

logger = logging.getLogger(__name__)


@shared_task
def translate_news(news_id: int, target_lang: str) -> None:
    """Translate a news article via DeepL (or whatever ``TRANSLATION_PROVIDER``
    says). Ported from ``actors.py::translate_news``.

    Provider is selected by ``settings.TRANSLATION_PROVIDER`` (default
    ``"deepl"``). Without ``settings.TRANSLATION_API_KEY`` this no-ops and
    logs — same behaviour as the FastAPI original, and it doubles as the
    network-free path exercised in tests (``TRANSLATION_API_KEY`` is blank
    by default in every settings module). Set the env var to enable.

    The original's own persistence step (write the translated body into
    ``News.translations``, a JSON column) was flagged there as a follow-up
    that never landed — the ported ``News`` model (Task 1.1) has no
    ``translations`` column either, so there is nothing to persist yet; only
    the provider-reachability check is ported, unchanged.
    """
    require_service("cms")

    if not settings.TRANSLATION_API_KEY:
        logger.info(
            "translate_news no-op: no TRANSLATION_API_KEY set "
            "(news_id=%d target=%s)",
            news_id,
            target_lang,
        )
        return

    provider = (settings.TRANSLATION_PROVIDER or "deepl").lower()
    logger.info(
        "translate_news start: news_id=%d target=%s provider=%s",
        news_id,
        target_lang,
        provider,
    )

    try:
        if provider == "deepl":
            with httpx.Client(timeout=15) as client:
                base = (settings.TRANSLATION_API_BASE or "https://api-free.deepl.com").rstrip("/")
                resp = client.post(
                    f"{base}/v2/translate",
                    headers={"Authorization": f"DeepL-Auth-Key {settings.TRANSLATION_API_KEY}"},
                    data={"text": "ping", "target_lang": target_lang.upper()},
                )
                logger.info(
                    "translate_news provider check: status=%d (news_id=%d)",
                    resp.status_code,
                    news_id,
                )
        else:
            logger.warning("translate_news: unknown provider=%s", provider)
    except httpx.HTTPError as exc:
        logger.error("translate_news: provider unreachable: %s", exc)


@shared_task
def notify_admins_on_contact_request(contact_request_id: int) -> None:
    """Notify administrators about a new contact request via email-service.

    Ported from ``actors.py::notify_admins_on_contact_request``. Makes an
    HTTP call to the (still FastAPI, not yet ported) email-service to
    dispatch the notification. Fails silently (logs error) if email-service
    is unavailable — matches the original's fire-and-forget contract.

    Wired from ``apps.cms.views._create_contact_request`` (Task 1.4
    deliberately deferred this side effect to this task landing).

    ``settings.EMAIL_SERVICE_URL`` is blank in tests
    (``htqweb/settings/test.py``) so this no-ops there instead of making a
    real HTTP call — same style of settings-gated no-op as
    ``translate_news`` above. Production keeps the FastAPI original's
    default (``http://email-service:8011``) and always calls out.
    """
    require_service("cms")

    if not settings.EMAIL_SERVICE_URL:
        logger.info(
            "notify_admins_on_contact_request no-op: EMAIL_SERVICE_URL not "
            "set (id=%d)",
            contact_request_id,
        )
        return

    logger.info("notify_admins_on_contact_request: id=%d", contact_request_id)

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{settings.EMAIL_SERVICE_URL}/api/email/v1/internal/notify",
                json={
                    "event": "contact_request_submitted",
                    "contact_request_id": contact_request_id,
                },
            )
            if resp.status_code < 300:
                logger.info(
                    "notify_admins_on_contact_request: email-service accepted id=%d",
                    contact_request_id,
                )
            else:
                logger.warning(
                    "notify_admins_on_contact_request: email-service returned %d for id=%d",
                    resp.status_code,
                    contact_request_id,
                )
    except httpx.HTTPError as exc:
        logger.error(
            "notify_admins_on_contact_request: email-service unreachable for id=%d: %s",
            contact_request_id,
            exc,
        )


@shared_task
def publish_scheduled_news() -> int:
    """Auto-publish ``News`` rows whose scheduled go-live time has passed.

    Ported from ``scheduler.py::news_scheduled_publish`` — an APScheduler
    cron job (``CronTrigger(minute="*")``, i.e. every minute) run by the
    standalone ``cms-scheduler`` container (and also started inside the main
    app's lifespan — both run the same job). Not currently scheduled: the
    django-q2 periodic ``Schedule`` row this task used to have (migration
    ``0002_schedule_publish_scheduled_news``, deleted with the Celery
    rework) will be re-registered via django-celery-beat in a separate task.
    Not invoked from any HTTP call site in the meantime.

    Query kept BYTE-IDENTICAL to the FastAPI original (``published=False AND
    published_at IS NOT NULL AND published_at <= now()``).

    NOTE (verbatim-port caveat, not a bugfix): against the *current* schema
    (migration ``004_news_taxonomy`` added ``status``/``scheduled_at``) this
    filter can never match. Every code path that sets
    ``status=NewsStatus.SCHEDULED`` (``_apply_status_side_effects`` in
    ``services/cms/app/api/v1/news.py``) always nulls ``published_at`` for
    scheduled rows, so ``published_at IS NOT NULL`` excludes exactly the rows
    this job exists to publish. The FastAPI service's actual auto-publish
    path is lazy, done at *read* time instead
    (``_public_visibility_clause``: ``status=SCHEDULED AND scheduled_at <=
    now()`` is included in "visible" results without ever flipping the row's
    status/``published``). This job is ported as-is because Task 1.7's scope
    is a verbatim port of ``scheduler.py``, not a fix to news-scheduling
    semantics — whichever task ports News CRUD next should decide whether to
    keep, repoint (at ``scheduled_at``/``status``), or drop this schedule.
    """
    require_service("cms")

    updated = News.objects.filter(
        published=False,
        published_at__isnull=False,
        published_at__lte=timezone.now(),
    ).update(published=True)

    if updated:
        logger.info("publish_scheduled_news: published %d articles", updated)
    return updated
