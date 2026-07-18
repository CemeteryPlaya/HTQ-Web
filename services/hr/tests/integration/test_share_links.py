"""Integration tests for hashed-token share-links (migration 007)."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.settings import settings
from app.models.shareable_link import ShareableLink, ShareLinkAudit
from tests.conftest import make_admin_token


pytestmark = pytest.mark.asyncio


# ── Helpers ────────────────────────────────────────────────────────────


async def _create(client, body: dict | None = None):
    body = body or {"label": "Test", "link_type": "one_time", "max_level": 3}
    return await client.post("/api/hr/v1/share-links/", json=body, headers=admin_headers())


def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_admin_token(secret=settings.jwt_secret)}"}


async def _audit_actions(session, link_id) -> list[str]:
    rows = (
        await session.execute(
            select(ShareLinkAudit.action)
            .where(ShareLinkAudit.link_id == link_id)
            .order_by(ShareLinkAudit.occurred_at)
        )
    ).all()
    return [r[0] for r in rows]


# ── Tests ──────────────────────────────────────────────────────────────


async def test_create_returns_raw_token_once(client):
    res = await _create(client)
    assert res.status_code == 201, res.text
    body = res.json()
    assert "token" in body and len(body["token"]) >= 32
    assert "url" in body and body["token"] in body["url"]
    assert "id" in body
    # The token MUST also disappear from list/detail responses.


async def test_list_does_not_expose_token(client):
    await _create(client)
    res = await client.get("/api/hr/v1/share-links/", headers=admin_headers())
    assert res.status_code == 200
    items = res.json()
    assert items, "list should not be empty"
    for item in items:
        assert "token" not in item, "raw token must never appear in list"


async def test_create_persists_default_language(client):
    res = await _create(
        client,
        {"label": "English default", "link_type": "one_time", "max_level": 3, "default_language": "en"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["default_language"] == "en"

    listed = await client.get("/api/hr/v1/share-links/", headers=admin_headers())
    assert listed.status_code == 200
    assert listed.json()[0]["default_language"] == "en"


async def test_db_stores_only_hash(client, session):
    res = await _create(client)
    raw = res.json()["token"]
    expected_hash = hashlib.sha256(raw.encode()).hexdigest()

    link = (
        await session.execute(select(ShareableLink).where(ShareableLink.token_hash == expected_hash))
    ).scalar_one()
    assert link.token_hash == expected_hash
    # New rows do not carry the raw token in the legacy column.
    assert link.token is None


async def test_consume_succeeds_via_hash(client):
    raw = (await _create(client)).json()["token"]
    res = await client.get(f"/api/hr/v1/public/org/{raw}")
    assert res.status_code == 200
    body = res.json()
    assert "tree" in body
    assert "watermark" in body


async def test_consume_returns_default_language_and_en_tree(client, monkeypatch):
    async def fake_translate(tree, target_lang):
        assert target_lang == "en"
        return {
            "nodes": [{"id": "translated", "label": "Organization Structure", "type": "department", "meta": {}}],
            "edges": [],
        }

    monkeypatch.setattr(
        "app.services.share_link_service.build_translated_org_tree",
        fake_translate,
    )
    raw = (
        await _create(
            client,
            {"label": "L", "link_type": "one_time", "max_level": 5, "default_language": "en"},
        )
    ).json()["token"]

    res = await client.get(f"/api/hr/v1/public/org/{raw}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["default_language"] == "en"
    assert body["translations"]["en"]["tree"]["nodes"][0]["label"] == "Organization Structure"


async def test_consume_enforces_max_level_in_public_payload(client, monkeypatch):
    async def fake_tree(self, root_id, depth, mode, lang="ru"):
        return {
            "nodes": [
                {
                    "id": "phantom_root",
                    "label": "Board",
                    "type": "position",
                    "level": None,
                    "meta": {"is_phantom": True},
                },
                {
                    "id": "pos_1",
                    "label": "CEO",
                    "type": "position",
                    "level": 9,
                    "meta": {"holder_name": "Jane Doe"},
                }
            ],
            "edges": [
                {"source": "phantom_root", "target": "pos_1", "relation_type": "direct"},
            ],
        }

    monkeypatch.setattr(
        "app.services.share_link_service.OrgService.get_org_tree",
        fake_tree,
    )
    raw = (
        await _create(
            client,
            {"label": "L", "link_type": "one_time", "max_level": 3},
        )
    ).json()["token"]

    res = await client.get(f"/api/hr/v1/public/org/{raw}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [node["id"] for node in body["tree"]["nodes"]] == ["phantom_root"]
    assert body["tree"]["edges"] == []


async def test_consume_unknown_token_404(client):
    res = await client.get("/api/hr/v1/public/org/this-token-does-not-exist")
    assert res.status_code == 404


async def test_one_time_link_second_open_410(client):
    raw = (await _create(client, {"link_type": "one_time", "max_level": 3})).json()["token"]
    first = await client.get(f"/api/hr/v1/public/org/{raw}")
    assert first.status_code == 200
    second = await client.get(f"/api/hr/v1/public/org/{raw}")
    assert second.status_code == 410


async def test_revoke_blocks_consume_410(client):
    created = (await _create(client)).json()
    rev = await client.delete(
        f"/api/hr/v1/share-links/{created['id']}", headers=admin_headers()
    )
    assert rev.status_code == 204
    consumed = await client.get(f"/api/hr/v1/public/org/{created['token']}")
    assert consumed.status_code == 410


async def test_expired_link_410(client, session):
    raw = (await _create(client, {"link_type": "time_limited", "max_level": 3})).json()["token"]
    # Force expiry by mutating the row directly.
    h = hashlib.sha256(raw.encode()).hexdigest()
    link = (
        await session.execute(select(ShareableLink).where(ShareableLink.token_hash == h))
    ).scalar_one()
    link.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await session.commit()

    res = await client.get(f"/api/hr/v1/public/org/{raw}")
    assert res.status_code == 410


async def test_audit_records_open_and_revoke(client, session):
    created = (await _create(client)).json()
    link_id = created["id"]

    # open
    await client.get(f"/api/hr/v1/public/org/{created['token']}")
    # second open denied (one-time)
    await client.get(f"/api/hr/v1/public/org/{created['token']}")

    actions = await _audit_actions(session, link_id)
    assert "created" in actions
    assert "open" in actions
    assert "denied_used" in actions


async def test_audit_endpoint_owner_only(client, session):
    created = (await _create(client)).json()
    res = await client.get(
        f"/api/hr/v1/share-links/{created['id']}/audit", headers=admin_headers()
    )
    assert res.status_code == 200
    entries = res.json()
    assert any(e["action"] == "created" for e in entries)


async def test_audit_endpoint_rejects_non_owner(client):
    created = (await _create(client)).json()
    # Different user_id → not the owner.
    other = {"Authorization": f"Bearer {make_admin_token(user_id=999, secret=settings.jwt_secret)}"}
    res = await client.get(
        f"/api/hr/v1/share-links/{created['id']}/audit", headers=other
    )
    assert res.status_code == 404


async def test_consume_strips_pii_fields(client, session):
    raw = (await _create(client, {"label": "L", "link_type": "one_time", "max_level": 5})).json()["token"]
    res = await client.get(f"/api/hr/v1/public/org/{raw}")
    assert res.status_code == 200, res.text
    body = res.json()
    forbidden = {
        "email",
        "phone",
        "manager_email",
        "manager_phone",
        "salary",
        "iin",
        "birthday",
        "home_address",
    }
    for node in body["tree"]["nodes"]:
        meta = node.get("meta") or {}
        assert not (forbidden & set(meta.keys())), f"PII leak: {forbidden & set(meta.keys())}"


async def test_consume_exposes_holder_contacts_for_public_cards(client, monkeypatch):
    async def fake_tree(self, root_id, depth, mode, lang="ru"):
        return {
            "nodes": [
                {
                    "id": "pos_1",
                    "label": "CEO",
                    "type": "position",
                    "level": 1,
                    "meta": {
                        "holder_name": "Jane Doe",
                        "holder_email": "jane@example.com",
                        "holder_phone": "+7 700 000 00 00",
                        "email": "generic@example.com",
                        "phone": "+7 777 777 77 77",
                        "holders": [
                            {
                                "id": 2,
                                "name": "John Smith",
                                "holder_email": "john@example.com",
                                "holder_phone": "+7 701 000 00 00",
                            }
                        ],
                    },
                }
            ],
            "edges": [],
        }

    monkeypatch.setattr(
        "app.services.share_link_service.OrgService.get_org_tree",
        fake_tree,
    )
    raw = (
        await _create(
            client,
            {"label": "L", "link_type": "one_time", "max_level": 5},
        )
    ).json()["token"]

    res = await client.get(f"/api/hr/v1/public/org/{raw}")
    assert res.status_code == 200, res.text
    meta = res.json()["tree"]["nodes"][0]["meta"]
    assert meta["holder_email"] == "jane@example.com"
    assert meta["holder_phone"] == "+7 700 000 00 00"
    assert "email" not in meta
    assert "phone" not in meta
    assert "holder_email" not in meta["holders"][0]
    assert "holder_phone" not in meta["holders"][0]


async def test_watermark_payload_carries_viewer_label(client):
    raw = (
        await _create(
            client,
            {
                "label": "L",
                "viewer_label": "ТОО Тест",
                "watermark_text": "CONFIDENTIAL",
                "link_type": "one_time",
                "max_level": 3,
            },
        )
    ).json()["token"]
    res = await client.get(f"/api/hr/v1/public/org/{raw}")
    wm = res.json()["watermark"]
    assert wm["viewer_label"] == "ТОО Тест"
    assert wm["text"] == "CONFIDENTIAL"
    assert wm["opened_at"]


async def test_legacy_plaintext_token_still_consumable(client, session):
    """Tokens migrated from before 007 keep the raw column populated; consume
    must still resolve them by hashing the input — the same path as new rows."""
    legacy_raw = "legacy-raw-token-for-test-1234567890abcdef"
    legacy_hash = hashlib.sha256(legacy_raw.encode()).hexdigest()

    link = ShareableLink(
        token=legacy_raw,
        token_hash=legacy_hash,
        created_by_user_id=1,
        label="legacy",
        max_level=3,
        link_type="time_limited",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        is_active=True,
    )
    session.add(link)
    await session.commit()

    res = await client.get(f"/api/hr/v1/public/org/{legacy_raw}")
    assert res.status_code == 200
