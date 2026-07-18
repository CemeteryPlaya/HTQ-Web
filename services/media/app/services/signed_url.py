"""HMAC-signed URL helper for serving private media via plain ``<img src>``.

A signed URL embeds an expiring HMAC over ``file_id|variant|exp`` so the
browser can fetch a private file without an Authorization header. This
unblocks chat attachments and HR documents which need to render in
``<img>`` / ``<a download>`` elements.

Public files (avatar, news) bypass this entirely — they're served openly
and cached at the nginx layer.
"""

from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256

from app.core.settings import settings


def _digest(file_id: str, variant: str, exp: int) -> str:
    msg = f"{file_id}|{variant}|{exp}".encode()
    secret = settings.media_signed_url_secret.encode()
    raw = hmac.new(secret, msg, sha256).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign(file_id: str, variant: str = "original", ttl: int | None = None) -> tuple[str, int]:
    """Return ``(sig, exp_unix_seconds)`` for the given file/variant."""
    ttl_seconds = ttl if ttl is not None else settings.media_signed_url_ttl
    exp = int(time.time()) + max(1, ttl_seconds)
    return _digest(file_id, variant, exp), exp


def verify(file_id: str, variant: str, sig: str, exp: int) -> bool:
    """Constant-time signature check; rejects anything past ``exp``."""
    if not sig or not exp:
        return False
    if int(time.time()) >= int(exp):
        return False
    expected = _digest(file_id, variant, int(exp))
    return hmac.compare_digest(expected, sig)


def signed_query(file_id: str, variant: str = "original", ttl: int | None = None) -> str:
    """Render the ``?sig=...&exp=...`` suffix to append to a media URL."""
    sig, exp = sign(file_id, variant, ttl)
    return f"sig={sig}&exp={exp}"
