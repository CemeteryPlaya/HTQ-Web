"""HMAC-signed URL helper for cms private attachments.

Public assets (cover image) are served via plain presigned URLs since they
land on the public news page. Attachments get this signed redirect so admins
can share them without exposing raw bucket access.
"""

from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256

from app.core.settings import settings


def _digest(resource_id: str, exp: int) -> str:
    msg = f"{resource_id}|{exp}".encode()
    secret = settings.news_signed_url_secret.encode()
    raw = hmac.new(secret, msg, sha256).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign(resource_id: str, ttl: int | None = None) -> tuple[str, int]:
    ttl_seconds = ttl if ttl is not None else settings.news_signed_url_ttl
    exp = int(time.time()) + max(1, ttl_seconds)
    return _digest(resource_id, exp), exp


def verify(resource_id: str, sig: str, exp: int) -> bool:
    if not sig or not exp:
        return False
    if int(time.time()) >= int(exp):
        return False
    expected = _digest(resource_id, int(exp))
    return hmac.compare_digest(expected, sig)


def signed_query(resource_id: str, ttl: int | None = None) -> str:
    sig, exp = sign(resource_id, ttl)
    return f"sig={sig}&exp={exp}"
