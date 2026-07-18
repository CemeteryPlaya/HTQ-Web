"""MongoDB HR documents API router.

CRUD endpoints for HR documents stored in MongoDB.  Each document
is linked to a PostgreSQL ``hr_employees`` record via the
``sql_employee_id`` field (synthetic foreign key).

The router gracefully degrades: when ``mongo_uri`` is not configured
every endpoint returns ``503 Service Unavailable``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import TokenPayload, get_current_user, require_hr_write
from app.mongo import get_hr_documents_collection
from app.schemas.mongo_document import (
    HRDocumentCreate,
    HRDocumentOut,
    HRDocumentUpdate,
)

router = APIRouter(prefix="/mongo-documents", tags=["mongo-documents"])


def _require_collection():
    """Dependency: return the collection or 503 if Mongo is not configured."""
    coll = get_hr_documents_collection()
    if coll is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB is not configured for this service",
        )
    return coll


def _doc_to_out(doc: dict) -> HRDocumentOut:
    """Convert a raw MongoDB document dict to the response schema."""
    doc["_id"] = str(doc["_id"])
    return HRDocumentOut(**doc)


@router.get("/", response_model=list[HRDocumentOut])
async def list_mongo_documents(
    employee_id: int | None = Query(default=None, description="Filter by SQL employee ID"),
    doc_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    coll=Depends(_require_collection),
    _: TokenPayload = Depends(get_current_user),
):
    """List HR documents from MongoDB with optional filters."""
    query: dict = {}
    if employee_id is not None:
        query["sql_employee_id"] = employee_id
    if doc_type:
        query["doc_type"] = doc_type

    skip = (page - 1) * limit
    cursor = coll.find(query).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    return [_doc_to_out(d) for d in docs]


@router.post("/", response_model=HRDocumentOut, status_code=status.HTTP_201_CREATED)
async def create_mongo_document(
    body: HRDocumentCreate,
    coll=Depends(_require_collection),
    current_user: TokenPayload = Depends(require_hr_write),
):
    """Create a new HR document in MongoDB.

    Requires HR write permissions (admin / hr_manager / hr_admin).
    """
    now = datetime.now(timezone.utc)
    doc = {
        **body.model_dump(),
        "doc_type": body.doc_type.value,
        "created_at": now,
        "updated_at": now,
        "created_by_user_id": current_user.user_id,
    }
    result = await coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _doc_to_out(doc)


@router.get("/{doc_id}", response_model=HRDocumentOut)
async def get_mongo_document(
    doc_id: str,
    coll=Depends(_require_collection),
    _: TokenPayload = Depends(get_current_user),
):
    """Retrieve a single HR document by MongoDB ObjectId."""
    try:
        oid = ObjectId(doc_id)
    except (InvalidId, Exception):
        raise HTTPException(status_code=400, detail="Invalid document ID format")

    doc = await coll.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _doc_to_out(doc)


@router.patch("/{doc_id}", response_model=HRDocumentOut)
async def update_mongo_document(
    doc_id: str,
    body: HRDocumentUpdate,
    coll=Depends(_require_collection),
    current_user: TokenPayload = Depends(require_hr_write),
):
    """Partially update an HR document in MongoDB."""
    try:
        oid = ObjectId(doc_id)
    except (InvalidId, Exception):
        raise HTTPException(status_code=400, detail="Invalid document ID format")

    update_data = body.model_dump(exclude_unset=True)
    if "doc_type" in update_data and update_data["doc_type"] is not None:
        update_data["doc_type"] = update_data["doc_type"].value
    update_data["updated_at"] = datetime.now(timezone.utc)

    result = await coll.find_one_and_update(
        {"_id": oid},
        {"$set": update_data},
        return_document=True,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _doc_to_out(result)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mongo_document(
    doc_id: str,
    coll=Depends(_require_collection),
    _: TokenPayload = Depends(require_hr_write),
):
    """Delete an HR document from MongoDB."""
    try:
        oid = ObjectId(doc_id)
    except (InvalidId, Exception):
        raise HTTPException(status_code=400, detail="Invalid document ID format")

    result = await coll.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
