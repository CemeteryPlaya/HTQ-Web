"""Vacancy repository."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vacancy import Vacancy
from app.models.application import Application
from app.repositories.base_repo import BaseRepository


class VacancyRepository(BaseRepository[Vacancy]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Vacancy, session)

    async def list_vacancies(
        self,
        *,
        status: str | None = None,
        department_id: int | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Vacancy], int]:
        stmt = select(Vacancy)
        if status:
            stmt = stmt.where(Vacancy.status == status)
        if department_id:
            stmt = stmt.where(Vacancy.department_id == department_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Vacancy.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_applications(self, vacancy_id: int) -> list[Application]:
        stmt = select(Application).where(Application.vacancy_id == vacancy_id).order_by(Application.applied_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
