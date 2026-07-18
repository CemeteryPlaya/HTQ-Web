"""Dramatiq actors for media-service.

The dramatiq message handler is sync, so each actor wraps an async impl
through ``asyncio.run`` — this keeps the storage layer (aiofiles / aioboto3)
working without dragging in extra plumbing.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from pathlib import PurePosixPath

import dramatiq
from sqlalchemy import select

from app.core.logging import get_logger
from app.core.scope_policy import get_policy
from app.core.settings import settings
from app.db import async_session_factory
from app.models.file_metadata import FileMetadata
from app.models.file_variant import FileVariant
from app.services.image_service import ImageProcessingError, make_variant
from app.storage import get_storage
from app.workers import broker  # noqa: F401  -- ensures broker is initialised


log = get_logger(__name__)
_logger = logging.getLogger(__name__)


def _variant_path(original_path: str, variant: str, fmt: str) -> str:
    """Place variants next to the original under ``<dir>/<variant>.<ext>``.

    The new layout (``<scope>/<yyyy>/<mm>/<uuid>/original.<ext>``) leaves a
    natural directory for the variants. For older files that still live at
    ``<yyyy>/<mm>/<uuid>.<ext>`` we strip the trailing extension and create
    a sibling directory keyed by uuid.
    """
    p = PurePosixPath(original_path)
    ext = {"WEBP": ".webp", "JPEG": ".jpg", "PNG": ".png"}.get(fmt, ".bin")
    if p.name == f"original{p.suffix}":
        # New layout: keep the same parent directory.
        return str(p.parent / f"{variant}{ext}")
    # Legacy layout: ``<yyyy>/<mm>/<uuid>.<ext>`` → ``<yyyy>/<mm>/<uuid>/<variant><ext>``.
    return str(p.parent / p.stem / f"{variant}{ext}")


async def _make_variants_impl(file_id: str) -> int:
    async with async_session_factory() as session:
        try:
            meta = await session.get(FileMetadata, uuid.UUID(file_id))
            if meta is None or meta.deleted_at is not None:
                _logger.info("make_variants: file gone, skipping id=%s", file_id)
                return 0
            if not meta.kind == "image":
                _logger.info("make_variants: not an image, skipping id=%s kind=%s", file_id, meta.kind)
                return 0

            policy = get_policy(meta.scope)
            if not policy.variants:
                _logger.info(
                    "make_variants: scope=%s has no variants configured, skipping id=%s",
                    meta.scope,
                    file_id,
                )
                return 0

            existing = await session.execute(
                select(FileVariant.variant).where(FileVariant.file_id == meta.id)
            )
            existing_names = {row[0] for row in existing.all()}

            storage = get_storage()
            original = await storage.open(meta.path)

            created = 0
            for variant_name in policy.variants:
                if variant_name in existing_names:
                    continue
                try:
                    out = make_variant(original, variant_name)
                except ImageProcessingError as exc:
                    _logger.warning(
                        "make_variants: %s failed for id=%s: %s", variant_name, file_id, exc
                    )
                    continue

                variant_path = _variant_path(meta.path, variant_name, out.format)
                await storage.save(variant_path, out.data)

                session.add(
                    FileVariant(
                        file_id=meta.id,
                        variant=variant_name,
                        path=variant_path,
                        size=len(out.data),
                        mime=out.mime,
                        width=out.width,
                        height=out.height,
                    )
                )
                created += 1

            await session.commit()
            log.info(
                "variants_generated",
                file_id=file_id,
                created=created,
                already=len(existing_names),
                requested=list(policy.variants),
            )
            return created
        except Exception:
            await session.rollback()
            _logger.exception("make_variants failed for id=%s", file_id)
            raise


@dramatiq.actor(max_retries=3, min_backoff=5_000, max_backoff=300_000)
def make_variants(file_id: str) -> None:
    """Generate all configured variants for a freshly-uploaded image."""
    asyncio.run(_make_variants_impl(file_id))


# ─── Cleanup ───────────────────────────────────────────────────────────────


async def _purge_soft_deleted_impl() -> int:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=settings.soft_delete_grace_days
    )
    async with async_session_factory() as session:
        rows = await session.execute(
            select(FileMetadata).where(
                FileMetadata.deleted_at.is_not(None),
                FileMetadata.deleted_at < cutoff,
            )
        )
        files = list(rows.scalars().all())
        if not files:
            return 0

        storage = get_storage()
        purged = 0
        for meta in files:
            # Drop variant files first (FK cascades the rows on delete).
            for v in list(meta.variants):
                try:
                    await storage.delete(v.path)
                except Exception:  # pragma: no cover — keep going on storage glitches
                    _logger.exception("purge: failed to drop variant %s", v.path)
            try:
                await storage.delete(meta.path)
            except Exception:
                _logger.exception("purge: failed to drop original %s", meta.path)
            await session.delete(meta)
            purged += 1
        await session.commit()
        log.info("soft_delete_purged", count=purged, grace_days=settings.soft_delete_grace_days)
        return purged


@dramatiq.actor
def purge_soft_deleted() -> None:
    """Reap files past their soft-delete grace period."""
    asyncio.run(_purge_soft_deleted_impl())


@dramatiq.actor
def cleanup_orphan_files() -> None:
    """Reserved: scan storage for files with no DB row and remove them.

    Implementation requires a storage-side enumerate which differs between
    backends (LocalStorage vs S3) — left as TODO since it's not blocking
    correctness.
    """
    _logger.info("cleanup_orphan_files: not implemented yet")
