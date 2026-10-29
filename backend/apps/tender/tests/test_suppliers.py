"""Участники тендера: контакты контрагентов, потенциальные поставщики,
приглашения со ссылкой (T2.2; план этапов 0–2, §4.1–§4.3; мастер-план T-21,
T-26).

Сырой токен ссылки не хранится нигде: в БД — только SHA-256, ссылка
отдаётся один раз (публикация, перевыпуск, приглашение после публикации).
Контрагент приглашается, только если он «Активен» (иначе 422 ``E-TND-02``).
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.tender.models import DeviceBinding, Invitation, SupplierContact
from apps.tender.tests import helpers as h
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

INVITATION_KEYS = {"id", "counterparty_id", "prospect_id", "name", "email", "status",
                   "sent_at", "first_opened_at", "revoked_at", "max_devices",
                   "allowed_actions"}


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    req = h.approved_request(slug)
    with use_company(slug):
        alfa = h.counterparty("100000000001", email="sales@alfa.kz")
        beta = h.counterparty("100000000002", email="", name="ТОО «Бета»")
        blocked = h.counterparty("100000000003", status="blocked", email="b@x.kz")
    tender = h.call("post", "tenders", slug, h.SN, h.tender_body(req)).json()
    h.call("put", f"tenders/{tender['id']}/payment-scheme", slug, h.SN, {"kind": "prepay"})
    return SimpleNamespace(slug=slug, req=req, tender=tender, alfa=alfa, beta=beta,
                           blocked=blocked)


def _invite(world, body, user_id=h.SN):
    return h.call("post", f"tenders/{world.tender['id']}/invitations", world.slug, user_id,
                  body)


def _card(world, user_id=h.SN):
    return h.call("get", f"tenders/{world.tender['id']}", world.slug, user_id).json()


def _publish(world):
    card = _card(world)
    resp = h.call("post", f"tenders/{world.tender['id']}/publish", world.slug, h.SN,
                  {"version": card["version"]})
    assert resp.status_code == 200, resp.content
    return resp.json()


def _token(link: str) -> str:
    assert "/supplier/" in link
    return link.rsplit("/supplier/", 1)[1]


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(set(), *(_keys(v) for v in value))
    return set()


# ── контакты ───────────────────────────────────────────────────────────────

def test_contacts_crud(world):
    base = f"contacts?counterparty_id={world.beta.id}"
    created = h.call("post", "contacts", world.slug, h.SN, {
        "counterparty_id": str(world.beta.id), "email": " Zakup@Beta.KZ ",
        "name": "Айгерим", "phone": "+7 701 000 00 00", "is_primary": True})
    assert created.status_code == 201, created.content
    contact = created.json()
    assert set(contact) == {"id", "counterparty_id", "email", "name", "phone", "is_primary",
                            "is_active"}
    assert contact["email"] == "zakup@beta.kz"
    dup = h.call("post", "contacts", world.slug, h.SN, {
        "counterparty_id": str(world.beta.id), "email": "zakup@beta.kz", "name": "X"})
    assert dup.status_code == 422 and dup.json()["fields"][0]["field"] == "email"
    second = h.call("post", "contacts", world.slug, h.SN, {
        "counterparty_id": str(world.beta.id), "email": "boss@beta.kz", "name": "Ерлан",
        "is_primary": True}).json()
    rows = h.call("get", base, world.slug, h.SN).json()
    assert {r["id"]: r["is_primary"] for r in rows} == {contact["id"]: False,
                                                        second["id"]: True}
    patched = h.call("patch", f"contacts/{contact['id']}", world.slug, h.SN,
                     {"is_active": False})
    assert patched.status_code == 200 and patched.json()["is_active"] is False
    bad = h.call("post", "contacts", world.slug, h.SN, {
        "counterparty_id": str(world.beta.id), "email": "not-an-email", "name": "Y"})
    assert bad.status_code == 422 and bad.json()["fields"][0]["field"] == "email"
    unknown = h.call("post", "contacts", world.slug, h.SN, {
        "counterparty_id": "00000000-0000-0000-0000-000000000009", "email": "a@b.kz",
        "name": "Z"})
    assert unknown.status_code == 422
    assert unknown.json()["fields"][0]["field"] == "counterparty_id"


def test_contacts_rights(world):
    body = {"counterparty_id": str(world.beta.id), "email": "q@beta.kz", "name": "Q"}
    assert h.call("post", "contacts", world.slug, h.FD, body).status_code == 403
    assert h.call("get", "contacts", world.slug, h.FD).status_code == 200
    assert h.call("get", "contacts", world.slug, h.TD).status_code == 403
    contact = h.call("post", "contacts", world.slug, h.SN, body).json()
    # У закупщика нет delete на узле — удаляет администратор модуля.
    assert h.call("delete", f"contacts/{contact['id']}", world.slug, h.SN).status_code == 403
    h.grant(world.slug, 957, "tender-adm")
    assert h.call("delete", f"contacts/{contact['id']}", world.slug, 957).status_code == 200


# ── потенциальные поставщики ───────────────────────────────────────────────

def test_prospects_crud(world):
    created = h.call("post", "prospects", world.slug, h.SN, {
        "name": "ИП Новый поставщик", "email": "New@Supplier.kz", "reg_number": "900101300123"})
    assert created.status_code == 201, created.content
    prospect = created.json()
    assert set(prospect) == {"id", "name", "email", "reg_number", "country_code",
                             "counterparty_id", "version"}
    assert prospect["email"] == "new@supplier.kz" and prospect["country_code"] == "KZ"
    found = h.call("get", "prospects?q=новый", world.slug, h.SN2).json()
    assert [p["id"] for p in found] == [prospect["id"]]
    path = f"prospects/{prospect['id']}"
    assert h.call("get", path, world.slug, h.FD).status_code == 200
    patched = h.call("patch", path, world.slug, h.SN, {"version": 1, "name": "ИП Поставщик"})
    assert patched.status_code == 200 and patched.json()["version"] == 2
    stale = h.call("patch", path, world.slug, h.SN, {"version": 1, "name": "x y z"})
    assert stale.status_code == 409 and stale.json()["code"] == "E-CON-01"
    bad = h.call("post", "prospects", world.slug, h.SN, {"name": "Без почты", "email": ""})
    assert bad.status_code == 422 and bad.json()["fields"][0]["field"] == "email"
    assert h.call("post", "prospects", world.slug, h.FD,
                  {"name": "ФД", "email": "fd@x.kz"}).status_code == 403


def test_counterparty_search_only_active(world):
    rows = h.call("get", "counterparties?q=ТОО", world.slug, h.SN).json()
    assert {r["id"] for r in rows} == {str(world.alfa.id), str(world.beta.id)}
    assert h.call("get", "counterparties?q=ТОО", world.slug, h.SN).status_code == 200


# ── приглашения до публикации ──────────────────────────────────────────────

def test_invite_counterparty_with_card_email(world):
    resp = _invite(world, {"counterparty_id": str(world.alfa.id)})
    assert resp.status_code == 201, resp.content
    inv = resp.json()
    assert set(inv) == INVITATION_KEYS            # ссылки до публикации нет
    assert (inv["email"], inv["status"], inv["max_devices"]) == ("sales@alfa.kz", "created", 1)
    assert inv["name"] == "ТОО «Альфа»"


def test_invite_counterparty_through_contact(world):
    contact = h.call("post", "contacts", world.slug, h.SN, {
        "counterparty_id": str(world.beta.id), "email": "zakup@beta.kz",
        "name": "Айгерим"}).json()
    no_email = _invite(world, {"counterparty_id": str(world.beta.id)})
    assert no_email.status_code == 422 and no_email.json()["code"] == "E-TND-02"
    resp = _invite(world, {"counterparty_id": str(world.beta.id), "contact_id": contact["id"]})
    assert resp.status_code == 201, resp.content
    assert resp.json()["email"] == "zakup@beta.kz"
    foreign = _invite(world, {"counterparty_id": str(world.alfa.id),
                              "contact_id": contact["id"]})
    assert foreign.status_code == 422


def test_blocked_counterparty_is_422(world):
    resp = _invite(world, {"counterparty_id": str(world.blocked.id)})
    assert resp.status_code == 422 and resp.json()["code"] == "E-TND-02"
    unknown = _invite(world, {"counterparty_id": "00000000-0000-0000-0000-000000000009"})
    assert unknown.status_code == 422 and unknown.json()["code"] == "E-TND-02"


def test_same_participant_twice_is_refused(world):
    assert _invite(world, {"counterparty_id": str(world.alfa.id)}).status_code == 201
    again = _invite(world, {"counterparty_id": str(world.alfa.id)})
    assert again.status_code == 422 and again.json()["code"] == "E-TND-02"


def test_invite_prospect(world):
    prospect = h.call("post", "prospects", world.slug, h.SN,
                      {"name": "ИП Новый", "email": "new@s.kz"}).json()
    resp = _invite(world, {"prospect_id": prospect["id"]})
    assert resp.status_code == 201, resp.content
    assert resp.json()["prospect_id"] == prospect["id"]
    assert resp.json()["counterparty_id"] is None
    both = _invite(world, {"prospect_id": prospect["id"],
                           "counterparty_id": str(world.alfa.id)})
    assert both.status_code == 422


def test_only_author_invites(world):
    assert _invite(world, {"counterparty_id": str(world.alfa.id)}, h.FD).status_code == 403
    assert _invite(world, {"counterparty_id": str(world.alfa.id)}, h.SN2).status_code == 404


# ── публикация и ссылки ────────────────────────────────────────────────────

def test_publish_issues_links_and_stores_only_hashes(world):
    first = _invite(world, {"counterparty_id": str(world.alfa.id)}).json()
    prospect = h.call("post", "prospects", world.slug, h.SN,
                      {"name": "ИП Новый", "email": "new@s.kz"}).json()
    second = _invite(world, {"prospect_id": prospect["id"]}).json()
    published = _publish(world)
    links = {row["invitation_id"]: row["link"] for row in published["links"]}
    assert set(links) == {first["id"], second["id"]}
    for link in links.values():
        assert link.startswith("/supplier/")        # PUBLIC_BASE_URL пуст — относительная
    tokens = {inv_id: _token(link) for inv_id, link in links.items()}
    assert len(set(tokens.values())) == 2
    with use_company(world.slug):
        for inv_id, token in tokens.items():
            row = Invitation.objects.get(pk=inv_id)
            assert row.token_hash == _sha(token) and len(row.token_hash) == 64
            assert row.status == "sent" and row.sent_at is not None
            # Сырого токена нет ни в одном столбце приглашения.
            values = Invitation.objects.filter(pk=inv_id).values().get()
            assert token not in json.dumps(values, default=str)

    card = _card(world)
    assert {i["status"] for i in card["invitations"]} == {"sent"}
    assert not {"token", "token_hash", "link", "links", "secret_hash"} & _keys(card)
    for token in tokens.values():
        assert token not in json.dumps(card)
        assert _sha(token) not in json.dumps(card)


def test_link_uses_the_company_host(world, settings):
    settings.PUBLIC_BASE_URL = "https://htq.group"
    _invite(world, {"counterparty_id": str(world.alfa.id)})
    [row] = _publish(world)["links"]
    assert row["link"].startswith(f"https://{world.slug}.htq.group/supplier/")


def test_invitation_after_publish_gets_its_link_at_once(world):
    _invite(world, {"counterparty_id": str(world.alfa.id)})
    _publish(world)
    prospect = h.call("post", "prospects", world.slug, h.SN,
                      {"name": "ИП Поздний", "email": "late@s.kz"}).json()
    resp = _invite(world, {"prospect_id": prospect["id"]})
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["status"] == "sent" and body["link"].startswith("/supplier/")
    with use_company(world.slug):
        assert Invitation.objects.get(pk=body["id"]).token_hash == _sha(_token(body["link"]))
    assert _card(world)["counters"]["sent"] == 2


def test_reissue_replaces_the_hash(world):
    inv = _invite(world, {"counterparty_id": str(world.alfa.id)}).json()
    old = _token(_publish(world)["links"][0]["link"])
    with use_company(world.slug):
        DeviceBinding.objects.create(invitation_id=inv["id"], secret_hash="a" * 64,
                                     user_agent="UA", ip="10.0.0.1")
    path = f"tenders/{world.tender['id']}/invitations/{inv['id']}/reissue"
    resp = h.call("post", path, world.slug, h.SN, {})
    assert resp.status_code == 200, resp.content
    assert set(resp.json()) == {"link"}
    new = _token(resp.json()["link"])
    assert new != old
    with use_company(world.slug):
        row = Invitation.objects.get(pk=inv["id"])
        assert row.token_hash == _sha(new)
        assert not Invitation.objects.filter(token_hash=_sha(old)).exists()
        # Перевыпуск отвязывает устройства: старое занимало бы единственное место.
        assert DeviceBinding.objects.get().revoked_at is not None


def test_reissue_needs_a_published_tender(world):
    inv = _invite(world, {"counterparty_id": str(world.alfa.id)}).json()
    resp = h.call("post", f"tenders/{world.tender['id']}/invitations/{inv['id']}/reissue",
                  world.slug, h.SN, {})
    assert resp.status_code == 409 and resp.json()["code"] == "E-STS-01"


def test_revoke_and_reset_device(world):
    inv = _invite(world, {"counterparty_id": str(world.alfa.id)}).json()
    _publish(world)
    with use_company(world.slug):
        DeviceBinding.objects.create(invitation_id=inv["id"], secret_hash="b" * 64,
                                     user_agent="UA", ip="10.0.0.2")
    base = f"tenders/{world.tender['id']}/invitations/{inv['id']}"
    reset = h.call("post", f"{base}/reset-device", world.slug, h.SN, {})
    assert reset.status_code == 200, reset.content
    with use_company(world.slug):
        assert DeviceBinding.objects.get().revoked_at is not None
    revoked = h.call("post", f"{base}/revoke", world.slug, h.SN, {})
    assert revoked.status_code == 200, revoked.content
    card = _card(world)
    [row] = card["invitations"]
    assert row["status"] == "revoked" and row["revoked_at"]
    assert card["counters"]["sent"] == 0
    again = h.call("post", f"{base}/revoke", world.slug, h.SN, {})
    assert again.status_code == 409
    # Отозванный приглашается заново — новой строкой.
    assert _invite(world, {"counterparty_id": str(world.alfa.id)}).status_code == 201


# ── действия приглашения (T3.7): кнопки и проверка сервера — одна функция ──

def _actions(world, user_id=h.SN) -> dict[str, list[str]]:
    return {row["id"]: row["allowed_actions"] for row in _card(world, user_id)["invitations"]}


def _base(world, inv) -> str:
    return f"tenders/{world.tender['id']}/invitations/{inv['id']}"


def test_draft_invitation_can_only_be_revoked(world):
    inv = _invite(world, {"counterparty_id": str(world.alfa.id)}).json()
    assert inv["allowed_actions"] == ["revoke"]
    assert _actions(world)[inv["id"]] == ["revoke"]


def test_intake_open_gives_all_three(world):
    inv = _invite(world, {"counterparty_id": str(world.alfa.id)}).json()
    _publish(world)
    assert _actions(world)[inv["id"]] == ["revoke", "reissue", "reset_device"]


def test_not_author_sees_no_invitation_actions(world):
    inv = _invite(world, {"counterparty_id": str(world.alfa.id)}).json()
    _publish(world)
    assert _actions(world, h.FD)[inv["id"]] == []


def test_after_deadline_only_revoke_is_left(world):
    """Срок прошёл, статус ещё «Приём»: перевыпуск и сброс бесполезны и
    закрыты, отзыв — как был."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.tender.models import Tender

    inv = _invite(world, {"counterparty_id": str(world.alfa.id)}).json()
    _publish(world)
    with use_company(world.slug):
        Tender.objects.filter(pk=world.tender["id"]).update(
            deadline_at=timezone.now() - timedelta(minutes=1))
    assert _actions(world)[inv["id"]] == ["revoke"]
    for action in ("reissue", "reset-device"):
        resp = h.call("post", f"{_base(world, inv)}/{action}", world.slug, h.SN, {})
        assert (resp.status_code, resp.json()["code"]) == (409, "E-STS-01"), action
    assert h.call("post", f"{_base(world, inv)}/revoke", world.slug, h.SN, {}).status_code == 200


def test_declined_invitation_has_no_actions(world):
    inv = _invite(world, {"counterparty_id": str(world.alfa.id)}).json()
    _publish(world)
    with use_company(world.slug):
        Invitation.objects.filter(pk=inv["id"]).update(status="declined")
    assert _actions(world)[inv["id"]] == []
    for action in ("revoke", "reissue", "reset-device"):
        resp = h.call("post", f"{_base(world, inv)}/{action}", world.slug, h.SN, {})
        assert resp.status_code == 409, (action, resp.content)


def test_invitation_list_and_foreign_invitation(world):
    inv = _invite(world, {"counterparty_id": str(world.alfa.id)}).json()
    rows = h.call("get", f"tenders/{world.tender['id']}/invitations", world.slug, h.FD).json()
    assert [r["id"] for r in rows] == [inv["id"]] and set(rows[0]) == INVITATION_KEYS
    other_req = h.approved_request(world.slug, author=h.SN)
    other = h.call("post", "tenders", world.slug, h.SN, h.tender_body(other_req)).json()
    resp = h.call("post", f"tenders/{other['id']}/invitations/{inv['id']}/revoke",
                  world.slug, h.SN, {})
    assert resp.status_code == 404


def test_contact_model_unique_per_counterparty(world):
    with use_company(world.slug):
        SupplierContact.objects.create(counterparty_id=world.alfa.id, email="a@a.kz", name="A")
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            SupplierContact.objects.create(counterparty_id=world.alfa.id, email="a@a.kz",
                                           name="B")
