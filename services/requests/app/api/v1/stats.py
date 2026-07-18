"""Statistics endpoints — see spec §6 for the five reporting cuts."""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.approval_action import ApprovalAction
from app.models.project import RequestProject
from app.models.request_instance import RequestInstance, RequestStatus
from app.models.stats_daily import RequestStatsDaily

router = APIRouter(prefix="/stats", tags=["stats"])

_PROJECT_NONE = 0  # sentinel mirrored from stats_rollup


def _default_from(days: int) -> date:
    return (datetime.now(timezone.utc).date() - timedelta(days=days))


def _iso_status_filter():
    """Helpers for FILTER (WHERE status=...) compatible across PG/SQLite."""
    return RequestInstance.status


# ─── overview ────────────────────────────────────────────────────────────


@router.get("/overview")
async def overview(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
):
    frm = from_ or _default_from(30)
    end = to or datetime.now(timezone.utc).date()
    stmt = (
        select(
            RequestInstance.status,
            func.count(RequestInstance.id),
            func.coalesce(func.sum(RequestInstance.total_amount), 0),
        )
        .where(RequestInstance.submitted_at.is_not(None))
        .group_by(RequestInstance.status)
    )
    rows = (await db.execute(stmt)).all()
    by_status: dict[str, dict] = {s: {"count": 0, "sum_amount": 0} for s in
        ("draft", "pending", "approved", "rejected", "cancelled", "returned")}
    for status, count, total in rows:
        by_status[status] = {"count": int(count), "sum_amount": float(total or 0)}
    return {
        "from": frm.isoformat(),
        "to": end.isoformat(),
        "by_status": by_status,
    }


# ─── by project ──────────────────────────────────────────────────────────


@router.get("/by-project")
async def by_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    project = await db.get(RequestProject, project_id)
    if project is None:
        return {"project": None}
    # SUM with CASE WHEN — portable across PG and SQLite.
    stmt = select(
        func.coalesce(func.sum(
            case((RequestInstance.status == RequestStatus.APPROVED.value, RequestInstance.total_amount), else_=0)
        ), 0).label("sum_approved"),
        func.coalesce(func.sum(
            case((RequestInstance.status == RequestStatus.PENDING.value, RequestInstance.total_amount), else_=0)
        ), 0).label("sum_pending"),
        func.coalesce(func.sum(
            case((RequestInstance.status == RequestStatus.APPROVED.value, 1), else_=0)
        ), 0).label("count_approved"),
        func.coalesce(func.sum(
            case((RequestInstance.status == RequestStatus.PENDING.value, 1), else_=0)
        ), 0).label("count_pending"),
    ).where(RequestInstance.project_id == project_id)
    row = (await db.execute(stmt)).one()
    sum_approved = float(row.sum_approved or 0)
    budget = float(project.budget_limit) if project.budget_limit is not None else None
    return {
        "project": {
            "id": project.id, "name": project.name,
            "budget_limit": budget, "currency": project.currency,
        },
        "sum_approved": sum_approved,
        "sum_pending": float(row.sum_pending or 0),
        "count_approved": int(row.count_approved or 0),
        "count_pending": int(row.count_pending or 0),
        "remaining": (budget - sum_approved) if budget is not None else None,
        "percent_used": (sum_approved / budget * 100) if budget and budget > 0 else None,
    }


# ─── by template ─────────────────────────────────────────────────────────


@router.get("/by-template")
async def by_template(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
    project_id: int | None = None,
):
    frm = from_ or _default_from(30)
    end = to or datetime.now(timezone.utc).date()
    cond = [RequestInstance.submitted_at.is_not(None)]
    if project_id is not None:
        cond.append(RequestInstance.project_id == project_id)
    stmt = (
        select(
            RequestInstance.template_id,
            func.count(RequestInstance.id).label("count"),
            func.coalesce(func.sum(case((RequestInstance.status == "approved", 1), else_=0)), 0).label("approved"),
            func.coalesce(func.sum(case((RequestInstance.status == "rejected", 1), else_=0)), 0).label("rejected"),
            func.coalesce(func.avg(
                case((RequestInstance.status == "approved", RequestInstance.total_amount), else_=None)
            ), 0).label("avg_amount"),
        )
        .where(*cond)
        .group_by(RequestInstance.template_id)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "template_id": int(r.template_id),
            "count": int(r.count),
            "approved": int(r.approved),
            "rejected": int(r.rejected),
            "avg_amount": float(r.avg_amount or 0),
            "approval_rate": (float(r.approved) / float(r.count) if r.count else 0.0),
        }
        for r in rows
    ]


# ─── by actor ────────────────────────────────────────────────────────────


@router.get("/by-actor")
async def by_actor(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
    role: Annotated[Literal["initiator", "approver"], Query()] = "initiator",
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
    limit: int = 20,
):
    frm = from_ or _default_from(30)
    end = to or datetime.now(timezone.utc).date()
    if role == "initiator":
        stmt = (
            select(
                RequestInstance.initiator_id.label("user_id"),
                func.count(RequestInstance.id).label("count"),
                func.coalesce(func.sum(case((RequestInstance.status == "approved", 1), else_=0)), 0).label("approved"),
            )
            .where(RequestInstance.submitted_at.is_not(None))
            .group_by(RequestInstance.initiator_id)
            .order_by(func.count(RequestInstance.id).desc())
            .limit(limit)
        )
    else:
        stmt = (
            select(
                ApprovalAction.approver_id.label("user_id"),
                func.count(ApprovalAction.id).label("count"),
                func.coalesce(func.sum(case((ApprovalAction.action == "approve", 1), else_=0)), 0).label("approved"),
            )
            .where(ApprovalAction.acted_at.is_not(None))
            .group_by(ApprovalAction.approver_id)
            .order_by(func.count(ApprovalAction.id).desc())
            .limit(limit)
        )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "user_id": int(r.user_id),
            "count": int(r.count),
            "approved": int(r.approved),
            "approval_rate": (float(r.approved) / float(r.count) if r.count else 0.0),
        }
        for r in rows
    ]


# ─── heatmap ─────────────────────────────────────────────────────────────


@router.get("/heatmap")
async def heatmap(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
):
    frm = from_ or _default_from(30)
    end = to or datetime.now(timezone.utc).date()
    stmt = (
        select(
            RequestStatsDaily.date,
            func.sum(RequestStatsDaily.created).label("created"),
            func.sum(RequestStatsDaily.approved).label("approved"),
            func.sum(RequestStatsDaily.rejected).label("rejected"),
            func.sum(RequestStatsDaily.cancelled).label("cancelled"),
        )
        .where(RequestStatsDaily.date.between(frm, end))
        .group_by(RequestStatsDaily.date)
        .order_by(RequestStatsDaily.date)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "date": r.date.isoformat(),
            "created": int(r.created or 0),
            "approved": int(r.approved or 0),
            "rejected": int(r.rejected or 0),
            "cancelled": int(r.cancelled or 0),
        }
        for r in rows
    ]
