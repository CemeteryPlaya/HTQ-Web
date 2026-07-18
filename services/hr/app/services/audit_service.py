"""Audit service — write audit log entries."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        *,
        entity_type: str,
        entity_id: int,
        action: str,
        changed_by: int,
        old_values: dict | None = None,
        new_values: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            changed_by=changed_by,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry
