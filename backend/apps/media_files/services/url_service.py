"""Signed-vs-plain URL construction for a ``FileMetadata`` row — the single
implementation of "public file -> plain path, private file -> HMAC-signed
query string" shared by every caller that needs to hand a browser a
fetchable URL.

**Why this module exists (final review of phases 2-3, Finding 3):**
``apps.media_files.interface`` — the public cross-app seam every neighbour
app is required to go through (enforced by
``apps/core/tests/test_app_isolation.py``) — used to import
``_build_file_url`` straight out of ``apps.media_files.views``. That is the
wrong dependency direction: the HTTP layer should depend on services, not
the other way around, and a neighbour importing ``interface.py`` had no
business transitively pulling in Django view machinery. It would also have
caused a real import cycle the moment ``views.py`` needed anything back
from ``interface.py``. Both ``views.py`` (``issue_signed_url``) and
``interface.py`` (``get_file_url``) now import ``build_file_url`` from
here instead — one implementation, imported downward by both.
"""

from __future__ import annotations

import datetime

from django.conf import settings

from htqweb.storage import sign

from apps.media_files.models import FileMetadata


def build_file_url(meta: FileMetadata, variant: str = "original",
                    ttl: int | None = None) -> tuple[str, int]:
    """The signed-vs-plain URL decision, factored out so it has exactly one
    implementation.

    Shared by ``apps.media_files.views.issue_signed_url`` (HTTP ``POST
    .../sign``) and ``apps.media_files.interface.get_file_url`` (the
    cross-app entry point) — both need "public -> plain path, private ->
    HMAC-signed query string", and neither should hand-roll its own signing
    (see ``htqweb.storage.signed_url``'s module docstring: the payload
    layout must stay byte-identical everywhere it's produced). ``ttl=None``
    falls back to ``settings.NEWS_SIGNED_URL_TTL`` (``sign()``'s own
    default) — used by the interface function, which has no per-call
    ``ttl`` query param to read.

    Returns ``(url, exp)`` — ``exp`` is a Unix timestamp (cache-busting hint
    for public files, real expiry for signed ones).
    """
    base = (
        f"/api/media/v1/files/{meta.id}"
        if variant == "original"
        else f"/api/media/v1/files/{meta.id}/{variant}"
    )

    if meta.is_public:
        # No need to sign; expose a far-future exp for cache-busting hint only.
        resolved_ttl = ttl if ttl is not None else settings.NEWS_SIGNED_URL_TTL
        far_future = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + resolved_ttl
        return base, far_future

    resource_id = str(meta.id) if variant == "original" else f"{meta.id}:{variant}"
    sig_value, exp_ts = sign(resource_id, ttl)
    return f"{base}?sig={sig_value}&exp={exp_ts}", exp_ts
