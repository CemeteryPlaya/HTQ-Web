"""HMAC-signed URL helper — shared across all Django apps.

Ported byte-for-byte from ``services/cms/app/services/signed_url.py``. The
FastAPI cms-service and this monolith run side by side during the Strangler
Fig transition, so the signature scheme (payload layout, hash algorithm,
encoding, query parameter names) MUST stay identical in both stacks — a URL
signed by one must verify against the other. Do not change the payload
construction, the digest algorithm, or ``sig``/``exp`` naming without also
updating the FastAPI side.

Public assets (e.g. cover images) are served via plain presigned S3 URLs
since they land on a public page. Private assets (e.g. news attachments) get
this signed redirect so admins can share them without exposing raw bucket
access.
"""

from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256

from django.conf import settings


def _digest(resource_id: str, exp: int) -> str:
    msg = f"{resource_id}|{exp}".encode()
    secret = settings.NEWS_SIGNED_URL_SECRET.encode()
    raw = hmac.new(secret, msg, sha256).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign(resource_id: str, ttl: int | None = None) -> tuple[str, int]:
    ttl_seconds = ttl if ttl is not None else settings.NEWS_SIGNED_URL_TTL
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
