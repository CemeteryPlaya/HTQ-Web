"""Celery tasks for ``media_files`` — variant (thumbnail) generation.

Ported from ``services/media/app/workers/actors.py``'s ``make_variants``
dramatiq actor. The source wraps an async impl in ``asyncio.run`` because it
runs under an async-only SQLAlchemy engine; the Django ORM is sync, so this
port does its DB/storage work directly, no asyncio needed.

``require_service("media")`` is the FIRST statement, same guard pattern as
``apps/cms/tasks.py`` — a disabled ``media`` app must stop processing queued
variant-generation work too, not just HTTP requests (``ServiceGateMiddleware``
only gates the request/response cycle).
"""

from __future__ import annotations

import datetime
import logging
import uuid
from pathlib import PurePosixPath

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.core.services import require_service
from htqweb.storage import get_storage

from .models import FileMetadata, FileVariant
from .services.image_service import ImageProcessingError, make_variant
from .services.scope_policy import get_policy

logger = logging.getLogger(__name__)


def _variant_path(original_path: str, variant: str, fmt: str) -> str:
    """Place variants next to the original under ``<dir>/<variant>.<ext>``.

    Ported verbatim from the source's ``_variant_path``, including its
    legacy-layout fallback (dead code for this port — every path this app's
    own upload pipeline builds is the "new layout" — kept for parity/
    robustness in case of a future backfill from the old service's data).
    """
    p = PurePosixPath(original_path)
    ext = {"WEBP": ".webp", "JPEG": ".jpg", "PNG": ".png"}.get(fmt, ".bin")
    if p.name == f"original{p.suffix}":
        # New layout: keep the same parent directory.
        return str(p.parent / f"{variant}{ext}")
    # Legacy layout: ``<yyyy>/<mm>/<uuid>.<ext>`` → ``<yyyy>/<mm>/<uuid>/<variant><ext>``.
    return str(p.parent / p.stem / f"{variant}{ext}")


@shared_task(max_retries=3)
def make_variants(file_id: str) -> int:
    """Generate all configured variants for a freshly-uploaded image.

    Enqueued by ``apps.media_files.views.upload_file`` via ``.delay()``, only
    when ``get_policy(scope).variants`` is non-empty and the upload's
    ``kind == "image"`` (mirrors the source's ``enqueue_variants`` in
    ``upload_file_bytes``).
    """
    require_service("media")

    try:
        meta = FileMetadata.objects.filter(pk=uuid.UUID(file_id)).first()
        if meta is None or meta.deleted_at is not None:
            logger.info("make_variants: file gone, skipping id=%s", file_id)
            return 0
        if meta.kind != "image":
            logger.info(
                "make_variants: not an image, skipping id=%s kind=%s", file_id, meta.kind
            )
            return 0

        policy = get_policy(meta.scope)
        if not policy.variants:
            logger.info(
                "make_variants: scope=%s has no variants configured, skipping id=%s",
                meta.scope,
                file_id,
            )
            return 0

        existing_names = set(
            FileVariant.objects.filter(file_id=meta.id).values_list("variant", flat=True)
        )

        storage = get_storage(bucket=settings.MEDIA_S3_BUCKET)
        original = storage.open(meta.path)

        created = 0
        for variant_name in policy.variants:
            if variant_name in existing_names:
                continue
            try:
                out = make_variant(original, variant_name)
            except ImageProcessingError as exc:
                logger.warning(
                    "make_variants: %s failed for id=%s: %s", variant_name, file_id, exc
                )
                continue

            variant_path = _variant_path(meta.path, variant_name, out.format)
            storage.save(variant_path, out.data, content_type=out.mime)

            FileVariant.objects.create(
                file=meta,
                variant=variant_name,
                path=variant_path,
                size=len(out.data),
                mime=out.mime,
                width=out.width,
                height=out.height,
            )
            created += 1

        logger.info(
            "variants_generated: file_id=%s created=%d already=%d requested=%s",
            file_id,
            created,
            len(existing_names),
            list(policy.variants),
        )
        return created
    except Exception:
        logger.exception("make_variants failed for id=%s", file_id)
        raise


# ─── Cleanup (task 3.4) ──────────────────────────────────────────────────────
#
# Ported from services/media/app/workers/actors.py's ``purge_soft_deleted``
# and ``cleanup_orphan_files`` dramatiq actors. Their schedules come from
# services/media/app/workers/scheduler.py's APScheduler cron jobs (a
# standalone ``cms-scheduler``-style process, also started from the app's
# lifespan) — registered here as django_celery_beat ``PeriodicTask`` rows by
# the ``0002_media_periodic_tasks`` data migration, not invented.
#
# The source's ``audit_log_compaction`` scheduler job (daily 03:30 UTC,
# deletes old ``AuditLog`` rows) has NO actor counterpart in actors.py — the
# task 3.4 brief scopes this port to the two actors.py workers only
# (``make_variants`` was already ported in 3.2). It is not ported here.


@shared_task
def purge_soft_deleted() -> int:
    """Reap ``FileMetadata`` rows (and their storage objects) past their
    soft-delete grace period.

    Ported from ``actors.py``'s ``purge_soft_deleted``
    (``_purge_soft_deleted_impl``): every ``FileMetadata`` whose
    ``deleted_at`` is older than ``settings.MEDIA_SOFT_DELETE_GRACE_DAYS``
    (source: ``settings.soft_delete_grace_days``, default 30) is reaped —
    variant storage objects first, then the original, then the DB rows
    (``FileVariant`` cascades on ``meta.delete()``, but the source drops
    storage objects explicitly since storage isn't transactional; this port
    keeps that explicit order). Storage failures are logged and do not abort
    the sweep — same best-effort contract as the source.

    Scheduled daily at 03:00 UTC (``scheduler.py``'s ``purge_soft_deleted``
    cron job, ``hour=3, minute=0``) via the ``0002_media_periodic_tasks``
    migration.
    """
    require_service("media")

    cutoff = timezone.now() - datetime.timedelta(days=settings.MEDIA_SOFT_DELETE_GRACE_DAYS)
    files = list(FileMetadata.objects.filter(deleted_at__isnull=False, deleted_at__lt=cutoff))
    if not files:
        return 0

    storage = get_storage(bucket=settings.MEDIA_S3_BUCKET)
    purged = 0
    for meta in files:
        for variant in meta.variants.all():
            try:
                storage.delete(variant.path)
            except Exception:
                logger.exception("purge_soft_deleted: failed to drop variant %s", variant.path)
        try:
            storage.delete(meta.path)
        except Exception:
            logger.exception("purge_soft_deleted: failed to drop original %s", meta.path)
        meta.delete()
        purged += 1

    logger.info(
        "purge_soft_deleted: purged %d files (grace_days=%d)",
        purged,
        settings.MEDIA_SOFT_DELETE_GRACE_DAYS,
    )
    return purged


@shared_task
def cleanup_orphan_files() -> None:
    """Reserved: scan storage for files with no ``FileMetadata`` row and
    remove them.

    Ported from ``actors.py``'s ``cleanup_orphan_files`` — a stub in the
    FastAPI source too ("not implemented yet"; the docstring there says the
    implementation needs a storage-side enumerate that differs between
    LocalStorage/S3 and was left as a TODO, not blocking correctness).

    This is the "dead job" case called out in the task 3.4 brief (same
    situation as ``apps.cms.tasks.publish_scheduled_news``'s query that can
    never match against the current schema): rather than silently drop the
    schedule or run a no-op every week, ``0002_media_periodic_tasks``
    registers this job's ``PeriodicTask`` row with ``enabled=False`` — the
    weekly Sunday 04:00 UTC cron from ``scheduler.py`` is preserved as
    documentation of intent, but beat will not actually tick it.
    """
    require_service("media")
    logger.info("cleanup_orphan_files: not implemented yet")
