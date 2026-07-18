"""Cross-DB UPSERT helpers for ``request_stats_daily``.

We avoid the dialect-specific ``INSERT … ON CONFLICT DO UPDATE`` so the same
code path works against both PG and the SQLite-backed test suite. The
SELECT-then-INSERT/UPDATE pattern is race-tolerant under typical dev/load
concurrency; the nightly reconciliation actor catches any missed deltas."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.request_instance import RequestInstance, RequestStatus
from app.models.stats_daily import RequestStatsDaily

_PROJECT_NONE = 0  # sentinel — composite PK can't store NULL on PG


async def upsert_finalization(session: AsyncSession, inst: RequestInstance) -> None:
    """Bump the per-day counters for the request's final outcome.

    Idempotent at the (date, project, template, status) granularity — callers
    must only invoke this once per finalization (the runtime does)."""
    if inst.finalized_at is None:
        return
    day = inst.finalized_at.date()
    pid = inst.project_id if inst.project_id is not None else _PROJECT_NONE
    tid = inst.template_id

    row = await session.get(RequestStatsDaily, (day, pid, tid))
    if row is None:
        row = RequestStatsDaily(
            date=day, project_id=pid, template_id=tid,
            created=0, approved=0, rejected=0, cancelled=0,
            sum_approved_amount=Decimal(0), time_to_decision_seconds_sum=0,
        )
        session.add(row)

    status = inst.status
    if status == RequestStatus.APPROVED.value:
        row.approved += 1
        if inst.total_amount is not None:
            row.sum_approved_amount = (row.sum_approved_amount or Decimal(0)) + Decimal(inst.total_amount)
    elif status == RequestStatus.REJECTED.value:
        row.rejected += 1
    elif status == RequestStatus.CANCELLED.value:
        row.cancelled += 1
    else:
        return  # `returned` is not a final state; no counter

    from app.services.template_settings import settings_for_template
    exclude = (await settings_for_template(session, inst.template_id))["exclude_efficiency"]
    if inst.submitted_at is not None and not exclude:
        # SQLite (test backend) strips tzinfo on roundtrip; normalize both
        # sides to naive UTC before subtraction.
        sub = inst.submitted_at if inst.submitted_at.tzinfo is None else inst.submitted_at.replace(tzinfo=None)
        fin = inst.finalized_at if inst.finalized_at.tzinfo is None else inst.finalized_at.replace(tzinfo=None)
        delta = (fin - sub).total_seconds()
        if delta > 0:
            row.time_to_decision_seconds_sum += int(delta)
    await session.flush()


async def recompute_window(session: AsyncSession, *, days: int = 7) -> int:
    """Recompute the last ``days`` days from ``request_instances``. Used by
    the nightly reconciliation actor to catch any drift. Returns the number of
    (date, project, template) rows touched."""
    from datetime import date as _date, timedelta as _timedelta
    today = datetime.now(timezone.utc).date()
    start = today - _timedelta(days=days - 1)

    # Pull all finalized instances in the window.
    stmt = (
        select(RequestInstance)
        .where(RequestInstance.finalized_at.is_not(None))
        .where(RequestInstance.finalized_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))
    )
    instances = list((await session.execute(stmt)).scalars().all())

    # Re-bucket fresh: wipe the affected slots first, then re-aggregate.
    touched_keys: set[tuple[_date, int, int]] = set()
    for inst in instances:
        day = inst.finalized_at.date()
        pid = inst.project_id if inst.project_id is not None else _PROJECT_NONE
        touched_keys.add((day, pid, inst.template_id))

    # Zero the touched rows (or create them).
    for (day, pid, tid) in touched_keys:
        row = await session.get(RequestStatsDaily, (day, pid, tid))
        if row is None:
            row = RequestStatsDaily(
                date=day, project_id=pid, template_id=tid,
                created=0, approved=0, rejected=0, cancelled=0,
                sum_approved_amount=Decimal(0), time_to_decision_seconds_sum=0,
            )
            session.add(row)
        else:
            row.created = 0
            row.approved = 0
            row.rejected = 0
            row.cancelled = 0
            row.sum_approved_amount = Decimal(0)
            row.time_to_decision_seconds_sum = 0
    await session.flush()

    # Re-aggregate.
    for inst in instances:
        await upsert_finalization(session, inst)
    return len(touched_keys)
