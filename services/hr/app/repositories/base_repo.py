"""Generic base repository for SQLAlchemy async sessions."""

from typing import Any, Generic, Sequence, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class BaseRepository(Generic[ModelT]):
    """CRUD + pagination helpers for any SQLAlchemy model."""

    def __init__(self, model: Type[ModelT], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get(self, id: int) -> ModelT | None:
        return await self.session.get(self.model, id)

    async def list(
        self,
        *,
        filters: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int = 20,
        order_by: str = "id",
        order: str = "asc",
    ) -> tuple[Sequence[ModelT], int]:
        stmt = select(self.model)

        if filters:
            for field, value in filters.items():
                if value is not None and hasattr(self.model, field):
                    stmt = stmt.where(getattr(self.model, field) == value)

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Order
        col = getattr(self.model, order_by, self.model.id)
        if order.lower() == "desc":
            stmt = stmt.order_by(col.desc())
        else:
            stmt = stmt.order_by(col.asc())

        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def create(self, data: dict[str, Any]) -> ModelT:
        instance = self.model(**data)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, instance: ModelT, data: dict[str, Any]) -> ModelT:
        for key, value in data.items():
            if value is not None and hasattr(instance, key):
                setattr(instance, key, value)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)
        await self.session.flush()
