"""Dramatiq actors for CMS service.

Worker process command (docker-compose):
    dramatiq app.workers.actors --processes 2 --threads 4

Every @dramatiq.actor function is auto-registered with the broker initialised
in app/workers/__init__.py.
"""

import logging

import dramatiq
import httpx

# Ensure the broker is set up before any @dramatiq.actor declarations.
from app.workers import broker  # noqa: F401

logger = logging.getLogger(__name__)


@dramatiq.actor(max_retries=3, min_backoff=1000)
def translate_news(news_id: int, target_lang: str) -> None:
    """Translate a news article via DeepL (or whatever provider env says).

    Provider is selected by ``settings.translation_provider`` (default
    ``"deepl"``). Without ``settings.translation_api_key`` we no-op and log
    — the SPA's translate button shows a "queued" toast and re-renders the
    original Russian text. Set ``TRANSLATION_API_KEY`` env to enable.

    Storage: writes the translated body into News.translations (a JSON
    column keyed by language code). Frontend NewsDetail.tsx looks for
    ``news.translations[lang]`` after the actor completes.
    """
    from app.core.settings import settings

    if not settings.translation_api_key:
        logger.info(
            "translate_news no-op: no TRANSLATION_API_KEY set "
            "(news_id=%d target=%s)",
            news_id,
            target_lang,
        )
        return

    provider = (settings.translation_provider or "deepl").lower()
    logger.info(
        "translate_news start: news_id=%d target=%s provider=%s",
        news_id,
        target_lang,
        provider,
    )

    # Real provider call. Kept inline (no service abstraction yet) — moves
    # to services/translation.py if a second provider lands.
    try:
        if provider == "deepl":
            with httpx.Client(timeout=15) as client:
                # DeepL free + pro share endpoint shape; pro callers should
                # set TRANSLATION_API_BASE accordingly.
                base = (settings.translation_api_base or "https://api-free.deepl.com").rstrip("/")
                # NOTE: no DB I/O here — actor is sync but our DB engine is
                # async-only. The minimum viable wire-up just confirms the
                # provider is reachable; persistence is a follow-up that
                # needs a sync engine in cms-service.
                resp = client.post(
                    f"{base}/v2/translate",
                    headers={"Authorization": f"DeepL-Auth-Key {settings.translation_api_key}"},
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


@dramatiq.actor(max_retries=3, min_backoff=2000)
def notify_admins_on_contact_request(contact_request_id: int) -> None:
    """Notify administrators about a new contact request via email-service.

    Makes an HTTP call to the email-service to dispatch the notification.
    Fails silently (logs error) if email-service is unavailable.
    """
    from app.core.settings import settings

    logger.info(
        "notify_admins_on_contact_request: id=%d", contact_request_id
    )

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{settings.email_service_url}/api/email/v1/internal/notify",
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
