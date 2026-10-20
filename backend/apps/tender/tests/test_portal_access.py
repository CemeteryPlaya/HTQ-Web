"""Вход поставщика по ссылке: токен → приглашение, привязка устройства,
Origin/JSON, IP из X-Real-IP, журнал портала (T3.2; план этапа 3, §1, §2 T3.2;
мастер-план T-21…T-26).

Мир собирается прямо в таблицах (заявка, тендер «Приём предложений»,
приглашение с хэшем известного токена): API закупщика проверено своими
тестами, здесь — анонимный контур.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.test import Client, override_settings
from django.utils import timezone

from apps.tender.models import (
    DeviceBinding,
    Invitation,
    PortalEvent,
    Tender,
    TenderRequest,
    TenderRequestItem,
)
from apps.tender.tests import helpers as h
from htqweb.tenancy.db import use_company

BASE = "/api/tender/v1/supplier"
REAL_IP = "10.20.30.40"

#: Ключи, которых в ответе портала быть не должно (план этапа 3, §1).
FORBIDDEN = {"plan_price", "delivery_plan_amount", "works_plan_amount", "budget",
             "invitations", "counters", "token", "token_hash", "secret_hash", "author_id"}
FORBIDDEN_PREFIXES = ("quality_reviewer", "bpp_")


def forbidden_keys(value, path="") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in FORBIDDEN or key.startswith(FORBIDDEN_PREFIXES):
                found.append(f"{path}.{key}")
            found += forbidden_keys(inner, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            found += forbidden_keys(inner, f"{path}[{index}]")
    return found


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _portal_env(settings):
    settings.PUBLIC_BASE_URL = "https://htq.group"
    cache.clear()
    yield
    cache.clear()


def build(slug: str, *, token: str | None = None, status: str = "intake",
          deadline_days: int = 7, max_devices: int = 1) -> SimpleNamespace:
    """Заявка → тендер → приглашение со ссылкой; всё — в схеме ``slug``."""
    token = token or f"tok-{uuid.uuid4().hex}{uuid.uuid4().hex}"
    with use_company(slug):
        n = TenderRequest.objects.count() + 1
        req = TenderRequest.objects.create(
            number=f"ЗТ-2026-{n:06d}", author_id=h.SN, initiator_role="sn",
            project_id=uuid.uuid4(), status="in_tender", delivery_address="Астана, ул. 1",
            need_date=timezone.localdate() + timedelta(days=20),
            needs_works=True, works_scope="Монтаж", works_plan_amount=500000)
        uom = h.pcs()
        TenderRequestItem.objects.create(request=req, line_no=1, name="Лист 10 мм",
                                         uom_id=uom.id, qty=10, plan_price=777)
        tender = Tender.objects.create(
            number=f"ТН-2026-{n:06d}", request=req, author_id=h.SN, status=status,
            deadline_at=timezone.now() + timedelta(days=deadline_days),
            delivery_terms="DAP Астана")
        inv = Invitation.objects.create(
            tender=tender, counterparty_id=uuid.uuid4(), email=f"s{n}@alfa.kz",
            name="ТОО «Альфа»", token_hash=sha(token), status="sent",
            sent_at=timezone.now(), max_devices=max_devices)
    return SimpleNamespace(slug=slug, token=token, req=req, tender=tender, inv=inv)


def origin(slug: str) -> str:
    return f"https://{slug}.htq.group"


def get(client: Client, slug: str, path: str, **extra):
    return client.get(f"{BASE}/{path}", HTTP_X_HTQ_COMPANY=slug, HTTP_X_REAL_IP=REAL_IP,
                      **extra)


def post(client: Client, slug: str, path: str, body=None, *, with_origin: bool = True,
         content_type: str = "application/json", **extra):
    headers = {"HTTP_X_HTQ_COMPANY": slug, "HTTP_X_REAL_IP": REAL_IP, **extra}
    if with_origin:
        headers.setdefault("HTTP_ORIGIN", origin(slug))
    return client.post(f"{BASE}/{path}", data=json.dumps(body or {}),
                       content_type=content_type, **headers)


def cookie_name() -> str:
    from django.conf import settings

    return "tender_device" if settings.TENDER_PORTAL_INSECURE_COOKIE else "__Secure-tender_device"


@pytest.fixture
def world(company_context):
    return build(company_context["slug"])


# ── промежуточная карточка ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_card_reads_and_writes_nothing(world):
    client = Client()
    resp = get(client, world.slug, world.token)
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert set(body) == {"company_name", "tender_number", "deadline_at", "intake_open", "bound"}
    assert body["tender_number"] == world.tender.number
    assert body["intake_open"] is True and body["bound"] is False
    assert body["company_name"] == "Фикстура"
    assert not resp.cookies
    with use_company(world.slug):
        assert not DeviceBinding.objects.exists()
        assert not PortalEvent.objects.exists()
        assert Invitation.objects.get(pk=world.inv.pk).first_opened_at is None


# ── привязка устройства ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bind_sets_the_device_cookie(world):
    client = Client()
    resp = post(client, world.slug, f"{world.token}/bind")
    assert resp.status_code == 200, resp.content
    assert resp.json()["bound"] is True
    morsel = resp.cookies[cookie_name()]
    assert morsel["httponly"] and morsel["samesite"] == "Strict"
    assert morsel["path"] == "/api/tender/v1/supplier/"
    assert int(morsel["max-age"]) > 30 * 24 * 3600          # срок тендера + 30 дней
    secret = morsel.value
    with use_company(world.slug):
        [binding] = DeviceBinding.objects.all()
        assert binding.secret_hash == sha(secret) and binding.ip == REAL_IP
        inv = Invitation.objects.get(pk=world.inv.pk)
        assert inv.status == "opened" and inv.first_opened_at is not None
        [event] = PortalEvent.objects.all()
        assert event.kind == "bound" and event.ip == REAL_IP
        assert secret not in json.dumps(event.meta) and world.token not in json.dumps(event.meta)
    assert get(client, world.slug, world.token).json()["bound"] is True


@pytest.mark.django_db
@override_settings(TENDER_PORTAL_INSECURE_COOKIE=False)
def test_secure_cookie_on_a_real_host(world):
    resp = post(Client(), world.slug, f"{world.token}/bind")
    morsel = resp.cookies["__Secure-tender_device"]
    assert morsel["secure"] and morsel["httponly"] and morsel["samesite"] == "Strict"
    assert "tender_device" not in resp.cookies


@pytest.mark.django_db
def test_same_device_rebinds_to_the_same_binding(world):
    client = Client()
    post(client, world.slug, f"{world.token}/bind")
    again = post(client, world.slug, f"{world.token}/bind")
    assert again.status_code == 200
    with use_company(world.slug):
        assert DeviceBinding.objects.count() == 1


@pytest.mark.django_db
def test_second_device_is_refused(world):
    assert post(Client(), world.slug, f"{world.token}/bind").status_code == 200
    resp = post(Client(), world.slug, f"{world.token}/bind")
    assert resp.status_code == 409 and resp.json()["code"] == "E-TND-06"
    with use_company(world.slug):
        assert DeviceBinding.objects.filter(revoked_at__isnull=True).count() == 1
        assert PortalEvent.objects.filter(kind="bind_refused").count() == 1


@pytest.mark.django_db
def test_two_devices_when_allowed(company_context):
    world = build(company_context["slug"], max_devices=2)
    assert post(Client(), world.slug, f"{world.token}/bind").status_code == 200
    assert post(Client(), world.slug, f"{world.token}/bind").status_code == 200
    assert post(Client(), world.slug, f"{world.token}/bind").status_code == 409


@pytest.mark.django_db
def test_one_cookie_serves_two_invitations(company_context):
    first = build(company_context["slug"])
    second = build(company_context["slug"])
    client = Client()
    assert post(client, first.slug, f"{first.token}/bind").status_code == 200
    assert post(client, second.slug, f"{second.token}/bind").status_code == 200
    assert get(client, first.slug, f"{first.token}/tender").status_code == 200
    assert get(client, second.slug, f"{second.token}/tender").status_code == 200


@pytest.mark.django_db(transaction=True)
def test_parallel_binds_make_one_binding(company_schema):
    world = build(company_schema["slug"])
    codes: list[int] = []
    lock = threading.Lock()

    def worker():
        try:
            resp = post(Client(), world.slug, f"{world.token}/bind")
            with lock:
                codes.append(resp.status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(codes) == [200] + [409] * 5
    with use_company(world.slug):
        assert DeviceBinding.objects.count() == 1


# ── «токен + cookie» ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_tender_needs_the_bound_device(world):
    resp = get(Client(), world.slug, f"{world.token}/tender")
    assert resp.status_code == 403
    assert resp.json()["code"] == "E-TND-06" and resp.json()["details"] == {"rebind": "otp"}
    stranger = Client()
    stranger.cookies[cookie_name()] = "forged-secret-value-forged-secret-value-xx"
    assert get(stranger, world.slug, f"{world.token}/tender").status_code == 403


@pytest.mark.django_db
def test_tender_view_is_a_whitelist(world):
    client = Client()
    bound = post(client, world.slug, f"{world.token}/bind")
    resp = get(client, world.slug, f"{world.token}/tender")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["number"] == world.tender.number and body["customer"] == "Фикстура"
    [item] = body["items"]
    assert set(item) == {"id", "line_no", "name", "specs", "uom", "qty", "need_date"}
    assert item["uom"] == {"code": "pcs", "short_name": "шт"}
    assert body["needs_works"] is True and body["works_scope"] == "Монтаж"
    assert body["intake_open"] is True and body["result"] == "awaiting"
    for payload in (get(client, world.slug, world.token).json(), bound.json(), body):
        assert forbidden_keys(payload) == []
    assert "777" not in json.dumps(body) and "500000" not in json.dumps(body)


@pytest.mark.django_db
def test_dead_links_answer_the_same_404(company_context):
    slug = company_context["slug"]
    live = build(slug)
    revoked = build(slug)
    draft = build(slug, status="draft")
    with use_company(slug):
        Invitation.objects.filter(pk=revoked.inv.pk).update(revoked_at=timezone.now(),
                                                            status="revoked")
    bodies = []
    for token in ("unknown-token-value", revoked.token, draft.token, "x" * 300):
        resp = get(Client(), slug, token)
        assert resp.status_code == 404, token
        bodies.append(resp.content)
    assert len(set(bodies)) == 1
    assert get(Client(), slug, live.token).status_code == 200


@pytest.mark.django_db
def test_reissued_link_is_dead(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    world = build(slug)
    reissue = h.call("post", f"tenders/{world.tender.id}/invitations/{world.inv.id}/reissue",
                     slug, h.SN, {})
    assert reissue.status_code == 200, reissue.content
    new_token = reissue.json()["link"].rsplit("/supplier/", 1)[1]
    assert get(Client(), slug, world.token).status_code == 404
    assert get(Client(), slug, new_token).status_code == 200


@pytest.mark.django_db
def test_token_of_another_company_is_404(two_company_schemas):
    alpha, beta = two_company_schemas
    world = build(alpha)
    assert get(Client(), alpha, world.token).status_code == 200
    assert get(Client(), beta, world.token).status_code == 404


@pytest.mark.django_db
def test_archived_company_is_404(world):
    from apps.companies.models import Company, CompanyStatus

    Company.objects.filter(slug=world.slug).update(status=CompanyStatus.ARCHIVED)
    cache.clear()
    assert get(Client(), world.slug, world.token).status_code == 404


@pytest.mark.django_db
def test_disabled_service_is_503(world):
    from apps.core.models import ServiceStatus

    ServiceStatus.objects.update_or_create(app_label="tender", defaults={"enabled": False})
    cache.clear()
    try:
        assert get(Client(), world.slug, world.token).status_code == 503
    finally:
        ServiceStatus.objects.update_or_create(app_label="tender", defaults={"enabled": True})
        cache.clear()


# ── Origin, тело, IP, лимит ────────────────────────────────────────────────

@pytest.mark.django_db
def test_post_needs_the_company_origin_and_json(world):
    path = f"{world.token}/bind"
    assert post(Client(), world.slug, path, with_origin=False).status_code == 403
    foreign = post(Client(), world.slug, path, HTTP_ORIGIN="https://evil.example")
    assert foreign.status_code == 403 and foreign.json()["code"] == "E-ACC-01"
    other_tenant = post(Client(), world.slug, path, HTTP_ORIGIN="https://other.htq.group")
    assert other_tenant.status_code == 403
    plain = post(Client(), world.slug, path, content_type="text/plain")
    assert plain.status_code == 415
    with use_company(world.slug):
        assert not DeviceBinding.objects.exists()


@pytest.mark.django_db
def test_multipart_only_for_upload(world):
    """``multipart/form-data`` — только у загрузки файла КП; на прочих POST — 415."""
    client = Client()
    bound = post(client, world.slug, f"{world.token}/bind")
    assert bound.status_code == 200, bound.content
    for path in ("bind", "offer/submit", "offer/withdraw", "decline"):
        resp = post(client, world.slug, f"{world.token}/{path}", {"version": 1},
                    content_type="multipart/form-data")
        assert (resp.status_code, resp.json()["code"]) == (415, "E-VAL-02"), (path, resp.content)


def test_forwarded_for_never_reaches_the_journal(world):
    resp = post(Client(), world.slug, f"{world.token}/bind",
                HTTP_X_FORWARDED_FOR="6.6.6.6, 7.7.7.7")
    assert resp.status_code == 200
    with use_company(world.slug):
        event = PortalEvent.objects.get()
        binding = DeviceBinding.objects.get()
    assert event.ip == REAL_IP and binding.ip == REAL_IP
    assert "6.6.6.6" not in json.dumps(event.meta)


@pytest.mark.django_db
def test_bind_rate_limit_is_429(world):
    client = Client()
    for _ in range(10):
        assert post(client, world.slug, f"{world.token}/bind").status_code == 200
    resp = post(client, world.slug, f"{world.token}/bind")
    assert resp.status_code == 429 and resp.json()["code"] == "E-RATE-01"
    assert int(resp["Retry-After"]) >= 1


@pytest.mark.django_db
def test_token_rate_limit_is_429(world, settings):
    settings.TENDER_PORTAL_TOKEN_LIMIT = 3
    client = Client()
    for _ in range(3):
        assert get(client, world.slug, world.token).status_code == 200
    resp = get(client, world.slug, world.token)
    assert resp.status_code == 429 and resp.json()["code"] == "E-RATE-01"


# ── закупщик: сброс устройства и журнал ────────────────────────────────────

@pytest.mark.django_db
def test_reset_device_kills_the_old_cookie(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    world = build(slug)
    client = Client()
    post(client, slug, f"{world.token}/bind")
    assert get(client, slug, f"{world.token}/tender").status_code == 200
    reset = h.call("post", f"tenders/{world.tender.id}/invitations/{world.inv.id}/reset-device",
                   slug, h.SN, {})
    assert reset.status_code == 200, reset.content
    assert get(client, slug, f"{world.token}/tender").status_code == 403
    assert post(Client(), slug, f"{world.token}/bind").status_code == 200   # новое устройство

    events = h.call("get", f"tenders/{world.tender.id}/invitations/{world.inv.id}/events",
                    slug, h.SN)
    assert events.status_code == 200, events.content
    kinds = [row["kind"] for row in events.json()]
    assert kinds == ["bound", "device_reset", "bound"]
    assert set(events.json()[0]) == {"id", "kind", "ip", "user_agent", "meta", "created_at"}
    assert h.call("get", f"tenders/{world.tender.id}/invitations/{world.inv.id}/events",
                  slug, h.SN2).status_code == 404


@pytest.mark.django_db
def test_portal_journal_is_append_only(world):
    post(Client(), world.slug, f"{world.token}/bind")
    with use_company(world.slug):
        event = PortalEvent.objects.get()
        with pytest.raises(DatabaseError), transaction.atomic():
            PortalEvent.objects.filter(pk=event.pk).update(kind="declined")
        with pytest.raises(DatabaseError), transaction.atomic():
            PortalEvent.objects.filter(pk=event.pk).delete()


# ── файлы ТЗ ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_spec_files_are_listed_and_linked(world, memory_storage):  # noqa: F811
    from apps.bpp.tests.test_files import PDF
    from apps.files import interface as files

    h.user(h.SN)
    other = build(world.slug)
    with use_company(world.slug):
        doc = files.attach_bytes("tender.request", world.req.pk, file_type="tender_spec",
                                 data=PDF, filename="tz.pdf", mime="application/pdf",
                                 actor_id=h.SN)
        foreign = files.attach_bytes("tender.request", other.req.pk, file_type="tender_spec",
                                     data=PDF, filename="other.pdf", mime="application/pdf",
                                     actor_id=h.SN)
    client = Client()
    post(client, world.slug, f"{world.token}/bind")
    body = get(client, world.slug, f"{world.token}/tender").json()
    assert body["files"] == [{"id": doc["document_id"], "name": "tz.pdf", "size": len(PDF)}]
    link = get(client, world.slug, f"{world.token}/files/{doc['document_id']}")
    assert link.status_code == 302 and link["Location"]
    assert get(client, world.slug,
               f"{world.token}/files/{foreign['document_id']}").status_code == 404
    assert get(Client(), world.slug,
               f"{world.token}/files/{doc['document_id']}").status_code == 403


from apps.bpp.tests.test_files import memory_storage  # noqa: E402,F401  (фикстура)


# ── ревью T3.2: схема Origin и вложенные секреты в журнале ─────────────────

@pytest.mark.django_db
def test_origin_scheme_must_match_the_root(world, settings):
    """``http://<метка>.<корень>`` при https-корне — чужой источник, даже если
    метка — эта компания (раньше ветка метки схему не сверяла)."""
    settings.DEBUG = False
    path = f"{world.token}/bind"
    plain_http = post(Client(), world.slug, path, HTTP_ORIGIN=f"http://{world.slug}.htq.group")
    assert plain_http.status_code == 403 and plain_http.json()["code"] == "E-ACC-01"
    with_port = post(Client(), world.slug, path,
                     HTTP_ORIGIN=f"http://{world.slug}.htq.group:8443")
    assert with_port.status_code == 403
    https_port = post(Client(), world.slug, path,
                      HTTP_ORIGIN=f"https://{world.slug}.htq.group:443")
    assert https_port.status_code == 200, https_port.content


@pytest.mark.django_db
def test_localhost_origin_only_in_debug(world, settings):
    path = f"{world.token}/bind"
    local = f"http://{world.slug}.localhost:3000"
    settings.DEBUG = False
    assert post(Client(), world.slug, path, HTTP_ORIGIN=local).status_code == 403
    settings.DEBUG = True
    assert post(Client(), world.slug, path, HTTP_ORIGIN=local).status_code == 200


@pytest.mark.django_db
def test_journal_meta_drops_secret_keys_at_any_depth(world):
    from apps.tender.services.portal import access

    with use_company(world.slug):
        event = access.log_event(world.inv, "bound", meta={
            "ok": 1, "cookie": "c",
            "nested": {"token": "t", "keep": "k", "deeper": {"secret_hash": "h", "n": 2}},
            "rows": [{"password": "p", "id": 3}, "plain", ["x", {"Token_Value": "v"}]],
        })
        stored = PortalEvent.objects.get(pk=event.pk).meta
    assert stored == {"ok": 1, "nested": {"keep": "k", "deeper": {"n": 2}},
                      "rows": [{"id": 3}, "plain", ["x", {}]]}
