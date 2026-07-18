"""HMAC-signed URL helper for chat attachments.

Mirrors ``services/media/app/services/signed_url.py``. The browser embeds the
attachment URL in ``<img src>`` / ``<a download>`` where it cannot send an
Authorization header. This signs ``attachment_id|exp`` with a secret so the
redirect endpoint can validate without consulting the database.

The actual file lives in S3; this signature only authorises hitting the
``GET /api/messenger/v1/attachments/file/{id}`` endpoint, which then mints a
short-lived S3 presigned URL.
"""

from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256

from app.core.settings import settings


def _digest(attachment_id: str, exp: int) -> str:
    msg = f"{attachment_id}|{exp}".encode()
    secret = settings.attachment_signed_url_secret.encode()
    raw = hmac.new(secret, msg, sha256).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign(attachment_id: str, ttl: int | None = None) -> tuple[str, int]:
    ttl_seconds = ttl if ttl is not None else settings.attachment_signed_url_ttl
    exp = int(time.time()) + max(1, ttl_seconds)
    return _digest(attachment_id, exp), exp


def verify(attachment_id: str, sig: str, exp: int) -> bool:
    if not sig or not exp:
        return False
    if int(time.time()) >= int(exp):
        return False
    expected = _digest(attachment_id, int(exp))
    return hmac.compare_digest(expected, sig)


def signed_query(attachment_id: str, ttl: int | None = None) -> str:
    sig, exp = sign(attachment_id, ttl)
    return f"sig={sig}&exp={exp}"
