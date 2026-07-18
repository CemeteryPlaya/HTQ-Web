"""Image thumbnail generation for chat attachments.

The full-resolution original lives at ``storage_path``. For images we also
generate a ≤ 256×256 WebP preview that the UI uses inline — saves
bandwidth on 10 MB photos that the chat bubble renders at 280×320.

The bytes pass through Pillow with the EXIF orientation applied so the
preview matches what a phone camera intended.
"""

from __future__ import annotations

import io
from typing import Optional

import structlog
from PIL import Image, ImageOps, UnidentifiedImageError

logger = structlog.get_logger(__name__)

# Inline thumbnails in chat are rendered at most 280×320 in the bubble and
# 64×64 in the search panel. 256 px gives us a 2× retina margin on the
# smaller dimension and keeps the file size around 10–30 KB for WebP.
THUMB_MAX_SIDE = 256
THUMB_FORMAT = "WEBP"
THUMB_QUALITY = 80
THUMB_EXTENSION = "webp"


def make_thumbnail(
    raw: bytes,
) -> tuple[Optional[bytes], Optional[int], Optional[int]]:
    """Return ``(thumb_bytes, orig_width, orig_height)`` for an image.

    Returns ``(None, None, None)`` when ``raw`` isn't a recognisable image
    so the caller can fall back to "no thumbnail" gracefully — this happens
    for SVG (we don't rasterise), encrypted blobs, or animated formats we
    don't downscale (we still record the dimensions if Pillow can read them).
    """
    try:
        with Image.open(io.BytesIO(raw)) as src:
            # EXIF rotation: phones store landscape JPEGs with a "rotate 90°"
            # flag instead of physically rotating the pixels.
            src = ImageOps.exif_transpose(src)
            orig_w, orig_h = src.size

            # Already small enough — reuse the original bytes as the "thumb"
            # to avoid a transcode for tiny images. We still want a WebP for
            # the unified content-type, so transcode unless it's already WebP.
            if (
                orig_w <= THUMB_MAX_SIDE
                and orig_h <= THUMB_MAX_SIDE
                and src.format == "WEBP"
            ):
                return raw, orig_w, orig_h

            # Pillow ``thumbnail`` mutates in place and never enlarges.
            preview = src.copy()
            preview.thumbnail(
                (THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.Resampling.LANCZOS
            )
            # WebP doesn't accept palette-mode (mode "P") images directly.
            if preview.mode not in ("RGB", "RGBA"):
                preview = preview.convert(
                    "RGBA" if preview.mode in ("LA", "PA") else "RGB"
                )
            out = io.BytesIO()
            preview.save(
                out,
                format=THUMB_FORMAT,
                quality=THUMB_QUALITY,
                method=4,
            )
            return out.getvalue(), orig_w, orig_h
    except UnidentifiedImageError:
        logger.info("attachment_thumb_unsupported_format")
        return None, None, None
    except Exception as exc:  # noqa: BLE001
        # Pillow can blow up on truncated files, EXIF parser bugs, etc.
        # Don't fail the upload — non-image fallback is fine.
        logger.warning("attachment_thumb_generation_failed", err=str(exc))
        return None, None, None


def thumbnail_object_key(*, original_key: str) -> str:
    """Sibling object key for the thumbnail.

    ``chats/<storage>/images/<id>_<file>`` becomes
    ``chats/<storage>/images/_thumbs/<id>_<file>.webp``. Keeping it under
    the same prefix lets the weekly archive find it via one list-objects
    call.
    """
    # Insert a ``_thumbs/`` segment just before the filename.
    if "/" in original_key:
        head, sep, tail = original_key.rpartition("/")
        return f"{head}{sep}_thumbs/{tail}.{THUMB_EXTENSION}"
    return f"_thumbs/{original_key}.{THUMB_EXTENSION}"
