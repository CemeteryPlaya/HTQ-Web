"""Reference data sources (Lark-Base-style lookup tables).

Management (create/update/delete + rows) is admin-only; `options` is readable
by any authenticated user so form `reference` widgets can populate their
dropdowns (with optional parent-field filtering for dependent selects)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.reference_source import RequestReferenceRow, RequestReferenceSource
from app.schemas.reference import (
    AccessUpdate, DataTableResponse, ReferenceRowCreate, ReferenceRowResponse,
    ReferenceSourceCreate, ReferenceSourceResponse, ReferenceSourceUpdate,
)
from app.services.template_data_table import can_manage_data_table, can_view_data_table
from app.util.slug import slugify

router = APIRouter(prefix="/reference-sources", tags=["reference"])


def _require_admin(user: TokenPayload) -> None:
    if not getattr(user, "is_elevated", False):
        raise HTTPException(status_code=403, detail="reference sources are managed by administrators")


async def _get_or_404(db: AsyncSession, source_id: int) -> RequestReferenceSource:
    src = await db.get(RequestReferenceSource, source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Reference source not found")
    return src


@router.get("/", response_model=list[ReferenceSourceResponse])
async def list_sources(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    stmt = select(RequestReferenceSource).order_by(RequestReferenceSource.name)
    return list((await db.execute(stmt)).scalars().all())


@router.post("/", response_model=ReferenceSourceResponse, status_code=201)
async def create_source(
    data: ReferenceSourceCreate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    _require_admin(user)
    slug = data.slug or slugify(data.name)
    exists = (await db.execute(select(RequestReferenceSource).where(RequestReferenceSource.slug == slug))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail=f"slug '{slug}' already exists")
    src = RequestReferenceSource(slug=slug, name=data.name, columns_json=data.columns, created_by=user.user_id)
    db.add(src)
    await db.flush()
    await db.refresh(src)
    return src


def _elevated(user: TokenPayload) -> bool:
    return bool(getattr(user, "is_elevated", False))


async def _data_table_dto(db: AsyncSession, src: RequestReferenceSource, user: TokenPayload) -> DataTableResponse:
    return DataTableResponse(
        id=src.id, slug=src.slug, name=src.name, columns=list(src.columns),
        template_id=src.template_id,
        access_ids=[int(x) for x in (src.access_ids or [])],
        can_manage=await can_manage_data_table(db, src, user.user_id, _elevated(user)),
    )


@router.get("/my-data-tables", response_model=list[DataTableResponse])
async def my_data_tables(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    """Template data tables the current user may see: created by them, they're a
    process admin, they were granted access, or they're a platform admin."""
    stmt = (
        select(RequestReferenceSource)
        .where(RequestReferenceSource.template_id.is_not(None))
        .order_by(RequestReferenceSource.name)
    )
    out = []
    for s in (await db.execute(stmt)).scalars().all():
        if await can_view_data_table(db, s, user.user_id, _elevated(user)):
            out.append(await _data_table_dto(db, s, user))
    return out


@router.patch("/{source_id}/access", response_model=DataTableResponse)
async def set_data_table_access(
    source_id: int,
    data: AccessUpdate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    src = await _get_or_404(db, source_id)
    if src.template_id is None:
        raise HTTPException(status_code=400, detail="not a template data table")
    if not await can_manage_data_table(db, src, user.user_id, _elevated(user)):
        raise HTTPException(status_code=403, detail="only the table owner can manage access")
    src.access_ids = [int(x) for x in data.viewer_ids]
    await db.flush()
    await db.refresh(src)
    return await _data_table_dto(db, src, user)


@router.get("/{source_id}/", response_model=ReferenceSourceResponse)
async def get_source(
    source_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    return await _get_or_404(db, source_id)


@router.patch("/{source_id}/", response_model=ReferenceSourceResponse)
async def update_source(
    source_id: int,
    data: ReferenceSourceUpdate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    _require_admin(user)
    src = await _get_or_404(db, source_id)
    if data.name is not None:
        src.name = data.name
    if data.columns is not None:
        src.columns_json = data.columns
    await db.flush()
    await db.refresh(src)
    return src


@router.delete("/{source_id}/", status_code=204)
async def delete_source(
    source_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    _require_admin(user)
    src = await _get_or_404(db, source_id)
    await db.delete(src)


@router.get("/{source_id}/rows/", response_model=list[ReferenceRowResponse])
async def list_rows(
    source_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    src = await _get_or_404(db, source_id)
    if src.template_id is not None and not await can_view_data_table(db, src, user.user_id, _elevated(user)):
        raise HTTPException(status_code=403, detail="no access to this data table")
    stmt = select(RequestReferenceRow).where(RequestReferenceRow.source_id == source_id).order_by(RequestReferenceRow.id)
    return list((await db.execute(stmt)).scalars().all())


@router.post("/{source_id}/rows/", response_model=ReferenceRowResponse, status_code=201)
async def add_row(
    source_id: int,
    data: ReferenceRowCreate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    _require_admin(user)
    await _get_or_404(db, source_id)
    row = RequestReferenceRow(source_id=source_id, data_json=data.data)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


@router.delete("/{source_id}/rows/{row_id}/", status_code=204)
async def delete_row(
    source_id: int,
    row_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    _require_admin(user)
    row = await db.get(RequestReferenceRow, row_id)
    if not row or row.source_id != source_id:
        raise HTTPException(status_code=404, detail="Row not found")
    await db.delete(row)


@router.get("/by-slug/{slug}/options")
async def options(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
    column: Annotated[str, Query(...)],
    filter_col: Annotated[str | None, Query()] = None,
    filter_val: Annotated[str | None, Query()] = None,
):
    """Distinct values of `column` from the named source, optionally filtered
    where `filter_col` == `filter_val` (drives dependent selects)."""
    src = (await db.execute(select(RequestReferenceSource).where(RequestReferenceSource.slug == slug))).scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=404, detail="Reference source not found")
    rows = (await db.execute(select(RequestReferenceRow).where(RequestReferenceRow.source_id == src.id))).scalars().all()
    seen: list[str] = []
    for r in rows:
        d = r.data_json or {}
        if filter_col and str(d.get(filter_col, "")) != str(filter_val):
            continue
        val = d.get(column)
        if val is None:
            continue
        s = str(val)
        if s not in seen:
            seen.append(s)
    return {"slug": slug, "column": column, "options": seen}
