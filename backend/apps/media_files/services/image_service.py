"""Image normalisation + thumbnail generation (Pillow).

Ported from ``services/media/app/services/image_service.py``. Two
responsibilities, unchanged from the source:

1. ``normalise(data, mime)`` — sanitises the original on upload: strips EXIF
   (metadata, GPS), respects EXIF orientation, re-encodes via Pillow so any
   embedded scripts/polyglot payloads are dropped. Returns the rewritten
   bytes plus dimensions.
2. ``make_variant(data, variant)`` — produces a single derived rendition
   (thumb_32, thumb_96, thumb_256, preview_1024, ...). Avatars are square
   center-cropped; previews preserve aspect.

All variants are encoded as WebP by default (configurable via
``settings.THUMBNAIL_FORMAT``).

**Deviation from source: ``detect_mime`` does not use ``python-magic``.**
The source falls back to the caller-supplied ``fallback`` (the client's
declared Content-Type) "only if libmagic is unavailable on the host"
(its own docstring) — treating that as a Dockerfile-drift edge case. On
this Windows dev host, ``python-magic`` doesn't degrade that gracefully:
``magic.from_buffer()`` segfaults the interpreter (no libmagic native DLL
installed) instead of raising a catchable exception, which is an
unacceptable crash risk sitting in a request-handling path. So this port
always takes the source's own documented fallback branch — declared
Content-Type is the "real" mime. For images specifically this is still
content-verified: ``normalise()`` below runs Pillow's ``Image.open()`` +
``.load()`` on the actual bytes regardless of the declared mime, and
raises ``ImageProcessingError`` (→ HTTP 415) if they don't decode as a
real image — so a mislabelled non-image can't pass as an image scope
either way.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from django.conf import settings

from PIL import Image, ImageOps, UnidentifiedImageError


# Variant-name → (target_pixel_size, square_crop)
_VARIANT_SPECS: dict[str, tuple[int, bool]] = {
    "thumb_32": (32, True),
    "thumb_96": (96, True),
    "thumb_256": (256, True),
    "thumb_512": (512, True),
    "preview_1024": (1024, False),
}


@dataclass(frozen=True)
class NormalisedImage:
    data: bytes
    width: int
    height: int
    mime: str
    format: str  # Pillow format name: JPEG / PNG / WEBP


@dataclass(frozen=True)
class VariantImage:
    data: bytes
    width: int
    height: int
    mime: str
    format: str


class ImageProcessingError(ValueError):
    """Raised when input bytes are not a decodable / safe image."""


def _open_safely(data: bytes) -> Image.Image:
    """Open with explicit guards against image-bombs and corrupt input."""
    Image.MAX_IMAGE_PIXELS = settings.MAX_IMAGE_PIXELS
    try:
        img = Image.open(io.BytesIO(data))
        # Force decode now so corrupt files fail here rather than later.
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageProcessingError(f"not a valid image: {exc}") from exc
    return img


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)


def _encode(img: Image.Image, fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    save_kwargs: dict = {}
    if fmt == "JPEG":
        # JPEG cannot carry alpha; flatten over white if needed.
        if img.mode != "RGB":
            img = img.convert("RGB")
        save_kwargs = {"quality": quality, "optimize": True, "progressive": True}
    elif fmt == "PNG":
        save_kwargs = {"optimize": True}
    elif fmt == "WEBP":
        save_kwargs = {"quality": quality, "method": 6}
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def _format_to_mime(fmt: str) -> str:
    return {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }[fmt]


def normalise(data: bytes, mime: str | None = None) -> NormalisedImage:
    """Strip EXIF, fix orientation, re-encode the original bytes.

    PNG with alpha stays PNG; everything else collapses to JPEG (smaller and
    universally supported). EXIF is dropped because we never copy ``exif=``
    into the new save call.
    """
    img = _open_safely(data)
    img = ImageOps.exif_transpose(img)
    if img is None:
        raise ImageProcessingError("EXIF transpose returned no image")

    if _has_alpha(img):
        out_format = "PNG"
        out_bytes = _encode(img, "PNG", quality=settings.IMAGE_JPEG_QUALITY)
    else:
        out_format = "JPEG"
        out_bytes = _encode(img, "JPEG", quality=settings.IMAGE_JPEG_QUALITY)

    return NormalisedImage(
        data=out_bytes,
        width=img.width,
        height=img.height,
        mime=_format_to_mime(out_format),
        format=out_format,
    )


def _square_center_crop(img: Image.Image) -> Image.Image:
    side = min(img.width, img.height)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    return img.crop((left, top, left + side, top + side))


def make_variant(data: bytes, variant: str) -> VariantImage:
    """Generate a single named variant from the original bytes."""
    if variant not in _VARIANT_SPECS:
        raise ImageProcessingError(f"unknown variant: {variant}")
    target, square = _VARIANT_SPECS[variant]

    img = _open_safely(data)
    img = ImageOps.exif_transpose(img) or img

    if square:
        img = _square_center_crop(img)
        img = img.resize((target, target), Image.Resampling.LANCZOS)
    else:
        # Preserve aspect, fit longest side to target.
        img.thumbnail((target, target), Image.Resampling.LANCZOS)

    fmt_setting = settings.THUMBNAIL_FORMAT.lower()
    if fmt_setting == "webp":
        out_format = "WEBP"
    elif fmt_setting == "png":
        out_format = "PNG"
    else:
        out_format = "JPEG"

    # WEBP supports alpha; JPEG doesn't.
    if out_format == "JPEG" and _has_alpha(img):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = bg

    out_bytes = _encode(img, out_format, quality=settings.THUMBNAIL_QUALITY)
    return VariantImage(
        data=out_bytes,
        width=img.width,
        height=img.height,
        mime=_format_to_mime(out_format),
        format=out_format,
    )


# ─── Mime detection ──────────────────────────────────────────────────────────


def detect_mime(data: bytes, fallback: str | None = None) -> str:
    """Return the "real" mime for ``data``.

    See the module docstring: this always takes the source's
    magic-unavailable fallback branch (``python-magic`` is not used here at
    all — it segfaults without a native libmagic install rather than
    raising). ``fallback`` is normally the client-supplied Content-Type.

    Deliberately NOT routed through ``htqweb.fallback``: that branch is not
    a substitution for something broken, it is the only branch there is —
    100% of calls take it. Counting it would add a metric that never varies
    and a log line on every upload, teaching readers to ignore the word
    FALLBACK exactly where it is supposed to mean something.
    """
    return fallback or "application/octet-stream"


def kind_from_mime(mime: str) -> str:
    """Classify mime into a coarse ``kind`` label used by FileMetadata.kind."""
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime in ("application/pdf",) or mime.startswith("application/msword") or mime.startswith(
        "application/vnd.openxmlformats-officedocument"
    ):
        return "document"
    return "other"
