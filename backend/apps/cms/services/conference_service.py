"""Conference (SFU) runtime config — ``GET /api/cms/v1/conference/config``.

Ported from ``services/cms/app/api/v1/conference.py`` (FastAPI cms-service):
reads no database, assembles static WebRTC/SFU config from Django settings
(``CONFERENCE_SFU_URL`` / ``CONFERENCE_SFU_PATH`` / ``CONFERENCE_ICE_SERVERS``,
themselves overridable via env — see ``htqweb/settings/base.py``) and
normalises the signaling URL against the current request host so browsers
never get a container-internal or localhost URL when hitting a public host.

Дополнения сверх порта:

* ``enabled`` (Task 1.5) — ``service_enabled("conference")`` из реестра
  ``apps.core``: фронт узнаёт статус сервиса из того же запроса конфига,
  а не только из ``/api/core/v1/services/``. Сервис включён (миграция
  ``core/0003_enable_conference``) — SFU поднят и в dev, и в проде.
* ``wt_signaling_url`` / ``wt_certificate_hashes`` — адрес QUIC-моста
  (``webtransport/``) и отпечатки его самоподписанного сертификата для
  dev. Фронт предпочитает WebTransport, а WebSocket держит запасным.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
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


def _wt_certificate_hashes() -> list[str]:
    """Отпечатки самоподписанного сертификата QUIC-моста (dev).

    Источника два: явный ``CONFERENCE_WT_CERT_HASHES`` (список hex через
    запятую) и файл, который мост пишет при каждом старте
    (``CONFERENCE_WT_CERT_HASH_FILE``, том ``wt_certs``). Файл читаем на
    каждый запрос: сертификат живёт 13 дней и перевыпускается, а конфиг
    фронт запрашивает раз в сессию — кэшировать нечего, а устаревший
    отпечаток сломал бы подключение.
    """
    hashes: list[str] = [
        value.strip()
        for value in settings.CONFERENCE_WT_CERT_HASHES.split(",")
        if value.strip()
    ]

    hash_file = (settings.CONFERENCE_WT_CERT_HASH_FILE or "").strip()
    if hash_file:
        try:
            from_file = Path(hash_file).read_text(encoding="utf-8").strip()
        except OSError:
            # Мост ещё не стартовал или том не смонтирован — не повод
            # ронять конфиг: без хэшей фронт просто уйдёт на WebSocket.
            from_file = ""
        if from_file and from_file not in hashes:
            hashes.append(from_file)

    return hashes


def get_conference_config(request: HttpRequest) -> schemas.ConferenceConfig:
    return schemas.ConferenceConfig(
        sfu_signaling_url=_resolve_signaling_url(
            request, settings.CONFERENCE_SFU_URL, settings.CONFERENCE_SFU_PATH,
        ),
        sfu_signaling_path=_normalize_path(settings.CONFERENCE_SFU_PATH),
        ice_servers=settings.CONFERENCE_ICE_SERVERS,
        enabled=service_enabled("conference"),
        wt_signaling_url=(settings.CONFERENCE_WT_URL or "").strip(),
        wt_certificate_hashes=_wt_certificate_hashes(),
    )
