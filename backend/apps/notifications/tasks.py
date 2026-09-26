from celery import shared_task

from apps.core.services import require_service


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def deliver(self, delivery_id: int) -> None:
    require_service("notifications")
    from apps.notifications.services import delivery

    try:
        delivery.deliver(delivery_id)
    except delivery.RetryLater as exc:
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
