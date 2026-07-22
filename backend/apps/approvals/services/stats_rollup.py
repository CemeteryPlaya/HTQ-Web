"""Daily rollup of request outcomes into ``RequestStatsDaily``.

Ported from ``services/requests/app/services/stats_rollup.py``. The original
avoided ``INSERT … ON CONFLICT`` so the same code ran against its SQLite test
backend; here the suite runs on Postgres (PLAN.md §3), so
``get_or_create`` + an explicit update is both simpler and equivalent.

``_PROJECT_NONE = 0`` is kept: the rollup key cannot hold NULL, so
"no project" is bucket 0. That sentinel is part of the stored data and the
stats endpoints read it back, so it must not be "modernised" into NULL.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..models import RequestInstance, RequestStatsDaily, RequestStatus
from .template_settings import settings_for_template

_PROJECT_NONE = 0


def _row_for(day: dt.date, project_id: int, template_id: int) -> RequestStatsDaily:
    row, _ = RequestStatsDaily.objects.get_or_create(
        date=day, project_id=project_id, template_id=template_id,
        defaults={"created": 0, "approved": 0, "rejected": 0, "cancelled": 0,
                  "sum_approved_amount": Decimal(0),
                  "time_to_decision_seconds_sum": 0},
    )
    return row


@transaction.atomic
def upsert_finalization(instance: RequestInstance) -> None:
    """Bump the counters for a request that has just reached a final state.

    Idempotent only at the caller's discretion — it adds one to a counter, so
    the runtime must call it exactly once per finalization (it does).
    """
    if instance.finalized_at is None:
        return
    day = timezone.localdate(instance.finalized_at)
    project_id = instance.project_id if instance.project_id is not None \
        else _PROJECT_NONE
    row = _row_for(day, project_id, instance.template_id)

    status = instance.status
    if status == RequestStatus.APPROVED:
        row.approved += 1
        if instance.total_amount is not None:
            row.sum_approved_amount = ((row.sum_approved_amount or Decimal(0))
                                       + Decimal(instance.total_amount))
    elif status == RequestStatus.REJECTED:
        row.rejected += 1
    elif status == RequestStatus.CANCELLED:
        row.cancelled += 1
    else:
        return   # 'returned' is not final — no counter moves

    exclude = settings_for_template(instance.template_id)["exclude_efficiency"]
    if instance.submitted_at is not None and not exclude:
        delta = (instance.finalized_at - instance.submitted_at).total_seconds()
        if delta > 0:
            row.time_to_decision_seconds_sum += int(delta)
    row.save()


@transaction.atomic
def recompute_window(days: int = 7) -> int:
    """Recompute the last ``days`` days from the instances themselves.

    The nightly reconciliation: counters are incremental, so a crash between
    the finalization and its rollup leaves drift. This wipes the affected
    buckets and re-aggregates them from scratch. Returns the number of
    ``(date, project, template)`` buckets touched.
    """
    start = timezone.now() - dt.timedelta(days=days - 1)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    instances = list(RequestInstance.objects.filter(
        finalized_at__isnull=False, finalized_at__gte=start))

    keys = {
        (timezone.localdate(inst.finalized_at),
         inst.project_id if inst.project_id is not None else _PROJECT_NONE,
         inst.template_id)
        for inst in instances
    }
    for day, project_id, template_id in keys:
        row = _row_for(day, project_id, template_id)
        row.created = 0
        row.approved = 0
        row.rejected = 0
        row.cancelled = 0
        row.sum_approved_amount = Decimal(0)
        row.time_to_decision_seconds_sum = 0
        row.save()

    for inst in instances:
        upsert_finalization(inst)
    return len(keys)
