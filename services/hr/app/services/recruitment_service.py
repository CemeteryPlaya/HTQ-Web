"""Recruitment service — vacancies and applications."""

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vacancy import Vacancy
from app.models.application import Application
from app.repositories.vacancy_repo import VacancyRepository
from app.repositories.base_repo import BaseRepository
from app.schemas.vacancy import VacancyCreate, VacancyUpdate
from app.schemas.application import ApplicationCreate, ApplicationUpdate, ApplicationStatusChange

logger = structlog.get_logger()


class RecruitmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.vacancy_repo = VacancyRepository(session)
        self.app_repo = BaseRepository(Application, session)

    # ── Vacancies ──────────────────────────────────────────────────────────

    async def list_vacancies(
        self,
        *,
        status: str | None = None,
        department_id: int | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Vacancy], int]:
        offset = (page - 1) * limit
        return await self.vacancy_repo.list_vacancies(
            status=status,
            department_id=department_id,
            offset=offset,
            limit=limit,
        )

    async def get_vacancy(self, id: int) -> Vacancy:
        vacancy = await self.vacancy_repo.get(id)
        if not vacancy:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vacancy not found")
        return vacancy

    async def create_vacancy(self, data: VacancyCreate) -> Vacancy:
        vacancy = await self.vacancy_repo.create(data.model_dump())
        logger.info("vacancy_created", vacancy_id=vacancy.id)
        return vacancy

    async def update_vacancy(self, id: int, data: VacancyUpdate) -> Vacancy:
        vacancy = await self.get_vacancy(id)
        updated = await self.vacancy_repo.update(vacancy, data.model_dump(exclude_none=True))
        logger.info("vacancy_updated", vacancy_id=id)
        return updated

    async def close_vacancy(self, id: int) -> None:
        from datetime import date
        vacancy = await self.get_vacancy(id)
        await self.vacancy_repo.update(vacancy, {"status": "closed", "closed_at": date.today()})
        logger.info("vacancy_closed", vacancy_id=id)

    async def get_vacancy_applications(self, vacancy_id: int) -> list[Application]:
        await self.get_vacancy(vacancy_id)
        return await self.vacancy_repo.get_applications(vacancy_id)

    # ── Applications ───────────────────────────────────────────────────────

    async def list_applications(self, *, page: int = 1, limit: int = 20) -> tuple[list[Application], int]:
        offset = (page - 1) * limit
        items, total = await self.app_repo.list(offset=offset, limit=limit, order_by="applied_at", order="desc")
        return list(items), total

    async def get_application(self, id: int) -> Application:
        app = await self.app_repo.get(id)
        if not app:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
        return app

    async def create_application(self, data: ApplicationCreate) -> Application:
        await self.get_vacancy(data.vacancy_id)
        app = await self.app_repo.create(data.model_dump())
        logger.info("application_created", application_id=app.id, vacancy_id=data.vacancy_id)
        return app

    async def update_application(self, id: int, data: ApplicationUpdate) -> Application:
        app = await self.get_application(id)
        updated = await self.app_repo.update(app, data.model_dump(exclude_none=True))
        logger.info("application_updated", application_id=id)
        return updated

    async def change_status(self, id: int, data: ApplicationStatusChange) -> Application:
        app = await self.get_application(id)
        patch: dict = {"status": data.status}
        if data.notes:
            patch["notes"] = data.notes
        updated = await self.app_repo.update(app, patch)
        logger.info("application_status_changed", application_id=id, new_status=data.status)
        return updated

    async def delete_application(self, id: int) -> None:
        app = await self.get_application(id)
        await self.app_repo.delete(app)
        logger.info("application_deleted", application_id=id)
