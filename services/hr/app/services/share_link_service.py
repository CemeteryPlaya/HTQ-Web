"""ShareLinkService — generate, validate, and consume shareable org links.

Security model:
- Raw token is generated with `secrets.token_urlsafe(32)` (≥256 bits entropy).
- Only SHA-256(token) is stored; the raw token is returned to the caller of
  POST /share-links/ exactly once and never persisted server-side.
- Token validation hashes the incoming URL parameter and looks up by
  `token_hash`. Brute force is infeasible; backups/dumps cannot be replayed.
- Every open / denial / revocation appends a row to `hr_share_link_audit` for
  forensic review.
"""

import copy
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shareable_link import ShareableLink, ShareLinkAudit
from app.services.employee_card_service import EmployeeCardService
from app.services.org_service import OrgService
from app.services.translation_service import build_translated_org_tree

logger = structlog.get_logger()

PII_FIELDS = (
    "email",
    "phone",
    "manager_email",
    "manager_phone",
    "salary",
    "iin",
    "birthday",
    "home_address",
)

NESTED_HOLDER_PII_FIELDS = PII_FIELDS + ("holder_email", "holder_phone")


def _hash_token(raw: str) -> str:
    """SHA-256 hex digest. Deterministic; no salt — token is itself high-entropy."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_raw_token() -> str:
    """43-char URL-safe token with ≥256 bits of entropy."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class CreatedLink:
    """Wraps a freshly created link with its one-shot raw token."""

    link: ShareableLink
    raw_token: str


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if fwd:
        return fwd[:45]
    if request.client:
        return request.client.host[:45]
    return None


def _user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:1024] if ua else None


class ShareLinkService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Authenticated operations ───────────────────────────────────────

    async def create_link(self, user_id: int, data: dict) -> CreatedLink:
        raw = _generate_raw_token()
        target_type = data.get("target_type") or "org"
        target_employee_id = data.get("target_employee_id")
        if target_type == "employee" and not target_employee_id:
            raise HTTPException(
                status_code=422,
                detail="target_employee_id is required when target_type='employee'",
            )
        if target_type == "org":
            target_employee_id = None

        link = ShareableLink(
            token=None,  # plaintext column reserved for legacy rows only
            token_hash=_hash_token(raw),
            created_by_user_id=user_id,
            label=data.get("label"),
            viewer_label=data.get("viewer_label"),
            watermark_text=data.get("watermark_text"),
            max_level=data.get("max_level", 3),
            default_language=data.get("default_language") or "ru",
            visible_units=data.get("visible_units"),
            link_type=data.get("link_type", "one_time"),
            expires_at=data.get("expires_at"),
            target_type=target_type,
            target_employee_id=target_employee_id,
            is_active=True,
        )
        self.session.add(link)
        await self.session.flush()
        await self.session.refresh(link)
        await self._audit(link.id, "created", reason=f"user_id={user_id}")
        logger.info("share_link_created", link_id=str(link.id), user_id=user_id)
        return CreatedLink(link=link, raw_token=raw)

    async def list_links(self, user_id: int) -> list[ShareableLink]:
        stmt = (
            select(ShareableLink)
            .where(ShareableLink.created_by_user_id == user_id)
            .order_by(ShareableLink.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_link(self, link_id: uuid.UUID, user_id: int) -> ShareableLink:
        stmt = select(ShareableLink).where(
            ShareableLink.id == link_id,
            ShareableLink.created_by_user_id == user_id,
        )
        link = (await self.session.execute(stmt)).scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        return link

    async def revoke_link(self, link_id: uuid.UUID, user_id: int) -> None:
        link = await self.get_link(link_id, user_id)
        if not link.is_active:
            return  # idempotent; already revoked or used
        now = datetime.now(timezone.utc)
        link.is_active = False
        link.revoked_at = now
        self.session.add(link)
        await self.session.flush()
        await self._audit(link.id, "revoked", reason=f"user_id={user_id}")
        logger.info("share_link_revoked", link_id=str(link_id))

    async def list_audit(
        self, link_id: uuid.UUID, user_id: int, limit: int = 200
    ) -> list[ShareLinkAudit]:
        # Authorisation: ensure the link belongs to the caller before exposing audit.
        await self.get_link(link_id, user_id)
        stmt = (
            select(ShareLinkAudit)
            .where(ShareLinkAudit.link_id == link_id)
            .order_by(ShareLinkAudit.occurred_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── Public consume ────────────────────────────────────────────────

    async def _resolve_and_validate(
        self, raw_token: str, request: Request, *, expected_target: str | None = None
    ) -> tuple[ShareableLink, str | None, str | None]:
        """Common validation pipeline: lock the row, run all the deny-checks,
        mark as opened/used, and return ``(link, ip, ua)``.

        Raises ``HTTPException`` on every denial reason (revoked / used /
        expired / wrong target type). The caller decides what payload to
        build once it knows the link is good.
        """
        token_hash = _hash_token(raw_token)
        stmt = (
            select(ShareableLink)
            .where(ShareableLink.token_hash == token_hash)
            .with_for_update()
        )
        link = (await self.session.execute(stmt)).scalar_one_or_none()

        ip = _client_ip(request)
        ua = _user_agent(request)

        if not link:
            logger.warning("share_link_unknown_token", ip=ip)
            raise HTTPException(status_code=404, detail="Link not found")

        now = datetime.now(timezone.utc)

        if link.revoked_at is not None:
            await self._audit(link.id, "denied_revoked", ip=ip, ua=ua)
            await self.session.commit()
            raise HTTPException(status_code=410, detail="This link has been revoked")

        if link.link_type == "one_time" and link.used_at is not None:
            await self._audit(link.id, "denied_used", ip=ip, ua=ua)
            await self.session.commit()
            raise HTTPException(
                status_code=410,
                detail="This one-time link has already been used",
            )

        if link.expires_at and link.expires_at < now:
            link.is_active = False
            self.session.add(link)
            await self.session.flush()
            await self._audit(link.id, "denied_expired", ip=ip, ua=ua)
            await self.session.commit()
            raise HTTPException(status_code=410, detail="This link has expired")

        if not link.is_active:
            await self._audit(
                link.id, "denied_revoked", ip=ip, ua=ua, reason="legacy_inactive"
            )
            await self.session.commit()
            raise HTTPException(
                status_code=410, detail="This link is no longer active"
            )

        if expected_target is not None and (link.target_type or "org") != expected_target:
            await self._audit(
                link.id, "denied_revoked", ip=ip, ua=ua, reason="wrong_target_type"
            )
            await self.session.commit()
            raise HTTPException(status_code=404, detail="Link not found")

        link.opened_at = now
        link.opened_by_ip = ip
        if link.link_type == "one_time":
            link.used_at = now
            link.is_active = False
        self.session.add(link)
        await self.session.flush()
        await self._audit(link.id, "open", ip=ip, ua=ua)

        return link, ip, ua

    async def consume_link(self, raw_token: str, request: Request) -> dict:
        """Validate raw_token and return a sanitised org tree.

        For ``one_time`` links: atomically set ``opened_at``+``used_at`` and
        flip ``is_active`` to ``False`` under a row lock so a concurrent open
        cannot succeed twice.
        """
        # Keep the legacy inline pipeline below: it has subtle differences in
        # the post-validation org-tree build vs. the employee variant, so we
        # don't try to share the whole function. The deny-path duplication is
        # intentional — when one branch tightens we want to see the diff.
        token_hash = _hash_token(raw_token)
        stmt = (
            select(ShareableLink)
            .where(ShareableLink.token_hash == token_hash)
            .with_for_update()
        )
        link = (await self.session.execute(stmt)).scalar_one_or_none()

        ip = _client_ip(request)
        ua = _user_agent(request)

        if not link:
            # Don't record an audit row (no link_id to attach to); structlog only.
            logger.warning("share_link_unknown_token", ip=ip)
            raise HTTPException(status_code=404, detail="Link not found")

        now = datetime.now(timezone.utc)

        if link.revoked_at is not None:
            await self._audit(link.id, "denied_revoked", ip=ip, ua=ua)
            await self.session.commit()
            raise HTTPException(status_code=410, detail="This link has been revoked")

        if link.link_type == "one_time" and link.used_at is not None:
            await self._audit(link.id, "denied_used", ip=ip, ua=ua)
            await self.session.commit()
            raise HTTPException(status_code=410, detail="This one-time link has already been used")

        if link.expires_at and link.expires_at < now:
            link.is_active = False
            self.session.add(link)
            await self.session.flush()
            await self._audit(link.id, "denied_expired", ip=ip, ua=ua)
            await self.session.commit()
            raise HTTPException(status_code=410, detail="This link has expired")

        if not link.is_active:
            # Belt-and-braces for legacy rows where is_active=False without a
            # revoked_at/used_at marker. Treat as revoked.
            await self._audit(link.id, "denied_revoked", ip=ip, ua=ua, reason="legacy_inactive")
            await self.session.commit()
            raise HTTPException(status_code=410, detail="This link is no longer active")

        # /public/org/{token} is for org-tree links only; an employee link
        # consumed here would leak the full company. Hide it as 404 to avoid
        # token enumeration probes learning the target type.
        if (link.target_type or "org") != "org":
            await self._audit(
                link.id, "denied_revoked", ip=ip, ua=ua, reason="wrong_target_type"
            )
            await self.session.commit()
            raise HTTPException(status_code=404, detail="Link not found")

        # Mark as opened
        link.opened_at = now
        link.opened_by_ip = ip
        if link.link_type == "one_time":
            link.used_at = now
            link.is_active = False
        self.session.add(link)
        await self.session.flush()
        await self._audit(link.id, "open", ip=ip, ua=ua)

        # Build org tree. We always render in `positions` mode for public
        # consumers — `both`/`employees` would expose extra metadata. We pass
        # a generous `depth` so dept-tree filtering stays open; the per-node
        # `level` filter below is what actually enforces ``link.max_level``.
        org_svc = OrgService(self.session)
        tree = await org_svc.get_org_tree(
            root_id=None,
            depth=20,
            mode="positions",
        )

        # ── Post-filters: enforce link options server-side so a savvy user
        # can't bypass the restriction by hitting the JSON directly.

        # 1. visible_units (departments allow-list)
        if link.visible_units:
            allowed = {str(u) for u in link.visible_units}
            tree["nodes"] = [
                n for n in tree["nodes"]
                if n["type"] != "department" or str(n.get("meta", {}).get("id", "")) in allowed
            ]

        # 2. max_level (position-level cap). Phantom/department nodes have
        # level=None and stay visible. Edges referencing dropped nodes are
        # pruned so the raw public JSON cannot bypass the link restriction.
        if link.max_level:
            kept = [
                n for n in tree["nodes"]
                if n.get("level") is None or n["level"] <= link.max_level
            ]
            visible_ids = {n["id"] for n in kept}
            tree["nodes"] = kept
            tree["edges"] = [
                e for e in tree["edges"]
                if e["source"] in visible_ids and e["target"] in visible_ids
            ]
        # 3. Strip sensitive data — belt-and-braces over the schema-level
        #    filter that already excluded these fields.
        tree = self._strip_public_pii(tree)

        translations: dict[str, dict] = {}
        en_tree = await build_translated_org_tree(tree, "en")
        if en_tree is not None:
            translations["en"] = {"tree": self._strip_public_pii(en_tree)}

        logger.info("share_link_consumed", link_id=str(link.id), ip=ip)

        watermark = self._build_watermark(link, ip=ip, opened_at=now)

        return {
            "label": link.label,
            "max_level": link.max_level,
            "default_language": link.default_language,
            "generated_at": link.created_at.isoformat() if link.created_at else None,
            "watermark": watermark,
            "tree": tree,
            "translations": translations,
        }

    async def consume_employee_link(self, raw_token: str, request: Request) -> dict:
        """Validate raw_token and return a sanitised employee card.

        Mirrors ``consume_link`` but for ``target_type='employee'``. PII
        stripping is handled inside ``EmployeeCardService`` via ``mode='public'``
        so the same logic stays in one place.
        """
        link, ip, _ua = await self._resolve_and_validate(
            raw_token, request, expected_target="employee"
        )
        if not link.target_employee_id:
            raise HTTPException(status_code=404, detail="Link not found")

        card_svc = EmployeeCardService(self.session)
        try:
            card = await card_svc.build_card(link.target_employee_id, mode="public")
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(
                    status_code=410,
                    detail="The employee referenced by this link no longer exists",
                ) from exc
            raise

        now = datetime.now(timezone.utc)
        watermark = self._build_watermark(link, ip=ip, opened_at=now)
        logger.info(
            "share_link_employee_consumed",
            link_id=str(link.id),
            employee_id=link.target_employee_id,
            ip=ip,
        )

        return {
            "label": link.label,
            "default_language": link.default_language,
            "generated_at": link.created_at.isoformat() if link.created_at else None,
            "watermark": watermark,
            "card": card,
        }

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _strip_public_pii(tree: dict) -> dict:
        cleaned = copy.deepcopy(tree)
        for node in cleaned.get("nodes") or []:
            meta = node.get("meta") or {}
            for f in PII_FIELDS:
                meta.pop(f, None)
            # Public links intentionally expose top-level holder_email/
            # holder_phone for visible cards. Nested holders stay summary-only
            # to avoid exposing contacts that are not rendered in the UI.
            if isinstance(meta.get("holders"), list):
                meta["holders"] = [
                    {k: v for k, v in h.items() if k not in NESTED_HOLDER_PII_FIELDS}
                    for h in meta["holders"]
                    if isinstance(h, dict)
                ]
            node["meta"] = meta
        return cleaned

    async def _audit(
        self,
        link_id: uuid.UUID,
        action: str,
        *,
        ip: str | None = None,
        ua: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.session.add(
            ShareLinkAudit(
                link_id=link_id,
                action=action,
                ip=ip,
                user_agent=ua,
                reason=reason,
            )
        )
        await self.session.flush()

    @staticmethod
    def _build_watermark(
        link: ShareableLink, *, ip: str | None, opened_at: datetime
    ) -> dict:
        """Frontend renders this as a CSS overlay over the chart."""
        ip_tail = ""
        if ip:
            parts = ip.split(".")
            ip_tail = parts[-1] if len(parts) == 4 else ip[-4:]
        return {
            "viewer_label": link.viewer_label,
            "text": link.watermark_text,
            "opened_at": opened_at.isoformat(),
            "ip_tail": ip_tail,
        }
