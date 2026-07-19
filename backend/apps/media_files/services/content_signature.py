"""Magic-byte content-signature verification — the python-magic substitute.

Why this exists: ``image_service.detect_mime`` doesn't run real mime
detection (``python-magic``'s ``magic.from_buffer`` segfaults the
interpreter on this Windows dev host — no libmagic native DLL, and it
doesn't degrade to a catchable exception), so it always echoes the
client-declared Content-Type back as the "real" mime. For image scopes
that's still safe in practice: ``image_service.normalise()`` runs Pillow's
``Image.open()`` + ``.load()`` on the actual bytes, which genuinely fails
closed on anything that isn't a decodable image. But non-image restricted
scopes (``hr_doc`` → PDF-only) never go through Pillow, so nothing checked
the bytes at all — a caller could POST arbitrary bytes with
``Content-Type: application/pdf`` and have them stored and later served as
a PDF.

This module is the fix: a small, dependency-free check of a handful of
well-known file-signature ("magic number") prefixes. It is deliberately
narrow — only mimes we can identify with a cheap prefix/structure check are
covered. Anything else reports ``UNKNOWN`` rather than guessing, so callers
must not block on it (permissive scopes like ``chat``/``generic`` accept
arbitrary mimes on purpose, and even restricted scopes shouldn't reject a
type we simply have no signature for).

Do NOT reintroduce ``python-magic`` here as a "real" replacement without
first fixing the segfault-on-Windows-host problem — see the docstring in
``image_service.py`` for the full story.
"""

from __future__ import annotations

import enum
from collections.abc import Callable


class SignatureCheck(enum.Enum):
    """Tri-state result of comparing bytes against a declared mime's signature."""

    MATCH = "match"  # bytes start with the known signature for this mime
    MISMATCH = "mismatch"  # bytes do NOT match the known signature — likely spoofed
    UNKNOWN = "unknown"  # no known signature for this mime — do not block on this


def _is_webp(data: bytes) -> bool:
    # RIFF container: bytes 0-3 "RIFF", bytes 4-7 chunk size (ignored), bytes 8-11 "WEBP".
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


_SIGNATURE_CHECKS: dict[str, Callable[[bytes], bool]] = {
    "application/pdf": lambda data: data.startswith(b"%PDF-"),
    "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
    "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/webp": _is_webp,
}


def verify_signature(data: bytes, declared_mime: str) -> SignatureCheck:
    """Compare ``data``'s leading bytes against ``declared_mime``'s known signature.

    Returns ``UNKNOWN`` (never a rejection) for any mime not in the small
    table above — callers must treat ``UNKNOWN`` as "cannot verify, do not
    block", the same as if this function didn't exist for that type.
    """
    check = _SIGNATURE_CHECKS.get(declared_mime)
    if check is None:
        return SignatureCheck.UNKNOWN
    return SignatureCheck.MATCH if check(data) else SignatureCheck.MISMATCH
