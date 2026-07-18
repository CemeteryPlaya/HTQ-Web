"""Taxonomy endpoints — ``/api/cms/v1/categories/*`` and ``.../tags/*``.

Two thin CRUD routers exposed under separate prefixes by ``main.py``. Read
endpoints are public (the public news feed needs the lists for filters);
mutating endpoints require admin.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, require_admin
from app.core.logging import get_logger
from app.db import get_db_session
from app.models.taxonomy import Category, Tag
from app.schemas.news import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    TagCreate,
    TagRead,
    TagUpdate,
)
from app.services.audit import record_action


log = get_logger(__name__)


# --- Categories ------------------------------------------------------------

categories_router = APIRouter(tags=["categories"])


@categories_router.get("/", response_model=list[CategoryRead])
async def list_categories(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[Category]:
    rows = await session.execute(select(Category).order_by(Category.name))
    return list(rows.scalars().all())


@categories_router.post("/", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> Category:
    cat = Category(**payload.model_dump())
    session.add(cat)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already exists")
    await record_action(
        session, user_id=admin.user_id, action="category_created",
        resource_type="Category", resource_id=str(cat.id),
        changes=payload.model_dump(mode="json"), request=request,
    )
    return cat


@categories_router.patch("/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> Category:
    cat = await session.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(cat, k, v)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug conflict")
    await record_action(
        session, user_id=admin.user_id, action="category_updated",
        resource_type="Category", resource_id=str(cat.id),
        changes=changes, request=request,
    )
    return cat


@categories_router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> None:
    cat = await session.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    await session.delete(cat)
    await record_action(
        session, user_id=admin.user_id, action="category_deleted",
        resource_type="Category", resource_id=str(category_id),
        changes={"slug": cat.slug}, request=request,
    )


# --- Tags ------------------------------------------------------------------

tags_router = APIRouter(tags=["tags"])


@tags_router.get("/", response_model=list[TagRead])
async def list_tags(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[Tag]:
    rows = await session.execute(select(Tag).order_by(Tag.name))
    return list(rows.scalars().all())


@tags_router.post("/", response_model=TagRead, status_code=status.HTTP_201_CREATED)
async def create_tag(
    payload: TagCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> Tag:
    tag = Tag(**payload.model_dump())
    session.add(tag)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already exists")
    await record_action(
        session, user_id=admin.user_id, action="tag_created",
        resource_type="Tag", resource_id=str(tag.id),
        changes=payload.model_dump(mode="json"), request=request,
    )
    return tag


@tags_router.patch("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int,
    payload: TagUpdate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> Tag:
    tag = await session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(tag, k, v)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug conflict")
    await record_action(
        session, user_id=admin.user_id, action="tag_updated",
        resource_type="Tag", resource_id=str(tag.id),
        changes=changes, request=request,
    )
    return tag


@tags_router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> None:
    tag = await session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    await session.delete(tag)
    await record_action(
        session, user_id=admin.user_id, action="tag_deleted",
        resource_type="Tag", resource_id=str(tag_id),
        changes={"slug": tag.slug}, request=request,
    )
