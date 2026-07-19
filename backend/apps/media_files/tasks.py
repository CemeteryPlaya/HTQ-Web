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

import logging
import uuid
from pathlib import PurePosixPath

from celery import shared_task
from django.conf import settings

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
