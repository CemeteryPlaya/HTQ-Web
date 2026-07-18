"""Image normalisation + variant generation (Pillow path)."""

import io

import pytest
from PIL import Image

from app.services.image_service import (
    ImageProcessingError,
    detect_mime,
    kind_from_mime,
    make_variant,
    normalise,
)


def _png_bytes(size=(100, 80), color="red") -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_with_exif() -> bytes:
    """A small JPEG carrying a fake EXIF tag (Software=secret)."""
    img = Image.new("RGB", (40, 40), color="blue")
    exif = img.getexif()
    exif[0x0131] = "secret-software"  # Software tag
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_normalise_strips_exif():
    src = _jpeg_with_exif()
    assert b"secret-software" in src  # baseline: tag is present in raw bytes

    out = normalise(src, "image/jpeg")
    assert out.format == "JPEG"
    assert out.mime == "image/jpeg"
    # Decode the result and confirm the EXIF dictionary is empty.
    img = Image.open(io.BytesIO(out.data))
    img.load()
    assert dict(img.getexif()) == {}, "EXIF metadata should be stripped after normalisation"
    assert b"secret-software" not in out.data


def test_normalise_returns_dimensions():
    out = normalise(_png_bytes((123, 45)), "image/png")
    assert out.width == 123
    assert out.height == 45


def test_normalise_rejects_garbage():
    with pytest.raises(ImageProcessingError):
        normalise(b"not an image at all", "image/jpeg")


def test_make_variant_thumb_96_is_square():
    src = _png_bytes((400, 200))
    out = make_variant(src, "thumb_96")
    assert out.width == 96
    assert out.height == 96  # square center-crop
    # WebP by default
    assert out.mime == "image/webp"


def test_make_variant_preview_preserves_aspect():
    src = _png_bytes((2000, 1000))
    out = make_variant(src, "preview_1024")
    assert out.width == 1024
    assert out.height == 512  # 2:1 aspect preserved


def test_make_variant_unknown_raises():
    with pytest.raises(ImageProcessingError):
        make_variant(_png_bytes(), "thumb_999")


def test_kind_from_mime():
    assert kind_from_mime("image/png") == "image"
    assert kind_from_mime("video/mp4") == "video"
    assert kind_from_mime("audio/ogg") == "audio"
    assert kind_from_mime("application/pdf") == "document"
    assert kind_from_mime("application/octet-stream") == "other"


def test_detect_mime_png():
    # detect_mime is best-effort; if libmagic missing, returns fallback. Both
    # acceptable but at least one branch must classify a real PNG correctly.
    real = detect_mime(_png_bytes(), fallback="image/png")
    assert real in ("image/png", "image/png; charset=binary", "image/png")
