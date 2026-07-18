"""Generic async repository."""

from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class BaseRepository(Generic[ModelT]):
    def __init__(self, model: type[ModelT], session: AsyncSession):
        self.model = model
        self.session = session

    async def get_by_id(self, id: int) -> ModelT | None:
        return await self.session.get(self.model, id)

    async def get_all(self, offset: int = 0, limit: int = 100, **filters) -> list[ModelT]:
        query = select(self.model)
        for field, value in filters.items():
            if hasattr(self.model, field):
                query = query.where(getattr(self.model, field) == value)
        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count(self, **filters) -> int:
        query = select(func.count(self.model.id))
        for field, value in filters.items():
            if hasattr(self.model, field):
                query = query.where(getattr(self.model, field) == value)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def create(self, **kwargs) -> ModelT:
        entity = self.model(**kwargs)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: ModelT, **kwargs) -> ModelT:
        for field, value in kwargs.items():
            if hasattr(entity, field):
                setattr(entity, field, value)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()
