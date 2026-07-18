"""Documents API router."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.auth.dependencies import get_current_user, TokenPayload
from app.models.document import Document
from app.repositories.base_repo import BaseRepository
from app.schemas.document import DocumentCreate, DocumentOut
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/documents", tags=["documents"])


def _repo(db: AsyncSession = Depends(get_db_session)) -> BaseRepository[Document]:
    return BaseRepository(Document, db)


@router.get("/", response_model=PaginatedResponse[DocumentOut])
async def list_documents(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    repo: BaseRepository[Document] = Depends(_repo),
    _: TokenPayload = Depends(get_current_user),
):
    offset = (page - 1) * limit
    items, total = await repo.list(offset=offset, limit=limit, order_by="created_at", order="desc")
    pages = (total + limit - 1) // limit
    return PaginatedResponse(items=list(items), total=total, page=page, pages=pages, limit=limit)


@router.post("/", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    body: DocumentCreate,
    repo: BaseRepository[Document] = Depends(_repo),
    current_user: TokenPayload = Depends(get_current_user),
):
    data = body.model_dump(by_alias=False)
    # Map metadata_ → metadata column
    data["metadata_"] = data.pop("metadata_", None)
    return await repo.create(data)


@router.get("/{id}/", response_model=DocumentOut)
async def get_document(
    id: int,
    repo: BaseRepository[Document] = Depends(_repo),
    _: TokenPayload = Depends(get_current_user),
):
    from fastapi import HTTPException
    doc = await repo.get(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    id: int,
    repo: BaseRepository[Document] = Depends(_repo),
    _: TokenPayload = Depends(get_current_user),
):
    from fastapi import HTTPException
    doc = await repo.get(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await repo.delete(doc)
