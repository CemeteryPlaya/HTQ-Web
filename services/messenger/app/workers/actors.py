import dramatiq
from app.workers import broker  # noqa: F401
from app.core.logging import get_logger
from app.core.settings import settings

log = get_logger(__name__)


@dramatiq.actor(max_retries=3, min_backoff=1000)
def dispatch_push_notification(user_id: int, payload: dict) -> None:
    """Send FCM/APNS push. Noop if FCM keys empty (env-placeholder)."""
    if not settings.fcm_api_key and not settings.apns_cert_path:
        log.info("push_skipped_no_keys", user_id=user_id)
        return
    # TODO: real FCM/APNS call
    log.info("push_dispatched", user_id=user_id)
