"""Тонкая обёртка над Mailcow REST API — порт
``services/email/app/services/mailcow_client.py`` (mailboxes-под-задача,
mail-mailboxes-brief.md).

СИНХРОННЫЙ (``httpx.Client``, а не ``AsyncClient``) — тот же принцип, что и
``apps/mail/services/oauth_clients.py``/``sender/gmail.py`` (Django-вьюхи
этого домена синхронные, в отличие от asyncio FastAPI-исходника). Единственный
живой HTTP-вызов обёрнут в seam-метод ``_request`` — тесты (``tests/
test_mailcow_client.py``) монkeypatch'ят ровно его, БЕЗ живой сети.

Настройки (решение 2 брифа mail-core, тот же принцип для mailboxes):
``htqweb/settings`` трогать нельзя (вне зоны ``backend/apps/mail/**``),
поэтому ``MAILCOW_API_URL``/``MAILCOW_API_KEY`` читаются через
``getattr(django.conf.settings, NAME, "")`` прямо здесь — пустая строка по
умолчанию буквально повторяет исходник (``mailcow_api_url: str = ""``,
``mailcow_api_key: str = ""``): оператор обязан задать реальные значения,
иначе ``mailbox_service.py::create`` отдаёт 500 "MAILCOW_DOMAIN not
configured" (та же логика, что и у исходника).

Mailcow отвечает HTTP 200 с телом ``{"type": "success"/"info"/"danger"/...,
"msg": ...}`` (или списком таких объектов для edit/add/delete) — статус-код
один не говорит ни о чём, поэтому ``_parse`` инспектирует ``type`` буквально
как исходник.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from django.conf import settings

log = logging.getLogger(__name__)


def _configured_domain() -> str:
    """Домен из эффективных настроек (интерфейс поверх env)."""
    from apps.mail.services.mail_config import get_config

    return get_config().domain


class MailcowError(RuntimeError):
    """Raised when Mailcow returns a non-success payload or the call fails."""


class MailcowClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        from apps.mail.services.mail_config import get_config

        cfg = get_config()
        self.base_url = (base_url or cfg.mailcow_api_url).rstrip("/")
        self.api_key = api_key or cfg.mailcow_api_key
        self.timeout = timeout
        if not self.base_url or not self.api_key:
            log.warning("mailcow_client_unconfigured")

    # ── Internal HTTP helpers ─────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, url: str, *, headers: dict[str, str], json: Any = None) -> httpx.Response:
        """Единственный живой сетевой вызов этого модуля — тесты
        монkeypatch'ят ровно этот (bound) метод."""
        with httpx.Client(timeout=self.timeout) as client:
            return client.request(method, url, json=json, headers=headers)

    def _post(self, path: str, payload: Any) -> Any:
        url = f"{self.base_url}{path}"
        resp = self._request("POST", url, headers=self._headers(), json=payload)
        return self._parse(resp, method="POST", path=path)

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        resp = self._request("GET", url, headers=self._headers())
        return self._parse(resp, method="GET", path=path)

    @staticmethod
    def _parse(resp: httpx.Response, *, method: str, path: str) -> Any:
        if resp.status_code >= 500:
            raise MailcowError(f"{method} {path} → HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise MailcowError(f"{method} {path} → invalid JSON: {exc}") from exc

        # GET /get/* returns the entity directly (list or dict). Edit/add/delete
        # endpoints return a list of {type, msg, ...} status objects.
        if isinstance(data, list) and data and isinstance(data[0], dict) and "type" in data[0]:
            for item in data:
                if item.get("type") not in ("success", "info"):
                    raise MailcowError(f"{method} {path} → {item.get('type')}: {item.get('msg')}")
        elif isinstance(data, dict) and "type" in data and data.get("type") not in ("success", "info"):
            raise MailcowError(f"{method} {path} → {data.get('type')}: {data.get('msg')}")
        return data

    # ── Mailbox CRUD ──────────────────────────────────────────────────────

    def create_mailbox(
        self,
        *,
        local_part: str,
        domain: str,
        password: str,
        full_name: str = "",
        quota_mb: int = 1024,
        active: bool = True,
    ) -> Any:
        payload = {
            "local_part": local_part,
            "domain": domain,
            "name": full_name or local_part,
            "quota": str(quota_mb),
            "password": password,
            "password2": password,
            "active": "1" if active else "0",
            "force_pw_update": "0",
            "tls_enforce_in": "1",
            "tls_enforce_out": "1",
        }
        return self._post("/add/mailbox", payload)

    def edit_mailbox(self, address: str, attr: dict[str, Any]) -> Any:
        """Edit one or more fields. `attr` keys are Mailcow native names
        (active, quota, name, password, password2, force_pw_update, ...).
        """
        return self._post("/edit/mailbox", {"items": [address], "attr": attr})

    def set_active(self, address: str, *, active: bool) -> Any:
        return self.edit_mailbox(address, {"active": "1" if active else "0"})

    def reset_password(self, address: str, new_password: str, *, force_change: bool = True) -> Any:
        return self.edit_mailbox(
            address,
            {
                "password": new_password,
                "password2": new_password,
                "force_pw_update": "1" if force_change else "0",
            },
        )

    def delete_mailbox(self, address: str) -> Any:
        return self._post("/delete/mailbox", [address])

    # ── App passwords (Phase 6 — SMTP submission + IMAP IDLE) ─────────────

    def add_app_password(
        self,
        *,
        address: str,
        app_name: str,
        password: str,
        protocols: list[str] | None = None,
    ) -> Any:
        """Create a per-mailbox app-password Mailcow keeps separate from the
        user's interactive password. Returns success/danger payload.

        ``protocols`` defaults to imap+smtp; pass ``["imap_access"]`` if you
        only want the IDLE supervisor to use it.
        """
        protos = protocols or ["imap_access", "smtp_access"]
        attr = {
            "username": address,
            "app_name": app_name,
            "app_passwd": password,
            "app_passwd2": password,
            "active": "1",
        }
        for p in protos:
            attr[p] = "1"
        return self._post("/add/app-passwd", attr)

    def get_mailbox(self, address: str) -> Any:
        return self._get(f"/get/mailbox/{address}")

    def list_mailboxes(self, domain: str | None = None) -> list[dict[str, Any]]:
        domain = domain or _configured_domain()
        data = self._get(f"/get/mailbox/all/{domain}")
        return data if isinstance(data, list) else []

    # ── Aliases ───────────────────────────────────────────────────────────

    def add_alias(self, *, address: str, goto: str, active: bool = True) -> Any:
        """Address that forwards to `goto` (one or more `,`-separated targets)."""
        return self._post(
            "/add/alias",
            {"address": address, "goto": goto, "active": "1" if active else "0"},
        )

    def list_aliases(self, domain: str | None = None) -> list[dict[str, Any]]:
        domain = domain or _configured_domain()
        data = self._get(f"/get/alias/all/{domain}")
        return data if isinstance(data, list) else []

    def delete_alias(self, alias_id: int) -> Any:
        return self._post("/delete/alias", [alias_id])

    # ── Forwarding (mailbox-level "send a copy to ...") ───────────────────

    def set_forwarding(self, address: str, goto: str, *, keep_local_copy: bool = True) -> Any:
        # Mailcow models forwarding as a special alias whose `address` equals
        # the mailbox itself, so it short-circuits delivery there too.
        return self.add_alias(
            address=address,
            goto=f"{address},{goto}" if keep_local_copy else goto,
            active=True,
        )


def get_mailcow_client() -> MailcowClient:
    return MailcowClient()
