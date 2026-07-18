"""News endpoints — ``/api/cms/v1/news/*``.

The list endpoint returns a paginated envelope (``Page[NewsRead]``).
Anonymous and non-admin readers see only published articles whose
``published_at`` (or ``scheduled_at`` for ``status='scheduled'``) has elapsed —
this lets ``status='scheduled'`` articles auto-flip to public at the right
moment without needing a background worker tick.
"""

import re
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import TokenPayload, get_optional_user, require_admin
from app.core.logging import get_logger
from app.db import get_db_session
from app.models.news import News, NewsStatus
from app.models.news_attachment import NewsAttachment
from app.models.taxonomy import Category, Tag
from app.schemas.news import (
    NewsAttachmentRead,
    NewsCreate,
    NewsRead,
    NewsTranslateRequest,
    NewsTranslateResponse,
    NewsUpdate,
    Page,
)
from app.services.audit import record_action
from app.services.news_snapshot import delete_news_snapshot, write_news_snapshot
from app.services.s3_storage import get_storage
from app.services.signed_url import verify as verify_signature


router = APIRouter(tags=["news"])
log = get_logger(__name__)


# --- helpers ---------------------------------------------------------------


def _is_admin(user: Optional[TokenPayload]) -> bool:
    return bool(user and user.is_admin)


def _public_visibility_clause():
    """SQL filter for what anonymous / non-admin readers may see.

    Published items are always visible. Scheduled items become visible once
    their ``scheduled_at`` is in the past — this is the lazy auto-publish
    path. Drafts and archived items are never visible to the public.
    """
    now = datetime.now(timezone.utc)
    return or_(
        News.status == NewsStatus.PUBLISHED,
        and_(News.status == NewsStatus.SCHEDULED, News.scheduled_at <= now),
    )


def _apply_status_side_effects(news: News) -> None:
    """Keep ``published_at`` / ``scheduled_at`` consistent with status.

    The DB trigger from migration 0003 also normalizes ``published`` and
    ``published_at`` on write; doing it here too means the ORM-level object
    returned from create/update reflects the same values without a refresh.
    """
    now = datetime.now(timezone.utc)
    if news.status == NewsStatus.PUBLISHED:
        news.published = True
        if not news.published_at:
            news.published_at = now
        news.scheduled_at = None
    elif news.status == NewsStatus.SCHEDULED:
        news.published = False
        news.published_at = None
    else:  # draft / archived
        news.published = False
        news.published_at = None


async def _resolve_tags(session: AsyncSession, tag_ids: list[int]) -> list[Tag]:
    if not tag_ids:
        return []
    result = await session.execute(select(Tag).where(Tag.id.in_(tag_ids)))
    tags = list(result.scalars().all())
    found = {t.id for t in tags}
    missing = [tid for tid in tag_ids if tid not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown tag ids: {missing}",
        )
    return tags


# --- endpoints -------------------------------------------------------------


@router.get("/", response_model=Page[NewsRead])
async def list_news(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[Optional[TokenPayload], Depends(get_optional_user)],
    category: Optional[str] = Query(None, max_length=120, description="Category slug"),
    tag: Optional[str] = Query(None, max_length=80, description="Tag slug"),
    status_filter: Optional[NewsStatus] = Query(None, alias="status"),
    q: Optional[str] = Query(None, max_length=200, description="Search in title/excerpt"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
) -> Page[NewsRead]:
    base = select(News).options(selectinload(News.tags))

    # Visibility gate
    if not _is_admin(user):
        base = base.where(_public_visibility_clause())
    elif status_filter is not None:
        base = base.where(News.status == status_filter)

    # Filters
    if category:
        base = base.join(Category, News.category_id == Category.id, isouter=True).where(
            or_(Category.slug == category, News.category == category)
        )
    if tag:
        base = base.join(News.tags).where(Tag.slug == tag)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(or_(News.title.ilike(like), News.excerpt.ilike(like)))

    # Order: scheduled-going-live first (scheduled_at desc), then published_at, then created_at
    ordered = base.order_by(
        News.published_at.desc().nullslast(),
        News.scheduled_at.desc().nullslast(),
        News.created_at.desc(),
    )

    total = (await session.execute(
        select(func.count()).select_from(ordered.order_by(None).subquery())
    )).scalar_one()

    offset = (page - 1) * page_size
    rows = (await session.execute(ordered.limit(page_size).offset(offset))).unique().scalars().all()
    items = [NewsRead.model_validate(n) for n in rows]
    return Page[NewsRead](
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        has_next=(page * page_size) < total,
    )


@router.get("/by-slug/{slug}", response_model=NewsRead)
async def get_news_by_slug(
    slug: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[Optional[TokenPayload], Depends(get_optional_user)],
) -> News:
    result = await session.execute(
        select(News).options(selectinload(News.tags)).where(News.slug == slug)
    )
    news = result.unique().scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")
    if not _is_admin(user):
        # mirror list-endpoint visibility gate
        now = datetime.now(timezone.utc)
        is_public = news.status == NewsStatus.PUBLISHED or (
            news.status == NewsStatus.SCHEDULED
            and news.scheduled_at is not None
            and news.scheduled_at <= now
        )
        if not is_public:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")
    return news


@router.get("/{news_id}", response_model=NewsRead)
async def get_news(
    news_id: int,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[Optional[TokenPayload], Depends(get_optional_user)],
) -> News:
    result = await session.execute(
        select(News).options(selectinload(News.tags)).where(News.id == news_id)
    )
    news = result.unique().scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")
    if not _is_admin(user) and news.status not in {NewsStatus.PUBLISHED}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")
    return news


@router.post("/", response_model=NewsRead, status_code=status.HTTP_201_CREATED)
async def create_news(
    payload: NewsCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> News:
    data = payload.model_dump(exclude={"tag_ids"})
    if data.get("author_id") is None:
        data["author_id"] = admin.user_id

    news = News(**data)
    news.tags = await _resolve_tags(session, payload.tag_ids)
    _apply_status_side_effects(news)
    session.add(news)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"News with slug '{payload.slug}' already exists",
        )
    await session.refresh(news, attribute_names=["tags", "category_ref"])

    await record_action(
        session,
        user_id=admin.user_id,
        action="news_created",
        resource_type="News",
        resource_id=str(news.id),
        changes=payload.model_dump(mode="json"),
        request=request,
    )
    # Mirror the post into S3 (content.md + metadata.json) so off-DB tools
    # and backups always see the canonical version. Snapshot failures are
    # logged but don't block the API — DB is the source of truth.
    try:
        await write_news_snapshot(news)
    except Exception as exc:  # noqa: BLE001
        log.warning("news_snapshot_failed", news_id=news.id, error=str(exc))
    if news.published:
        await _publish_news_to_messenger_bot(news)
    log.info("news_created", news_id=news.id, slug=news.slug, by=admin.user_id)
    return news


@router.patch("/{news_id}", response_model=NewsRead)
async def update_news(
    news_id: int,
    payload: NewsUpdate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> News:
    result = await session.execute(
        select(News).options(selectinload(News.tags)).where(News.id == news_id)
    )
    news = result.unique().scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")

    changes = payload.model_dump(exclude_unset=True)
    tag_ids = changes.pop("tag_ids", None)
    legacy_published = changes.pop("published", None)
    if legacy_published is not None and "status" not in changes:
        changes["status"] = NewsStatus.PUBLISHED if legacy_published else NewsStatus.DRAFT

    for key, value in changes.items():
        setattr(news, key, value)
    if tag_ids is not None:
        news.tags = await _resolve_tags(session, tag_ids)
    _apply_status_side_effects(news)

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug conflict")

    await session.refresh(news, attribute_names=["tags", "category_ref"])
    await record_action(
        session,
        user_id=admin.user_id,
        action="news_updated",
        resource_type="News",
        resource_id=str(news.id),
        changes=changes if "status" not in changes else {**changes, "status": changes["status"].value},
        request=request,
    )
    # Re-snapshot on every change so the bucket stays in lockstep with the
    # DB — the user explicitly asked for snapshots to be overwritten on
    # any publication change, not just on initial publish.
    try:
        await write_news_snapshot(news)
    except Exception as exc:  # noqa: BLE001
        log.warning("news_snapshot_failed", news_id=news.id, error=str(exc))
    # Fire the bot fan-out only on a fresh publish transition. We can't tell
    # for sure here (would need the pre-update value); the messenger
    # subscriber tolerates a small amount of duplicates per news.slug, so
    # we conservatively re-publish whenever `published` ends up True.
    if news.published:
        await _publish_news_to_messenger_bot(news)
    return news


async def _publish_news_to_messenger_bot(news: News) -> None:
    """Emit ``notify.news_for_department`` so the messenger 📰 Новости
    bot can DM every employee. Best-effort — Redis failures are logged
    but don't propagate into the user-facing response.
    """
    try:
        import json as _json
        import redis.asyncio as _aioredis

        from app.core.settings import settings as _settings

        client = _aioredis.Redis.from_url(_settings.redis_url)
        try:
            await client.publish(
                "notify.news_for_department",
                _json.dumps(
                    {
                        "news_id": news.id,
                        "slug": news.slug,
                        "title": news.title,
                        "excerpt": (news.summary or "")[:240],
                    },
                    default=str,
                ),
            )
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        log.warning("news_bot_publish_failed", news_id=news.id, error=str(exc))


@router.delete("/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_news(
    news_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> None:
    news = await session.get(News, news_id)
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")
    slug = news.slug
    await session.delete(news)
    await record_action(
        session,
        user_id=admin.user_id,
        action="news_deleted",
        resource_type="News",
        resource_id=str(news_id),
        changes={"slug": slug},
        request=request,
    )
    try:
        await delete_news_snapshot(news_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("news_snapshot_delete_failed", news_id=news_id, error=str(exc))
    log.info("news_deleted", news_id=news_id, slug=slug, by=admin.user_id)


@router.post(
    "/{news_id}/translate",
    response_model=NewsTranslateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def translate_news(
    news_id: int,
    payload: NewsTranslateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> NewsTranslateResponse:
    news = await session.get(News, news_id)
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")

    from app.workers.actors import translate_news as translate_actor

    message = translate_actor.send(news.id, payload.target)
    log.info(
        "translate_news_enqueued",
        news_id=news.id,
        target=payload.target,
        task_id=message.message_id,
        by=admin.user_id,
    )
    return NewsTranslateResponse(
        task_id=message.message_id,
        news_id=news.id,
        target=payload.target,
    )


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str | None) -> str:
    raw = PurePosixPath((name or "file").replace("\\", "/")).name
    cleaned = _SAFE_FILENAME_RE.sub("_", raw).strip("._")
    return (cleaned or "file")[:180]


def _cover_object_key(news_id: int, filename: str) -> str:
    suffix = PurePosixPath(filename).suffix.lower() or ".bin"
    return f"news/{news_id}/cover{suffix}"


def _attachment_object_key(news_id: int, attachment_id: uuid.UUID, filename: str) -> str:
    return f"news/{news_id}/attachments/{attachment_id}_{filename}"


@router.post(
    "/{news_id}/cover",
    response_model=NewsAttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_cover(
    news_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
    file: Annotated[UploadFile, File(...)],
) -> NewsAttachment:
    """Upload (or replace) the post's cover image.

    Stored at ``news/<id>/cover.<ext>`` in S3; the post's ``image`` column
    is updated with that S3 key so the existing list/detail responses keep
    working unchanged.
    """
    news = await session.get(News, news_id)
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")

    filename = _safe_filename(file.filename)
    content_type = file.content_type or "application/octet-stream"
    object_key = _cover_object_key(news_id, filename)

    body = await file.read()
    storage = get_storage()
    await storage.save(object_key, body, content_type=content_type)

    # Drop any previous cover row for this post so the table doesn't accrue
    # orphans every time admin replaces the image.
    existing = (
        await session.execute(
            select(NewsAttachment).where(
                NewsAttachment.news_id == news_id,
                NewsAttachment.role == "cover",
            )
        )
    ).scalars().all()
    for prev in existing:
        await session.delete(prev)

    attachment = NewsAttachment(
        news_id=news_id,
        role="cover",
        filename=filename,
        size=len(body),
        content_type=content_type,
        storage_path=object_key,
        uploaded_by=admin.user_id,
    )
    session.add(attachment)
    news.image = object_key
    await session.flush()
    await session.refresh(attachment)

    await record_action(
        session,
        user_id=admin.user_id,
        action="news_cover_uploaded",
        resource_type="News",
        resource_id=str(news_id),
        changes={"storage_path": object_key, "filename": filename},
        request=request,
    )
    # Re-snapshot metadata so the bucket sees the new cover path.
    try:
        await write_news_snapshot(news, storage=storage)
    except Exception as exc:  # noqa: BLE001
        log.warning("news_snapshot_failed", news_id=news_id, error=str(exc))
    return attachment


@router.post(
    "/{news_id}/attachments",
    response_model=NewsAttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_news_attachment(
    news_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
    file: Annotated[UploadFile, File(...)],
) -> NewsAttachment:
    news = await session.get(News, news_id)
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")

    attachment_id = uuid.uuid4()
    filename = _safe_filename(file.filename)
    content_type = file.content_type or "application/octet-stream"
    object_key = _attachment_object_key(news_id, attachment_id, filename)

    body = await file.read()
    storage = get_storage()
    await storage.save(object_key, body, content_type=content_type)

    attachment = NewsAttachment(
        id=attachment_id,
        news_id=news_id,
        role="attachment",
        filename=filename,
        size=len(body),
        content_type=content_type,
        storage_path=object_key,
        uploaded_by=admin.user_id,
    )
    session.add(attachment)
    await session.flush()
    await session.refresh(attachment)

    await record_action(
        session,
        user_id=admin.user_id,
        action="news_attachment_uploaded",
        resource_type="News",
        resource_id=str(news_id),
        changes={
            "attachment_id": str(attachment_id),
            "storage_path": object_key,
            "filename": filename,
        },
        request=request,
    )
    return attachment


@router.get("/{news_id}/attachments", response_model=list[NewsAttachmentRead])
async def list_news_attachments(
    news_id: int,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[Optional[TokenPayload], Depends(get_optional_user)],
) -> list[NewsAttachment]:
    news = await session.get(News, news_id)
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")
    if not news.published and not (user and user.is_admin):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News not found")

    rows = (
        await session.execute(
            select(NewsAttachment)
            .where(NewsAttachment.news_id == news_id)
            .order_by(NewsAttachment.created_at.asc())
        )
    ).scalars().all()
    return list(rows)


@router.get("/attachments/{attachment_id}", include_in_schema=False)
async def serve_news_attachment(
    attachment_id: uuid.UUID,
    sig: Annotated[str, Query(...)],
    exp: Annotated[int, Query(...)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RedirectResponse:
    if not verify_signature(str(attachment_id), sig, exp):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired signature")

    attachment = await session.get(NewsAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    storage = get_storage()
    presigned = await storage.presigned_get_url(attachment.storage_path)
    return RedirectResponse(url=presigned, status_code=status.HTTP_302_FOUND)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_news_attachment(
    attachment_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> None:
    attachment = await session.get(NewsAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    storage = get_storage()
    try:
        await storage.delete(attachment.storage_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("news_attachment_s3_delete_failed", id=str(attachment_id), error=str(exc))

    news_id = attachment.news_id
    await session.delete(attachment)
    await record_action(
        session,
        user_id=admin.user_id,
        action="news_attachment_deleted",
        resource_type="News",
        resource_id=str(news_id),
        changes={"attachment_id": str(attachment_id)},
        request=request,
    )
