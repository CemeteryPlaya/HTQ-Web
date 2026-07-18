"""Thin wrapper around the Mailcow REST API.

Mailcow's API is HTTP+JSON with an X-API-Key header. Most "edit" endpoints
take a payload of {"items": [<id>], "attr": {...}} — kind of awkward, so this
client hides that shape from callers.

Docs: https://mailcow.github.io/mailcow-dockerized-docs/api/

Errors:
    Mailcow returns HTTP 200 with a JSON body of either:
        {"type": "success", "msg": "...", ...}
        {"type": "danger",  "msg": "...", ...}
    so we cannot rely on status codes alone — every method inspects `type`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from app.core.settings import settings


log = structlog.get_logger(__name__)


class MailcowError(RuntimeError):
    """Raised when Mailcow returns a non-success payload or the call fails."""


class MailcowClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = (base_url or settings.mailcow_api_url).rstrip("/")
        self.api_key = api_key or settings.mailcow_api_key
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

    async def _post(self, path: str, payload: Any) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
        return self._parse(resp, method="POST", path=path)

    async def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._headers())
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

    async def create_mailbox(
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
        return await self._post("/add/mailbox", payload)

    async def edit_mailbox(self, address: str, attr: dict[str, Any]) -> Any:
        """Edit one or more fields. `attr` keys are Mailcow native names
        (active, quota, name, password, password2, force_pw_update, ...).
        """
        return await self._post("/edit/mailbox", {"items": [address], "attr": attr})

    async def set_active(self, address: str, *, active: bool) -> Any:
        return await self.edit_mailbox(address, {"active": "1" if active else "0"})

    async def reset_password(self, address: str, new_password: str, *, force_change: bool = True) -> Any:
        return await self.edit_mailbox(
            address,
            {
                "password": new_password,
                "password2": new_password,
                "force_pw_update": "1" if force_change else "0",
            },
        )

    async def delete_mailbox(self, address: str) -> Any:
        return await self._post("/delete/mailbox", [address])

    # ── App passwords (Phase 6 — SMTP submission + IMAP IDLE) ─────────────

    async def add_app_password(
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
        return await self._post("/add/app-passwd", attr)

    async def get_mailbox(self, address: str) -> Any:
        return await self._get(f"/get/mailbox/{address}")

    async def list_mailboxes(self, domain: str | None = None) -> list[dict[str, Any]]:
        domain = domain or settings.mailcow_domain
        data = await self._get(f"/get/mailbox/all/{domain}")
        return data if isinstance(data, list) else []

    # ── Aliases ───────────────────────────────────────────────────────────

    async def add_alias(self, *, address: str, goto: str, active: bool = True) -> Any:
        """Address that forwards to `goto` (one or more `,`-separated targets)."""
        return await self._post(
            "/add/alias",
            {"address": address, "goto": goto, "active": "1" if active else "0"},
        )

    async def list_aliases(self, domain: str | None = None) -> list[dict[str, Any]]:
        domain = domain or settings.mailcow_domain
        data = await self._get(f"/get/alias/all/{domain}")
        return data if isinstance(data, list) else []

    async def delete_alias(self, alias_id: int) -> Any:
        return await self._post("/delete/alias", [alias_id])

    # ── Forwarding (mailbox-level "send a copy to ...") ───────────────────

    async def set_forwarding(self, address: str, goto: str, *, keep_local_copy: bool = True) -> Any:
        # Mailcow models forwarding as a special alias goto_null/goto_spam,
        # but for "deliver here AND forward" we use the mailbox-level
        # `/edit/user-acl` is read-only; the standard pattern is an alias
        # with `address == mailbox` so it short-circuits.
        return await self.add_alias(
            address=address,
            goto=f"{address},{goto}" if keep_local_copy else goto,
            active=True,
        )


def get_mailcow_client() -> MailcowClient:
    return MailcowClient()


# Sync helper for use inside Dramatiq actors (which don't run an event loop).
def run_sync(coro):
    return asyncio.run(coro)
