"""Conference runtime config endpoint — ``/api/cms/v1/conference/config``.

Reads the static YAML file and normalises the signaling URL against the
current request host (so browsers don't get localhost URLs in production).
Port of Django ``ConferenceConfigView`` from
``backend/mainView/views.py:ConferenceConfigView``.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse, urlunparse

import yaml
from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import TokenPayload, get_current_user
from app.core.logging import get_logger
from app.core.settings import settings
from app.schemas.conference import ConferenceConfig, ConferenceYAMLSource


router = APIRouter(tags=["conference"])
log = get_logger(__name__)


@lru_cache(maxsize=1)
def _load_yaml_cached(path: str) -> ConferenceYAMLSource:
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        log.warning("conference_yaml_missing", path=str(p))
        return ConferenceYAMLSource()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return ConferenceYAMLSource(**raw)


def _load_yaml() -> ConferenceYAMLSource:
    return _load_yaml_cached(settings.conference_config_path)


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


def _resolve_signaling_url(request: Request, source: ConferenceYAMLSource) -> str:
    raw_url = (source.sfu_url or "").strip()
    signaling_path = _normalize_path(source.sfu_path)
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

    request_host = (request.url.hostname or "").strip()
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

    if request.url.scheme in {"https", "wss"} and scheme == "ws":
        scheme = "wss"

    return urlunparse(parsed._replace(scheme=scheme, path=path))


@router.get("/config", response_model=ConferenceConfig)
async def get_conference_config(
    request: Request,
    _user: Annotated[TokenPayload, Depends(get_current_user)],
) -> ConferenceConfig:
    source = _load_yaml()
    return ConferenceConfig(
        sfu_signaling_url=_resolve_signaling_url(request, source),
        sfu_signaling_path=_normalize_path(source.sfu_path),
        ice_servers=source.ice_servers,
    )


def _reset_yaml_cache() -> None:
    """Test helper — clear the YAML cache."""
    _load_yaml_cached.cache_clear()
