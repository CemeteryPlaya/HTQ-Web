"""Department file manager endpoints."""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.core.settings import settings
from app.db import get_db_session
from app.models.department import Department
from app.models.department_file import DepartmentFile, DepartmentFileFolder
from app.models.employee import Employee
from app.schemas.department_file import (
    DepartmentFileFolderCreate,
    DepartmentFileFolderOut,
    DepartmentFileOut,
    DepartmentFolderOut,
)


router = APIRouter(tags=["department-files"])


def _is_admin(user: TokenPayload) -> bool:
    return bool(user.is_admin or user.is_staff or user.is_superuser)


async def _employee_for_user(session: AsyncSession, user: TokenPayload) -> Employee | None:
    if user.user_id is None:
        return None
    result = await session.execute(
        select(Employee).where(Employee.user_id == user.user_id, Employee.is_deleted.is_(False))
    )
    return result.scalar_one_or_none()


async def _assert_department_access(
    session: AsyncSession,
    user: TokenPayload,
    department_id: int,
) -> Department:
    department = await session.get(Department, department_id)
    if department is None or not department.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    if _is_admin(user):
        return department

    employee = await _employee_for_user(session, user)
    if employee is None or employee.department_id != department_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Department access denied")
    return department


async def _assert_file_folder_access(
    session: AsyncSession,
    user: TokenPayload,
    file_folder_id: int,
    *,
    department_id: int | None = None,
) -> DepartmentFileFolder:
    file_folder = await session.get(DepartmentFileFolder, file_folder_id)
    if file_folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File folder not found")
    if department_id is not None and file_folder.department_id != department_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File folder not found")
    await _assert_department_access(session, user, file_folder.department_id)
    return file_folder


def _employee_display_name(employee: Employee | None, user: TokenPayload) -> str | None:
    if employee is not None:
        full_name = " ".join(part for part in [employee.first_name, employee.last_name] if part)
        if full_name:
            return full_name
    return user.username or user.email


def _normalize_folder_name(name: str) -> str:
    normalized = " ".join(name.strip().split())
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder name is required")
    return normalized


def _to_file_folder_out(row: DepartmentFileFolder, files_count: int = 0) -> DepartmentFileFolderOut:
    return DepartmentFileFolderOut(
        id=row.id,
        department=row.department_id,
        name=row.name,
        files_count=files_count,
        created_by=row.created_by_user_id,
        created_by_name=row.created_by_name,
        created_at=row.created_at,
    )


def _to_file_out(row: DepartmentFile) -> DepartmentFileOut:
    return DepartmentFileOut(
        id=row.id,
        folder=row.department_id,
        file_folder=row.file_folder_id,
        name=row.name,
        file=row.file_url,
        file_url=row.file_url,
        file_size=row.file_size,
        uploaded_by=row.uploaded_by_user_id,
        uploaded_by_name=row.uploaded_by_name,
        description=row.description,
        created_at=row.created_at,
    )


async def _upload_to_media(
    *,
    request: Request,
    file: UploadFile,
) -> dict[str, Any]:
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")

    content = await file.read()
    files = {
        "file": (
            file.filename or "upload.bin",
            content,
            file.content_type or "application/octet-stream",
        )
    }
    data = {"scope": "hr_department", "is_public": "false"}

    # Generous read/write budget: a blanket 30s total raced with media-service's
    # own ~30s storage write and produced false 502s even though the file was
    # saved. Connect stays short so a genuinely-down media-service fails fast.
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings.media_service_url.rstrip('/')}/api/media/v1/files/",
                data=data,
                files=files,
                headers={"Authorization": authorization},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="media-service unavailable") from exc

    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="media-service returned invalid JSON") from exc
    if "id" not in payload:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="media-service response is missing file id")
    return payload


@router.get("/department-folders/", response_model=list[DepartmentFolderOut])
async def list_department_folders(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
) -> list[DepartmentFolderOut]:
    department_query = select(Department).where(Department.is_active.is_(True)).order_by(Department.name)
    if not _is_admin(current_user):
        employee = await _employee_for_user(session, current_user)
        if employee is None:
            return []
        department_query = department_query.where(Department.id == employee.department_id)

    departments = list((await session.execute(department_query)).scalars().all())
    if not departments:
        return []

    count_result = await session.execute(
        select(DepartmentFile.department_id, func.count(DepartmentFile.id))
        .where(DepartmentFile.department_id.in_([department.id for department in departments]))
        .group_by(DepartmentFile.department_id)
    )
    counts = {department_id: count for department_id, count in count_result.all()}

    return [
        DepartmentFolderOut(
            id=department.id,
            department=department.id,
            department_name=department.name,
            files_count=int(counts.get(department.id, 0)),
            created_at=department.created_at,
        )
        for department in departments
    ]


async def _accessible_department_ids(session: AsyncSession, user: TokenPayload) -> list[int] | None:
    """Return the department ids the user may browse, or ``None`` for "all" (admins)."""
    if _is_admin(user):
        return None
    employee = await _employee_for_user(session, user)
    if employee is None or employee.department_id is None:
        return []
    return [employee.department_id]


@router.get("/department-files/search/", response_model=list[DepartmentFileOut])
async def search_department_files(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    q: str = Query(..., min_length=1, description="Free-text: file name / description"),
    limit: int = Query(20, ge=1, le=100),
) -> list[DepartmentFileOut]:
    """Search files by name/description across the departments the user can access."""
    department_ids = await _accessible_department_ids(session, current_user)
    if department_ids is not None and not department_ids:
        return []

    pattern = f"%{q.strip()}%"
    stmt = (
        select(DepartmentFile)
        .where(
            (DepartmentFile.name.ilike(pattern))
            | (DepartmentFile.description.ilike(pattern))
        )
        .order_by(DepartmentFile.created_at.desc())
        .limit(limit)
    )
    if department_ids is not None:
        stmt = stmt.where(DepartmentFile.department_id.in_(department_ids))

    result = await session.execute(stmt)
    return [_to_file_out(row) for row in result.scalars().all()]


@router.get("/department-file-folders/", response_model=list[DepartmentFileFolderOut])
async def list_department_file_folders(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    department: int = Query(..., ge=1),
) -> list[DepartmentFileFolderOut]:
    await _assert_department_access(session, current_user, department)
    result = await session.execute(
        select(DepartmentFileFolder)
        .where(DepartmentFileFolder.department_id == department)
        .order_by(DepartmentFileFolder.name)
    )
    folders = list(result.scalars().all())
    if not folders:
        return []

    count_result = await session.execute(
        select(DepartmentFile.file_folder_id, func.count(DepartmentFile.id))
        .where(DepartmentFile.file_folder_id.in_([folder.id for folder in folders]))
        .group_by(DepartmentFile.file_folder_id)
    )
    counts = {folder_id: count for folder_id, count in count_result.all()}
    return [_to_file_folder_out(folder, int(counts.get(folder.id, 0))) for folder in folders]


@router.post(
    "/department-file-folders/",
    response_model=DepartmentFileFolderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_department_file_folder(
    payload: DepartmentFileFolderCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
) -> DepartmentFileFolderOut:
    await _assert_department_access(session, current_user, payload.department)
    name = _normalize_folder_name(payload.name)
    existing = await session.execute(
        select(DepartmentFileFolder).where(
            DepartmentFileFolder.department_id == payload.department,
            func.lower(DepartmentFileFolder.name) == name.lower(),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Folder already exists")

    employee = await _employee_for_user(session, current_user)
    row = DepartmentFileFolder(
        department_id=payload.department,
        name=name,
        created_by_user_id=current_user.user_id,
        created_by_name=_employee_display_name(employee, current_user),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _to_file_folder_out(row, 0)


@router.get("/department-files/", response_model=list[DepartmentFileOut])
async def list_department_files(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    folder: int = Query(..., ge=1),
    file_folder: int | None = Query(default=None, ge=1),
    root_only: bool = Query(default=False),
) -> list[DepartmentFileOut]:
    await _assert_department_access(session, current_user, folder)
    query = select(DepartmentFile).where(DepartmentFile.department_id == folder)
    if file_folder is not None:
        await _assert_file_folder_access(session, current_user, file_folder, department_id=folder)
        query = query.where(DepartmentFile.file_folder_id == file_folder)
    elif root_only:
        query = query.where(DepartmentFile.file_folder_id.is_(None))

    result = await session.execute(query.order_by(DepartmentFile.created_at.desc()))
    return [_to_file_out(row) for row in result.scalars().all()]


@router.post("/department-files/", response_model=DepartmentFileOut, status_code=status.HTTP_201_CREATED)
async def upload_department_file(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    folder: int = Form(...),
    file_folder: int | None = Form(None),
    file: UploadFile = File(...),
    description: str = Form(""),
) -> DepartmentFileOut:
    await _assert_department_access(session, current_user, folder)
    if file_folder is not None:
        await _assert_file_folder_access(session, current_user, file_folder, department_id=folder)

    # Release the pooled DB connection (end the read-only access-check
    # transaction) BEFORE the outbound call to media-service. Holding an open
    # asyncpg connection across the httpx request stalls that request until the
    # socket times out (~30s) and surfaces as a false "media-service
    # unavailable" 502. SQLAlchemy transparently checks out a fresh connection
    # for the queries below.
    await session.commit()

    media = await _upload_to_media(request=request, file=file)
    employee = await _employee_for_user(session, current_user)

    row = DepartmentFile(
        department_id=folder,
        file_folder_id=file_folder,
        media_file_id=str(media["id"]),
        name=media.get("original_filename") or file.filename or "upload.bin",
        file_url=media.get("url") or f"/api/media/v1/files/{media['id']}",
        file_size=int(media.get("size") or 0),
        mime_type=media.get("mime") or file.content_type or "application/octet-stream",
        uploaded_by_user_id=current_user.user_id,
        uploaded_by_name=_employee_display_name(employee, current_user),
        description=description or "",
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)

    # Notify every other employee in the same department that a new file
    # arrived. The messenger Файлы bot turns each event into a DM line.
    try:
        from sqlalchemy import select as _select
        import json as _json
        import redis.asyncio as _aioredis

        from app.core.settings import settings as _settings
        from app.models.department import Department as _Department

        stmt = _select(Employee).where(
            Employee.department_id == folder,
            Employee.is_deleted.is_(False),
            Employee.user_id.is_not(None),
        )
        dept_employees = (await session.execute(stmt)).scalars().all()
        dept = await session.get(_Department, folder)
        dept_name = dept.name if dept else None
        client = _aioredis.Redis.from_url(_settings.redis_url)
        try:
            for emp in dept_employees:
                if not emp.user_id or emp.user_id == current_user.user_id:
                    continue
                await client.publish(
                    "notify.file_access_request",
                    _json.dumps(
                        {
                            "user_id": int(emp.user_id),
                            "requester_name": uploaded_by_name or "",
                            "file_name": row.name,
                            "department_name": dept_name,
                            "file_id": str(row.id),
                        },
                        default=str,
                    ),
                )
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001
        # Publish errors must not block the upload from succeeding.
        pass

    return _to_file_out(row)


@router.delete("/department-files/{file_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department_file(
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
) -> None:
    row = await session.get(DepartmentFile, file_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department file not found")
    await _assert_department_access(session, current_user, row.department_id)
    await session.delete(row)
