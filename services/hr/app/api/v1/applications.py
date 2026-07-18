"""Applications (отклики кандидатов) API router.

Route ordering: literal `/archive/` is declared before `/{id}/` so FastAPI
doesn't try to parse `archive` as int and 422.
"""

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.auth.dependencies import get_current_user, TokenPayload
from app.models.application import Application
from app.models.document import Document
from app.schemas.application import ApplicationCreate, ApplicationUpdate, ApplicationOut, ApplicationStatusChange
from app.schemas.common import PaginatedResponse
from app.services.recruitment_service import RecruitmentService

router = APIRouter(prefix="/applications", tags=["applications"])


def _svc(db: AsyncSession = Depends(get_db_session)) -> RecruitmentService:
    return RecruitmentService(db)


# ── List + create ─────────────────────────────────────────────────────

@router.get("/", response_model=PaginatedResponse[ApplicationOut])
async def list_applications(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    items, total = await svc.list_applications(page=page, limit=limit)
    pages = (total + limit - 1) // limit
    return PaginatedResponse(items=items, total=total, page=page, pages=pages, limit=limit)


@router.post("/", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
async def create_application(
    body: ApplicationCreate,
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.create_application(body)


# ── Archive (BEFORE /{id}/ so `archive` isn't parsed as int) ──────────

class HRArchiveResponse(BaseModel):
    """Read-only roll-up powering /hr/archive page."""
    applications: list[dict]
    documents: list[dict]


@router.get("/archive/", response_model=HRArchiveResponse)
async def archive(
    db: AsyncSession = Depends(get_db_session),
    _: TokenPayload = Depends(get_current_user),
):
    """Closed/archived applications + documents.

    Minimal read-only shape — returns terminal-status applications and all
    documents. Sorting/filtering happens client-side in HRArchive.tsx.
    """
    closed_statuses = {"rejected", "hired", "withdrawn", "archived"}
    apps_result = await db.execute(
        select(Application).where(Application.status.in_(closed_statuses)).order_by(Application.created_at.desc())
    )
    docs_result = await db.execute(select(Document).order_by(Document.created_at.desc()).limit(200))
    return HRArchiveResponse(
        applications=[
            {
                "id": a.id,
                "vacancy_id": getattr(a, "vacancy_id", None),
                "candidate_name": getattr(a, "candidate_name", None),
                "candidate_email": getattr(a, "candidate_email", None),
                "status": a.status,
                "created_at": a.created_at.isoformat() if getattr(a, "created_at", None) else None,
            }
            for a in apps_result.scalars().all()
        ],
        documents=[
            {
                "id": d.id,
                "title": getattr(d, "title", None),
                "doc_type": getattr(d, "doc_type", None),
                "employee_id": getattr(d, "employee_id", None),
                "created_at": d.created_at.isoformat() if getattr(d, "created_at", None) else None,
            }
            for d in docs_result.scalars().all()
        ],
    )


@router.get("/{id}/", response_model=ApplicationOut)
async def get_application(
    id: int,
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.get_application(id)


@router.put("/{id}/", response_model=ApplicationOut)
async def update_application(
    id: int,
    body: ApplicationUpdate,
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.update_application(id, body)


@router.delete("/{id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    id: int,
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    await svc.delete_application(id)


@router.post("/{id}/status", response_model=ApplicationOut)
async def change_application_status(
    id: int,
    body: ApplicationStatusChange,
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.change_status(id, body)
