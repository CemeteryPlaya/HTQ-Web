"""S2S internal endpoints — accessed only by other internal services via shared secret.

Phase 4b: a single ``GET /supervisor?user_id=…`` endpoint used by requests-service
to resolve ``initiator_supervisor`` / ``department_head`` workflow assignees."""

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db_session
from app.models.employee import Employee
from app.services.employee_card_service import EmployeeCardService

router = APIRouter(tags=["internal"])


async def require_internal_token(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    # Shared secret across S2S endpoints. Accept either name during the
    # transition from messenger's MESSENGER_INTERNAL_TOKEN to the generic
    # INTERNAL_S2S_TOKEN — both are configured to the same value in compose.
    expected = os.environ.get("INTERNAL_S2S_TOKEN") or os.environ.get("MESSENGER_INTERNAL_TOKEN") or ""
    if not expected:
        raise HTTPException(status_code=503, detail="INTERNAL_S2S_TOKEN not configured")
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


@router.get("/supervisor", dependencies=[Depends(require_internal_token)])
async def get_supervisor(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Return the user_id of the head of ``user_id``'s department.

    If the employee heads their own department, climbs the ltree upward to the
    nearest parent department with a different manager. Returns
    ``{"supervisor_user_id": null}`` if no supervisor is found (no department,
    no upper-level manager)."""
    stmt = (
        select(Employee)
        .where(Employee.user_id == user_id, Employee.is_deleted == False)  # noqa: E712
        .options(selectinload(Employee.department))
    )
    emp = (await db.execute(stmt)).scalar_one_or_none()
    if emp is None:
        return {"supervisor_user_id": None}

    card = EmployeeCardService(db)
    manager = await card._resolve_manager(emp)
    return {"supervisor_user_id": manager.user_id if manager is not None else None}
