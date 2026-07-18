"""Positions API router — CRUD + weight system."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.auth.dependencies import get_current_user, require_hr_write, TokenPayload
from app.services.position_service import PositionService
from app.schemas.position import (
    PositionCreate, PositionUpdate, PositionOut,
    PositionWeightUpdate, LevelThresholdOut, LevelThresholdCreate,
    LevelThresholdUpdate, PositionMoveRequest, PositionRebalanceRequest,
    PermissionCatalog, PermissionCatalogItem,
)
from app.schemas.common import PaginatedResponse
from app.auth.permissions import LEVEL_PRESETS


# Static catalog — surfaced to the UI so admins can build a permission
# matrix without hard-coding strings into the frontend. The keys are
# authoritative and enforced via ``app.auth.hr_access`` (HRAccess.has /
# require_permission); ``hr_level`` is a preset that fills the key-set.
_PERMISSION_CATALOG = PermissionCatalog(
    hr_levels=[
        {"value": "junior", "label": "Junior", "description": "Просмотр своих данных и базовых справочников"},
        {"value": "middle", "label": "Middle", "description": "Редактирование данных в рамках своего отдела"},
        {"value": "senior", "label": "Senior", "description": "Полный просмотр + создание сотрудников"},
        {"value": "lead",   "label": "Lead",   "description": "Полный доступ ко всем HR-функциям"},
    ],
    permissions=[
        PermissionCatalogItem(key="hr.employees.view",    label="Просмотр сотрудников",   group="Сотрудники"),
        PermissionCatalogItem(key="hr.employees.create",  label="Создание сотрудников",   group="Сотрудники"),
        PermissionCatalogItem(key="hr.employees.edit",    label="Редактирование данных",  group="Сотрудники"),
        PermissionCatalogItem(key="hr.employees.delete",  label="Удаление сотрудников",   group="Сотрудники"),
        PermissionCatalogItem(key="hr.employees.transfer",  label="Переводы",               group="Сотрудники"),
        PermissionCatalogItem(key="hr.employees.view.all", label="Просмотр всех отделов", group="Сотрудники"),
        PermissionCatalogItem(key="hr.users.list",         label="Список платформенных аккаунтов", group="Аккаунты"),
        PermissionCatalogItem(key="hr.users.manage",       label="Управление аккаунтами",          group="Аккаунты"),

        PermissionCatalogItem(key="hr.departments.view",  label="Просмотр отделов",       group="Отделы"),
        PermissionCatalogItem(key="hr.departments.edit",  label="Редактирование отделов", group="Отделы"),

        PermissionCatalogItem(key="hr.positions.view",    label="Просмотр должностей",    group="Должности"),
        PermissionCatalogItem(key="hr.positions.edit",    label="Редактирование должностей", group="Должности"),

        PermissionCatalogItem(key="hr.documents.view",    label="Просмотр документов",    group="Документы"),
        PermissionCatalogItem(key="hr.documents.manage",  label="Управление документами", group="Документы"),

        PermissionCatalogItem(key="hr.reports.view",      label="Просмотр отчётности",    group="Отчёты"),

        PermissionCatalogItem(key="hr.card.financial.view", label="Финансы — просмотр", group="Карточка"),
        PermissionCatalogItem(key="hr.card.financial.edit", label="Финансы — изменение", group="Карточка"),
        PermissionCatalogItem(key="hr.card.personal.view",  label="Личные данные — просмотр", group="Карточка"),
        PermissionCatalogItem(key="hr.card.personal.edit",  label="Личные данные — изменение", group="Карточка"),
        PermissionCatalogItem(key="hr.card.certs.view",     label="Сертификаты/СРО — просмотр", group="Карточка"),
        PermissionCatalogItem(key="hr.card.certs.edit",     label="Сертификаты/СРО — изменение", group="Карточка"),
        PermissionCatalogItem(key="hr.card.groups.view",    label="Образование/стаж/семья — просмотр", group="Карточка"),
        PermissionCatalogItem(key="hr.card.groups.edit",    label="Образование/стаж/семья — изменение", group="Карточка"),

        PermissionCatalogItem(key="hr.calendar.view",   label="Календарь — просмотр",  group="Календарь"),
        PermissionCatalogItem(key="hr.calendar.manage", label="Календарь — управление", group="Календарь"),

        PermissionCatalogItem(key="hr.staffing.view",   label="Штатное расписание — просмотр",  group="Штатное расписание"),
        PermissionCatalogItem(key="hr.staffing.manage", label="Штатное расписание — управление", group="Штатное расписание"),
    ],
    level_presets={lvl: sorted(keys) for lvl, keys in LEVEL_PRESETS.items()},
)

router = APIRouter(prefix="/positions", tags=["positions"])


def _svc(db: AsyncSession = Depends(get_db_session)) -> PositionService:
    return PositionService(db)


# ── List endpoints (literal-segment routes MUST precede /{id}/) ───────

@router.get("/", response_model=PaginatedResponse[PositionOut])
async def list_positions(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    svc: PositionService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    items, total = await svc.list_positions(page=page, limit=limit)
    pages = (total + limit - 1) // limit
    return PaginatedResponse(items=items, total=total, page=page, pages=pages, limit=limit)


@router.post("/", response_model=PositionOut, status_code=status.HTTP_201_CREATED)
async def create_position(
    body: PositionCreate,
    svc: PositionService = Depends(_svc),
    _: TokenPayload = Depends(require_hr_write),
):
    return await svc.create_position(body)


# ── Level thresholds (declared BEFORE /{id}/ so `levels` isn't parsed as int)

@router.get("/levels/", response_model=list[LevelThresholdOut])
async def list_level_thresholds(
    svc: PositionService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.list_thresholds()


@router.post("/levels/", response_model=LevelThresholdOut, status_code=status.HTTP_201_CREATED)
async def create_level_threshold(
    body: LevelThresholdCreate,
    svc: PositionService = Depends(_svc),
    current_user: TokenPayload = Depends(require_hr_write),
):
    return await svc.create_threshold(body, actor_user_id=current_user.user_id)


@router.put("/levels/{level_number}", response_model=LevelThresholdOut)
async def update_level_threshold(
    level_number: int,
    body: LevelThresholdUpdate,
    svc: PositionService = Depends(_svc),
    current_user: TokenPayload = Depends(require_hr_write),
):
    """Update weight range for a level; recomputes affected positions' levels."""
    return await svc.update_threshold(
        level_number,
        body,
        actor_user_id=current_user.user_id,
    )


@router.delete("/levels/{level_number}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_level_threshold(
    level_number: int,
    svc: PositionService = Depends(_svc),
    current_user: TokenPayload = Depends(require_hr_write),
):
    await svc.delete_threshold(level_number, actor_user_id=current_user.user_id)


@router.get("/permissions-catalog/", response_model=PermissionCatalog)
async def get_permissions_catalog(
    _: TokenPayload = Depends(get_current_user),
):
    """Available HR levels + advisory permission keys for the UI."""
    return _PERMISSION_CATALOG


@router.post("/rebalance")
async def rebalance_positions(
    body: PositionRebalanceRequest,
    svc: PositionService = Depends(_svc),
    current_user: TokenPayload = Depends(require_hr_write),
):
    if body.level is not None:
        count = await svc.rebalance_level(body.level, actor_user_id=current_user.user_id)
        return {"levels": {body.level: count}, "total": count}
    levels = await svc.rebalance_all(actor_user_id=current_user.user_id)
    return {"levels": levels, "total": sum(levels.values())}


# ── /{id}/ catch-all comes last ───────────────────────────────────────

@router.get("/{id}/", response_model=PositionOut)
async def get_position(
    id: int,
    svc: PositionService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.get_position(id)


@router.put("/{id}/", response_model=PositionOut)
async def update_position(
    id: int,
    body: PositionUpdate,
    svc: PositionService = Depends(_svc),
    current_user: TokenPayload = Depends(require_hr_write),
):
    return await svc.update_position(id, body, actor_user_id=current_user.user_id)


@router.delete("/{id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_position(
    id: int,
    svc: PositionService = Depends(_svc),
    _: TokenPayload = Depends(require_hr_write),
):
    await svc.delete_position(id)


@router.patch("/{id}/weight", response_model=PositionOut)
async def update_position_weight(
    id: int,
    body: PositionWeightUpdate,
    svc: PositionService = Depends(_svc),
    current_user: TokenPayload = Depends(require_hr_write),
):
    """Update position weight; recomputes level automatically."""
    return await svc.update_weight(id, body.weight, actor_user_id=current_user.user_id)


@router.patch("/{id}/move", response_model=PositionOut)
async def move_position(
    id: int,
    body: PositionMoveRequest,
    svc: PositionService = Depends(_svc),
    current_user: TokenPayload = Depends(require_hr_write),
):
    return await svc.move_position(
        id,
        before_position_id=body.before_position_id,
        after_position_id=body.after_position_id,
        target_level=body.target_level,
        actor_user_id=current_user.user_id,
    )
