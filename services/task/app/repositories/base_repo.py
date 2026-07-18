"""Repository base class for database operations."""

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class BaseRepository(Generic[ModelT]):
    """Generic repository with common CRUD operations."""

    def __init__(self, model: type[ModelT], session: AsyncSession):
        self.model = model
        self.session = session

    async def get_by_id(self, id: int) -> ModelT | None:
        """Get entity by ID."""
        return await self.session.get(self.model, id)

    async def get_all(
        self, offset: int = 0, limit: int = 100, **filters
    ) -> list[ModelT]:
        """Get all entities with optional filters."""
        query = select(self.model)
        for field, value in filters.items():
            if hasattr(self.model, field):
                query = query.where(getattr(self.model, field) == value)
        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count(self, **filters) -> int:
        """Count entities with optional filters."""
        from sqlalchemy import func

        query = select(func.count(self.model.id))
        for field, value in filters.items():
            if hasattr(self.model, field):
                query = query.where(getattr(self.model, field) == value)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def create(self, **kwargs) -> ModelT:
        """Create new entity."""
        entity = self.model(**kwargs)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: ModelT, **kwargs) -> ModelT:
        """Update entity."""
        for field, value in kwargs.items():
            if hasattr(entity, field):
                setattr(entity, field, value)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        """Delete entity."""
        await self.session.delete(entity)
        await self.session.flush()
