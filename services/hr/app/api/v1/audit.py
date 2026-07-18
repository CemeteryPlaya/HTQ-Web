"""Audit log API router."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.auth.dependencies import get_current_user, TokenPayload
from app.models.audit_log import AuditLog

# Mounted at `/logs` to match the frontend (`HRLogs.tsx`). The "audit" naming
# is kept internally — model + schema unchanged.
router = APIRouter(prefix="/logs", tags=["audit-logs"])


@router.get("/")
async def get_audit_log(
    entity_type: str | None = Query(default=None),
    entity_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
    _: TokenPayload = Depends(get_current_user),
):
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)

    offset = (page - 1) * limit
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "action": log.action,
            "old_values": log.old_values,
            "new_values": log.new_values,
            "changed_by": log.changed_by,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
