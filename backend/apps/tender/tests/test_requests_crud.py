"""Заявка тендерного модуля: модели и CRUD черновика (T1.1; план этапов 0–2,
§3.1, §3.4).

Черновик правит только автор и только в «Черновике» / «На доработке»;
удаляет — только ни разу не отправленный черновик. Реестр — свои заявки, с
узлом ``tender.requests.all`` — все. ПМ подаёт только по проектам-участиям.
Ошибки формы — конверт ``{detail, code, fields: [{field, message}]}`` с
именами полей тела запроса (``items[0].qty``).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from django.db import connection
from django.utils import timezone

from apps.project.models import Project
from apps.tender.models import (
    AuditLog,
    TenderRequest,
    TenderRequestItem,
    TenderRequestPart,
    TenderRequestStatus,
)
from apps.tender.services.core import audit
from apps.tender.tests import helpers as h
from htqweb.tenancy.context import schema_for
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

ROW_KEYS = {"id", "number", "status", "project_id", "purchase_type", "need_date",
            "created_at", "author_name"}


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    proj = h.project("П-101", members=(h.PM,))
    other = h.project("П-102")
    return SimpleNamespace(slug=slug, proj=proj, other=other)


def _create(world, user_id=h.SN, **over):
    data = h.body(over.pop("proj", world.proj), **over)
    return h.call("post", "requests", world.slug, user_id, data)


def _fields(resp) -> list[str]:
    return [f["field"] for f in resp.json().get("fields", [])]


# ── модели ─────────────────────────────────────────────────────────────────

def test_tables_live_in_the_company_schema(world):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name LIKE 'tender_tenderrequest%%'",
            [schema_for(world.slug)])
        found = {row[0] for row in cursor.fetchall()}
    assert found == {"tender_tenderrequest", "tender_tenderrequestpart",
                     "tender_tenderrequestitem"}


# ── создание ───────────────────────────────────────────────────────────────

def test_buyer_creates_a_draft(world):
    resp = _create(world)
    assert resp.status_code == 201, resp.content
    card = resp.json()
    year = timezone.localdate().year
    assert card["number"] == f"ЗТ-{year}-000001"
    assert card["status"] == "draft" and card["version"] == 1
    assert card["initiator_role"] == "sn"
    assert card["project_id"] == str(world.proj.id)
    assert card["allow_partial"] is True and card["allow_analogs"] is False
    assert card["parts"] == []
    assert set(card["allowed_actions"]) == {"save", "submit", "cancel", "delete"}
    [row] = card["items"]
    assert set(row) == {"id", "line_no", "name", "specs", "uom_id", "qty", "plan_price",
                        "need_date", "article_id"}
    assert (row["line_no"], row["name"]) == (1, "Труба 57×3,5")
    assert row["qty"] == "10.000" and row["plan_price"] == "1500.00"
    with use_company(world.slug):
        req = TenderRequest.objects.get(pk=card["id"])
        assert req.author_id == h.SN and req.created_by == h.SN
        assert AuditLog.objects.filter(object_type="tender.tenderrequest",
                                       object_id=card["id"], action="created").exists()


def test_draft_keeps_delivery_and_works_plan(world):
    delivery = h.article("T-DELIV", "Доставка", "supply")
    resp = _create(world, needs_delivery=True, delivery_article_id=str(delivery.id),
                   delivery_plan_amount="25000", needs_works=True, works_scope="Монтаж",
                   works_plan_amount="100000.5", delivery_address="Астана, Нурлы Жол")
    assert resp.status_code == 201, resp.content
    card = resp.json()
    assert card["delivery_plan_amount"] == "25000.00"
    assert card["works_plan_amount"] == "100000.50"
    assert card["delivery_article_id"] == str(delivery.id)
    assert card["delivery_address"] == "Астана, Нурлы Жол"


def test_numbers_go_in_sequence(world):
    first, second = _create(world).json(), _create(world).json()
    assert first["number"][-6:] == "000001" and second["number"][-6:] == "000002"


def test_role_without_create_cannot_create(world):
    for user_id in (h.FD, h.VIEWER, h.TD):
        assert _create(world, user_id).status_code == 403


def test_initiator_role_must_be_held_in_bpp(world):
    h.grant(world.slug, 960, "tender-buyer")          # без ролей БЗО
    resp = _create(world, 960)
    assert resp.status_code == 403 and resp.json()["code"] == "E-ACC-01"
    resp = _create(world, h.SN, role="pm")            # у СН нет роли ПМ
    assert resp.status_code == 403 and resp.json()["code"] == "E-ACC-01"


def test_single_role_is_taken_when_omitted(world):
    data = h.body(world.proj)
    data.pop("initiator_role")
    resp = h.call("post", "requests", world.slug, h.SN, data)
    assert resp.status_code == 201, resp.content
    assert resp.json()["initiator_role"] == "sn"


def test_project_is_required_and_must_be_active(world):
    data = h.body(world.proj)
    data.pop("project_id")
    resp = h.call("post", "requests", world.slug, h.SN, data)
    assert resp.status_code == 422 and _fields(resp) == ["project_id"]

    data["project_id"] = "00000000-0000-0000-0000-000000000001"
    resp = h.call("post", "requests", world.slug, h.SN, data)
    assert resp.status_code == 404 and _fields(resp) == ["project_id"]

    with use_company(world.slug):
        Project.objects.filter(pk=world.other.pk).update(status="closed")
    resp = _create(world, proj=world.other)
    assert resp.status_code == 422 and resp.json()["code"] == "E-PRJ-03"
    assert _fields(resp) == ["project_id"]


def test_pm_files_only_on_member_projects(world):
    resp = _create(world, h.PM, proj=world.other, role="pm",
                   art=h.article("T-DESIGN", "Проектные работы", "pm"))
    assert resp.status_code == 403 and resp.json()["code"] == "E-REQ-05"
    assert _fields(resp) == ["project_id"]
    resp = _create(world, h.PM, role="pm", art=h.article("T-DESIGN", "Проектные работы", "pm"))
    assert resp.status_code == 201, resp.content


@pytest.mark.parametrize("bad,field", [
    ({"name": "ab"}, "items[0].name"),
    ({"name": "x" * 501}, "items[0].name"),
    ({"qty": "0"}, "items[0].qty"),
    ({"qty": "-1"}, "items[0].qty"),
    ({"plan_price": "0"}, "items[0].plan_price"),
    ({"uom_id": "00000000-0000-0000-0000-000000000002"}, "items[0].uom_id"),
    ({"uom_id": None}, "items[0].uom_id"),
    ({"article_id": "00000000-0000-0000-0000-000000000003"}, "items[0].article_id"),
])
def test_item_is_validated(world, bad, field):
    resp = _create(world, items=[h.item(), h.item(**bad)])
    assert resp.status_code == 422, resp.content
    assert _fields(resp) == [field.replace("[0]", "[1]")]


def test_unknown_and_archived_articles_are_refused(world):
    resp = _create(world, article_id="00000000-0000-0000-0000-000000000004")
    assert resp.status_code == 422 and _fields(resp) == ["article_id"]
    old = h.article("T-OLD", "Архивная", "supply")
    old.is_active = False
    old.save(update_fields=["is_active"])
    resp = _create(world, works_article_id=str(old.id))
    assert resp.status_code == 422 and _fields(resp) == ["works_article_id"]


def test_plan_amounts_must_be_positive(world):
    resp = _create(world, delivery_plan_amount="0")
    assert resp.status_code == 422 and _fields(resp) == ["delivery_plan_amount"]
    resp = _create(world, works_plan_amount="-5")
    assert resp.status_code == 422 and _fields(resp) == ["works_plan_amount"]


# ── реестр и карточка ──────────────────────────────────────────────────────

def test_registry_shows_own_requests_and_all_with_the_node(world):
    mine = _create(world).json()
    theirs = _create(world, h.SN2).json()

    rows = h.call("get", "requests", world.slug, h.SN).json()["results"]
    assert [r["id"] for r in rows] == [mine["id"]]
    assert set(rows[0]) >= ROW_KEYS
    assert "Тестов951" in rows[0]["author_name"]

    for user_id in (h.FD, h.VIEWER):          # tender.requests.all
        rows = h.call("get", "requests", world.slug, user_id).json()["results"]
        assert {r["id"] for r in rows} == {mine["id"], theirs["id"]}

    # Проверяющему качество заявки не открыты вовсе (пустая строка на узле).
    assert h.call("get", "requests", world.slug, h.TD).status_code == 403


def test_registry_filters(world):
    a = _create(world).json()
    b = _create(world, proj=world.other,
                items=[h.item("Арматура А500С")]).json()
    with use_company(world.slug):
        TenderRequest.objects.filter(pk=b["id"]).update(status="in_approval")

    def ids(query):
        return {r["id"] for r in
                h.call("get", f"requests?{query}", world.slug, h.SN).json()["results"]}

    assert ids("status=in_approval") == {b["id"]}
    assert ids(f"project_id={world.proj.id}") == {a["id"]}
    assert ids("q=арматура") == {b["id"]}
    assert ids(f"q={a['number']}") == {a["id"]}


def test_card_is_visible_to_author_and_all_viewers_only(world):
    card = _create(world).json()
    path = f"requests/{card['id']}"
    assert h.call("get", path, world.slug, h.SN).status_code == 200
    assert h.call("get", path, world.slug, h.SN2).status_code == 404
    fd = h.call("get", path, world.slug, h.FD)
    assert fd.status_code == 200 and fd.json()["allowed_actions"] == []
    assert h.call("get", "requests/not-a-uuid", world.slug, h.SN).status_code == 404


def test_card_lists_parts(world):
    card = _create(world).json()
    with use_company(world.slug):
        TenderRequestPart.objects.create(
            request_id=card["id"], kind="goods", article_id=h.article().id,
            purchase_type="goods", bpp_number="ЗЗ-2026-000007", bpp_status="in_approval")
    [part] = h.call("get", f"requests/{card['id']}", world.slug, h.SN).json()["parts"]
    assert set(part) == {"id", "kind", "article_id", "purchase_type", "bpp_request_id",
                         "bpp_number", "bpp_status", "excluded_at"}
    assert part["bpp_number"] == "ЗЗ-2026-000007"


# ── правка ─────────────────────────────────────────────────────────────────

def test_author_patches_with_version(world):
    card = _create(world, items=[h.item("Первая"), h.item("Вторая")]).json()
    first, second = card["items"]
    resp = h.call("patch", f"requests/{card['id']}", world.slug, h.SN, {
        "version": 1, "justification": "Новое обоснование потребности",
        "items": [{**h.item("Вторая, правка", qty="3"), "id": second["id"]},
                  h.item("Новая")]})
    assert resp.status_code == 200, resp.content
    patched = resp.json()
    assert patched["version"] == 2
    assert patched["justification"] == "Новое обоснование потребности"
    names = [(i["line_no"], i["name"]) for i in patched["items"]]
    assert names == [(1, "Вторая, правка"), (2, "Новая")]
    assert patched["items"][0]["id"] == second["id"]       # строка та же
    with use_company(world.slug):
        assert not TenderRequestItem.objects.filter(pk=first["id"]).exists()
        assert AuditLog.objects.filter(object_id=card["id"], action="updated").exists()


def test_stale_version_is_409(world):
    card = _create(world).json()
    path = f"requests/{card['id']}"
    assert h.call("patch", path, world.slug, h.SN, {"version": 1,
                                                    "works_scope": "a"}).status_code == 200
    resp = h.call("patch", path, world.slug, h.SN, {"version": 1, "works_scope": "b"})
    assert resp.status_code == 409 and resp.json()["code"] == "E-CON-01"


def test_only_author_patches(world):
    card = _create(world).json()
    resp = h.call("patch", f"requests/{card['id']}", world.slug, h.FD, {"version": 1})
    assert resp.status_code == 403
    resp = h.call("patch", f"requests/{card['id']}", world.slug, h.SN2, {"version": 1})
    assert resp.status_code == 404


@pytest.mark.parametrize("status,code", [
    ("in_approval", 409), ("approved", 409), ("rejected", 409), ("in_tender", 409),
    ("cancelled", 409), ("rework", 200),
])
def test_patch_after_submit_depends_on_status(world, status, code):
    card = _create(world).json()
    with use_company(world.slug):
        TenderRequest.objects.filter(pk=card["id"]).update(status=status)
    resp = h.call("patch", f"requests/{card['id']}", world.slug, h.SN,
                  {"version": 1, "works_scope": "x"})
    assert resp.status_code == code, resp.content
    if code == 409:
        assert resp.json()["code"] == "E-STS-01"


def test_patch_rechecks_the_project_for_pm(world):
    design = h.article("T-DESIGN", "Проектные работы", "pm")
    card = _create(world, h.PM, role="pm", art=design).json()
    resp = h.call("patch", f"requests/{card['id']}", world.slug, h.PM,
                  {"version": 1, "project_id": str(world.other.id)})
    assert resp.status_code == 403 and resp.json()["code"] == "E-REQ-05"


def test_patch_validates_items_like_create(world):
    card = _create(world).json()
    resp = h.call("patch", f"requests/{card['id']}", world.slug, h.SN,
                  {"version": 1, "items": [h.item(qty="0")]})
    assert resp.status_code == 422 and _fields(resp) == ["items[0].qty"]


def test_patch_refuses_the_same_item_twice(world):
    card = _create(world, items=[h.item("Первая"), h.item("Вторая")]).json()
    first = card["items"][0]["id"]
    resp = h.call("patch", f"requests/{card['id']}", world.slug, h.SN, {
        "version": 1,
        "items": [{**h.item("Труба"), "id": first}, {**h.item("Уголок"), "id": first}]})
    assert resp.status_code == 422 and resp.json()["code"] == "E-VAL-01"
    assert _fields(resp) == ["items[1].id"]


# ── удаление ───────────────────────────────────────────────────────────────

def test_author_deletes_a_never_sent_draft(world):
    card = _create(world).json()
    resp = h.call("delete", f"requests/{card['id']}?version=1", world.slug, h.SN)
    assert resp.status_code == 200, resp.content
    with use_company(world.slug):
        assert not TenderRequest.objects.filter(pk=card["id"]).exists()
        assert AuditLog.objects.filter(object_id=card["id"], action="deleted").exists()


def test_delete_checks_version_author_and_history(world):
    card = _create(world).json()
    path = f"requests/{card['id']}"
    resp = h.call("delete", f"{path}?version=7", world.slug, h.SN)
    assert resp.status_code == 409 and resp.json()["code"] == "E-CON-01"
    assert h.call("delete", path, world.slug, h.FD).status_code == 403
    with use_company(world.slug):
        TenderRequest.objects.filter(pk=card["id"]).update(status="rework")
    resp = h.call("delete", path, world.slug, h.SN)
    assert resp.status_code == 409 and resp.json()["code"] == "E-STS-01"
    # Отозванный черновик (части уже были) не удаляется: в БЗО остались ЗЗ.
    with use_company(world.slug):
        TenderRequest.objects.filter(pk=card["id"]).update(status="draft")
        TenderRequestPart.objects.create(request_id=card["id"], kind="goods",
                                         article_id=h.article().id, purchase_type="goods")
    card = h.call("get", path, world.slug, h.SN).json()
    assert "delete" not in card["allowed_actions"]
    resp = h.call("delete", path, world.slug, h.SN)
    assert resp.status_code == 409 and resp.json()["code"] == "E-STS-01"


# ── журнал и действия ──────────────────────────────────────────────────────

def test_history_is_readable_by_those_who_see_the_request(world):
    from django.test import RequestFactory

    from htqweb.authn.jwt import decode_token
    from apps.access.tests.helpers import token

    card = _create(world).json()

    def request_of(user_id):
        req = RequestFactory().get("/")
        req.token = decode_token(token(user_id=user_id, sub=str(user_id), company=world.slug))
        req.company = {"slug": world.slug}
        return req

    with use_company(world.slug):
        assert audit.can_view_history(request_of(h.SN), "tender.tenderrequest", card["id"])
        assert audit.can_view_history(request_of(h.FD), "tender.tenderrequest", card["id"])
        assert not audit.can_view_history(request_of(h.SN2), "tender.tenderrequest",
                                          card["id"])


@pytest.mark.parametrize("status,actions", [
    ("rework", {"save", "submit", "cancel"}),
    ("in_approval", {"withdraw"}),
    ("approved", {"cancel"}),
    ("cancelled", set()),
])
def test_allowed_actions_follow_status(world, status, actions):
    card = _create(world).json()
    with use_company(world.slug):
        TenderRequest.objects.filter(pk=card["id"]).update(status=status)
    got = h.call("get", f"requests/{card['id']}", world.slug, h.SN).json()
    assert set(got["allowed_actions"]) == actions


def test_rejected_part_offers_exclude(world):
    card = _create(world).json()
    with use_company(world.slug):
        TenderRequest.objects.filter(pk=card["id"]).update(
            status=TenderRequestStatus.REJECTED)
        TenderRequestPart.objects.create(request_id=card["id"], kind="goods",
                                         article_id=h.article().id, purchase_type="goods",
                                         bpp_status="rejected")
    got = h.call("get", f"requests/{card['id']}", world.slug, h.SN).json()
    assert "exclude" in got["allowed_actions"] and "cancel" in got["allowed_actions"]


@pytest.mark.parametrize("status", ["cancelled", "closed", "in_tender", "handed_over"])
def test_exclude_is_not_offered_where_the_service_refuses_it(world, status):
    """Кнопка — по тому же условию, что сам переход (``status.excludable_parts``):
    у отменённой заявки отклонённую часть исключить нельзя."""
    card = _create(world).json()
    with use_company(world.slug):
        TenderRequest.objects.filter(pk=card["id"]).update(status=status)
        part = TenderRequestPart.objects.create(
            request_id=card["id"], kind="goods", article_id=h.article().id,
            purchase_type="goods", bpp_status="rejected")
    got = h.call("get", f"requests/{card['id']}", world.slug, h.SN).json()
    assert "exclude" not in got["allowed_actions"]
    refused = h.call("post", f"requests/{card['id']}/parts/{part.id}/exclude", world.slug,
                     h.SN, {"version": got["version"]})
    assert refused.status_code == 409 and refused.json()["code"] == "E-STS-01"


def test_need_date_is_a_date(world):
    card = _create(world).json()
    assert date.fromisoformat(card["need_date"])
