from celery import shared_task
from django.utils import timezone

from apps.core.services import require_service


@shared_task
def load_nbrk_rates() -> int:
    require_service("refdata")
    from apps.refdata.services import nbrk

    return nbrk.load(timezone.localdate())
