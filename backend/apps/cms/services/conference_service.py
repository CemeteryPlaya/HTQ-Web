"""Conference (SFU) runtime config — ``GET /api/cms/v1/conference/config``.

Ported from ``services/cms/app/api/v1/conference.py`` (FastAPI cms-service):
reads no database, assembles static WebRTC/SFU config from Django settings
(``CONFERENCE_SFU_URL`` / ``CONFERENCE_SFU_PATH`` / ``CONFERENCE_ICE_SERVERS``,
themselves overridable via env — see ``htqweb/settings/base.py``) and
normalises the signaling URL against the current request host so browsers
never get a container-internal or localhost URL when hitting a public host.

The one addition beyond the port (Task 1.5) is ``enabled``: the SFU stack is
deliberately out of service and seeded DISABLED in the ``apps.core`` service
registry, so the response also carries ``service_enabled("conference")`` —
the frontend learns that from the same config fetch it already makes,
instead of only from ``/api/core/v1/services/``.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.http import HttpRequest

from apps.core.services import service_enabled

from .. import schemas


def _is_local_or_private_host(hostname: str) -> bool:
    normalized = (hostname or "").strip().lower()
    if not normalized:
        return True
    if normalized in {"localhost", "::1"} or normalized.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _normalize_path(raw_path: str) -> str:
    path = (raw_path or "/ws/sfu/").strip() or "/ws/sfu/"
    return path if path.startswith("/") else f"/{path}"


def _request_hostname(request: HttpRequest) -> str:
    return (request.get_host() or "").split(":", 1)[0].strip()


def _resolve_signaling_url(request: HttpRequest, raw_sfu_url: str, raw_sfu_path: str) -> str:
    raw_url = (raw_sfu_url or "").strip()
    signaling_path = _normalize_path(raw_sfu_path)
    if not raw_url:
        return ""

    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return ""

    scheme = (parsed.scheme or "").lower()
    if scheme == "http":
        scheme = "ws"
    elif scheme == "https":
        scheme = "wss"
    elif scheme not in {"ws", "wss"}:
        return ""

    request_host = _request_hostname(request)
    target_host = (parsed.hostname or "").strip()
    if (
        target_host
        and not _is_local_or_private_host(request_host)
        and _is_local_or_private_host(target_host)
    ):
        return ""

    path = parsed.path or ""
    if not path or path == "/":
        path = signaling_path

    if request.scheme in {"https", "wss"} and scheme == "ws":
        scheme = "wss"

    return urlunparse(parsed._replace(scheme=scheme, path=path))


def get_conference_config(request: HttpRequest) -> schemas.ConferenceConfig:
    return schemas.ConferenceConfig(
        sfu_signaling_url=_resolve_signaling_url(
            request, settings.CONFERENCE_SFU_URL, settings.CONFERENCE_SFU_PATH,
        ),
        sfu_signaling_path=_normalize_path(settings.CONFERENCE_SFU_PATH),
        ice_servers=settings.CONFERENCE_ICE_SERVERS,
        enabled=service_enabled("conference"),
    )
