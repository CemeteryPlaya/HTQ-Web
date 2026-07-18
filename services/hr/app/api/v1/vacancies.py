"""Vacancies API router."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.auth.dependencies import get_current_user, TokenPayload
from app.schemas.vacancy import VacancyCreate, VacancyUpdate, VacancyOut
from app.schemas.application import ApplicationOut
from app.schemas.common import PaginatedResponse
from app.services.recruitment_service import RecruitmentService

router = APIRouter(prefix="/vacancies", tags=["vacancies"])


def _svc(db: AsyncSession = Depends(get_db_session)) -> RecruitmentService:
    return RecruitmentService(db)


@router.get("/", response_model=PaginatedResponse[VacancyOut])
async def list_vacancies(
    status: str | None = Query(default=None),
    department_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    items, total = await svc.list_vacancies(
        status=status, department_id=department_id, page=page, limit=limit
    )
    pages = (total + limit - 1) // limit
    return PaginatedResponse(items=items, total=total, page=page, pages=pages, limit=limit)


@router.post("/", response_model=VacancyOut, status_code=status.HTTP_201_CREATED)
async def create_vacancy(
    body: VacancyCreate,
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.create_vacancy(body)


@router.get("/{id}/", response_model=VacancyOut)
async def get_vacancy(
    id: int,
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.get_vacancy(id)


@router.put("/{id}/", response_model=VacancyOut)
async def update_vacancy(
    id: int,
    body: VacancyUpdate,
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.update_vacancy(id, body)


@router.delete("/{id}/", status_code=status.HTTP_204_NO_CONTENT)
async def close_vacancy(
    id: int,
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    await svc.close_vacancy(id)


@router.get("/{id}/applications", response_model=list[ApplicationOut])
async def vacancy_applications(
    id: int,
    svc: RecruitmentService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.get_vacancy_applications(id)
