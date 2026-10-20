"""Отправка заявки тендерного модуля в БЗО (T1.3; план этапов 0–2, §3.2–§3.4;
мастер-план T-03…T-06, T-08).

Заявка режется на части по паре «статья × вид»: основные позиции — по статье,
доставка и СМР — отдельные ЗЗ видом «работы» на свои статьи. Под каждой частью
— ЗЗ в БЗО (``bpp.submit_request_from_tender``), её статус приходит слушателем
в той же транзакции и сворачивается в статус заявки (T-08). Маршрут ЗЗ —
настоящий ``signoff`` «ТД → ОД» из помощников БЗО.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import transaction

from apps.bpp.models import PurchaseRequest
from apps.bpp.tests import stage2 as s
from apps.tender.models import (
    AuditLog,
    TenderRequest,
    TenderRequestItem,
    TenderRequestPart,
)
from apps.tender.tests import helpers as h
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

REASON = "Закупка больше не нужна"


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    proj = h.project("П-101", members=(h.PM,))
    other = h.project("П-102")
    arts = SimpleNamespace(
        metal=h.article("T-METAL", "Металлопрокат"), pipe=h.article("T-PIPE", "Трубы"),
        deliv=h.article("T-DELIV", "Доставка грузов"), smr=h.article("T-SMR", "Монтаж"),
        design=h.article("T-DESIGN", "Проектные работы", "pm"))
    s.approved_budget(slug, proj, {arts.metal: 10_000, arts.pipe: 10_000,
                                   arts.deliv: 10_000, arts.smr: 10_000,
                                   arts.design: 10_000})
    s.request_route()
    return SimpleNamespace(slug=slug, proj=proj, other=other, arts=arts)


def _create(world, *, items=None, user_id=h.SN, **over):
    data = h.body(world.proj, world.arts.metal,
                  items=items if items is not None else [h.item(qty="10", price="100")],
                  **over)
    resp = h.call("post", "requests", world.slug, user_id, data)
    assert resp.status_code == 201, resp.content
    return resp.json()


def _full(world):
    """Две статьи + доставка + СМР."""
    return _create(world, items=[
        h.item("Лист 10 мм", qty="10", price="100"),
        h.item("Уголок 50×50", qty="5", price="100"),
        h.item("Труба 57×3,5", qty="2", price="300", article_id=str(world.arts.pipe.id)),
    ], needs_delivery=True, delivery_article_id=str(world.arts.deliv.id),
        delivery_plan_amount="500", needs_works=True, works_scope="Монтаж каркаса",
        works_article_id=str(world.arts.smr.id), works_plan_amount="700")


def _post(world, card, action, body=None, user_id=h.SN):
    return h.call("post", f"requests/{card['id']}/{action}", world.slug, user_id,
                  {"version": card["version"], **(body or {})})


def _get(world, card, user_id=h.SN):
    resp = h.call("get", f"requests/{card['id']}", world.slug, user_id)
    assert resp.status_code == 200, resp.content
    return resp.json()


def _submit(world, card):
    resp = _post(world, card, "submit")
    assert resp.status_code == 200, resp.content
    return resp.json()


def _part(card, kind, article):
    return next(p for p in card["parts"]
                if p["kind"] == kind and p["article_id"] == str(article.id))


def _zz(world, part) -> PurchaseRequest:
    with use_company(world.slug):
        return PurchaseRequest.objects.get(pk=part["bpp_request_id"])


def _decide(world, part, user_id, decision, comment=""):
    with use_company(world.slug):
        assert s.decide(_zz(world, part), user_id, decision, comment)["ok"]


def _budget(world, article):
    resp = h.call("get", f"requests/budget?project_id={world.proj.id}&article_id={article.id}",
                  world.slug, h.SN)
    assert resp.status_code == 200, resp.content
    return resp.json()


# ── отправка и части (T-03, T-04) ────────────────────────────────────────

def test_two_articles_delivery_and_works_make_four_requests(world):
    assert _budget(world, world.arts.metal)["available"] == "10000.00"
    card = _submit(world, _full(world))

    assert card["status"] == "in_approval"
    assert sorted((p["kind"], p["article_id"]) for p in card["parts"]) == sorted([
        ("goods", str(world.arts.metal.id)), ("goods", str(world.arts.pipe.id)),
        ("delivery", str(world.arts.deliv.id)), ("works", str(world.arts.smr.id))])
    assert {p["bpp_status"] for p in card["parts"]} == {"in_approval"}
    assert all(p["bpp_number"].startswith("ЗЗ-") for p in card["parts"])
    assert set(card["allowed_actions"]) == {"withdraw"}

    with use_company(world.slug):
        rows = {str(r.pk): r for r in PurchaseRequest.objects.all()}
        assert len(rows) == 4
        assert {(r.source, r.tender_number, r.author_id) for r in rows.values()} == {
            ("tender", card["number"], h.SN)}
        delivery = rows[_part(card, "delivery", world.arts.deliv)["bpp_request_id"]]
        works = rows[_part(card, "works", world.arts.smr)["bpp_request_id"]]
        assert delivery.purchase_type == works.purchase_type == "works"
        assert [(i.name, i.qty, i.price) for i in delivery.items.all()] == [
            ("Доставка до объекта", Decimal("1.000"), Decimal("500.00"))]
        assert [(i.name, i.price) for i in works.items.all()] == [
            ("СМР: Монтаж каркаса", Decimal("700.00"))]
        metal = rows[_part(card, "goods", world.arts.metal)["bpp_request_id"]]
        assert metal.total_amount == Decimal("1500.00")
        # Позиции заявки связаны с частью и с позицией ЗЗ — в порядке строк.
        tender_items = list(TenderRequestItem.objects.filter(request_id=card["id"])
                            .order_by("line_no"))
        assert [str(i.bpp_request_item_id) for i in tender_items[:2]] == [
            str(pk) for pk in metal.items.order_by("line_no").values_list("pk", flat=True)]
        assert {str(i.part_id) for i in tender_items[:2]} == {
            _part(card, "goods", world.arts.metal)["id"]}
        assert AuditLog.objects.filter(object_id=card["id"], action="submitted").exists()

    # Резерв ЗЗ уменьшает остаток статьи, который видит форма tender.
    assert _budget(world, world.arts.metal)["available"] == "8500.00"
    assert _budget(world, world.arts.deliv)["available"] == "9500.00"


def test_foreign_group_article_is_refused_in_tender(world):
    card = _create(world, items=[h.item(article_id=str(world.arts.design.id))])
    resp = _post(world, card, "submit")
    assert resp.status_code == 422, resp.content
    assert resp.json()["code"] == "E-REQ-04"
    assert [f["field"] for f in resp.json()["fields"]] == ["items[0].article_id"]
    with use_company(world.slug):
        assert not PurchaseRequest.objects.exists()


def test_required_fields_are_checked_before_bpp(world):
    short = _create(world, justification="Нужно")
    resp = _post(world, short, "submit")
    assert (resp.status_code, resp.json()["code"]) == (422, "E-REQ-01")
    assert [f["field"] for f in resp.json()["fields"]] == ["justification"]

    no_amount = _create(world, needs_delivery=True,
                        delivery_article_id=str(world.arts.deliv.id))
    resp = _post(world, no_amount, "submit")
    assert (resp.status_code, resp.json()["code"]) == (422, "E-REQ-01")
    assert [f["field"] for f in resp.json()["fields"]] == ["delivery_plan_amount"]
    with use_company(world.slug):
        assert not PurchaseRequest.objects.exists()


def test_bpp_error_points_at_its_part_and_rolls_back_everything(world):
    card = _create(world, items=[h.item(qty="1", price="100")], needs_delivery=True,
                   delivery_article_id=str(world.arts.deliv.id),
                   delivery_plan_amount="20000")
    resp = _post(world, card, "submit")
    assert resp.status_code == 422, resp.content
    body = resp.json()
    assert body["code"] == "E-BUD-01"
    pointed = [f for f in body["fields"] if f.get("kind") == "delivery"]
    assert pointed and pointed[0]["field"] == "delivery_plan_amount"
    assert pointed[0]["article_id"] == str(world.arts.deliv.id)
    with use_company(world.slug):
        assert not PurchaseRequest.objects.exists()
        assert not TenderRequestPart.objects.exists()
        assert TenderRequest.objects.get(pk=card["id"]).status == "draft"


# ── свёртка статусов (T-08) — через настоящий маршрут «ТД → ОД» ─────────

def test_td_refusal_is_seen_in_tender_in_the_same_transaction(world):
    card = _submit(world, _create(world, items=[
        h.item(qty="1", price="100"),
        h.item("Труба", qty="1", price="100", article_id=str(world.arts.pipe.id))]))
    metal = _part(card, "goods", world.arts.metal)
    with use_company(world.slug), transaction.atomic():
        assert s.decide(_zz(world, metal), s.TD, "reject", "Металлопрокат не нужен")["ok"]
        # Ещё до коммита решения: зеркало части и свёртка заявки.
        assert TenderRequestPart.objects.get(pk=metal["id"]).bpp_status == "rejected"
        assert TenderRequest.objects.get(pk=card["id"]).status == "rejected"
    after = _get(world, card)
    assert after["status"] == "rejected"
    assert set(after["allowed_actions"]) >= {"cancel", "exclude"}


def test_route_roll_up_rework_and_resubmit(world):
    card = _submit(world, _create(world, items=[h.item(qty="10", price="100")],
                                  needs_delivery=True,
                                  delivery_article_id=str(world.arts.deliv.id),
                                  delivery_plan_amount="500"))
    metal, delivery = (_part(card, "goods", world.arts.metal),
                       _part(card, "delivery", world.arts.deliv))
    _decide(world, delivery, s.TD, "approve")
    _decide(world, delivery, s.OD, "approve")
    card = _get(world, card)
    assert card["status"] == "in_approval"
    assert _part(card, "delivery", world.arts.deliv)["bpp_status"] == "approved"

    _decide(world, metal, s.TD, "rework", "Уточните марку стали")
    card = _get(world, card)
    assert (card["status"], card["rework_comment"]) == ("rework", "Уточните марку стали")

    # Правка утверждённой части (доставка) — E-TND-03.
    patched = h.call("patch", f"requests/{card['id']}", world.slug, h.SN,
                     {"version": card["version"], "delivery_plan_amount": "600"}).json()
    resp = _post(world, patched, "submit")
    assert (resp.status_code, resp.json()["code"]) == (422, "E-TND-03")

    item = patched["items"][0]
    patched = h.call("patch", f"requests/{card['id']}", world.slug, h.SN, {
        "version": patched["version"], "delivery_plan_amount": "500",
        "items": [{**item, "qty": "8"}]}).json()
    card = _submit(world, patched)
    assert card["status"] == "in_approval" and card["rework_comment"] == ""
    again = _part(card, "goods", world.arts.metal)
    assert again["bpp_request_id"] == metal["bpp_request_id"]
    assert _zz(world, again).total_amount == Decimal("800.00")
    assert _part(card, "delivery", world.arts.deliv)["bpp_status"] == "approved"

    _decide(world, again, s.TD, "approve")
    _decide(world, again, s.OD, "approve")
    assert _get(world, card)["status"] == "approved"


def test_items_moved_to_another_article_drop_the_old_part(world):
    card = _submit(world, _create(world))
    metal = _part(card, "goods", world.arts.metal)
    _decide(world, metal, s.TD, "rework", "Это не металлопрокат")
    card = _get(world, card)
    item = card["items"][0]
    card = h.call("patch", f"requests/{card['id']}", world.slug, h.SN, {
        "version": card["version"],
        "items": [{**item, "article_id": str(world.arts.pipe.id)}]}).json()
    card = _submit(world, card)
    assert [(p["kind"], p["article_id"]) for p in card["parts"]] == [
        ("goods", str(world.arts.pipe.id))]
    assert _zz(world, metal).status == "cancelled"
    assert _budget(world, world.arts.metal)["available"] == "10000.00"


# ── отзыв, отмена, исключение части ─────────────────────────────────────

def test_withdraw_returns_to_draft_and_resubmit_reuses_the_requests(world):
    card = _submit(world, _create(world))
    first = _part(card, "goods", world.arts.metal)["bpp_request_id"]
    resp = _post(world, card, "withdraw")
    assert resp.status_code == 200, resp.content
    card = resp.json()
    assert card["status"] == "draft"
    assert {p["bpp_status"] for p in card["parts"]} == {"draft"}
    card = _submit(world, card)
    assert _part(card, "goods", world.arts.metal)["bpp_request_id"] == first


def test_cancel_needs_a_reason_and_releases_the_reserve(world):
    card = _submit(world, _create(world))
    resp = _post(world, card, "cancel", {"comment": REASON})
    assert (resp.status_code, resp.json()["code"]) == (409, "E-STS-01")
    card = _post(world, card, "withdraw").json()
    resp = _post(world, card, "cancel", {"comment": "Не надо"})
    assert resp.status_code == 422
    resp = _post(world, card, "cancel", {"comment": REASON})
    assert resp.status_code == 200, resp.content
    card = resp.json()
    assert (card["status"], card["status_comment"]) == ("cancelled", REASON)
    assert card["allowed_actions"] == []
    assert _zz(world, _part(card, "goods", world.arts.metal)).status == "cancelled"
    assert _budget(world, world.arts.metal)["available"] == "10000.00"


def test_cancel_of_an_approved_request_closes_the_remainder(world):
    card = _submit(world, _create(world))
    metal = _part(card, "goods", world.arts.metal)
    _decide(world, metal, s.TD, "approve")
    _decide(world, metal, s.OD, "approve")
    card = _get(world, card)
    assert card["status"] == "approved"
    card = _post(world, card, "cancel", {"comment": REASON}).json()
    assert card["status"] == "cancelled"
    assert _zz(world, metal).status == "closed"


def test_exclude_a_rejected_part(world):
    card = _submit(world, _create(world, items=[
        h.item(qty="1", price="100"),
        h.item("Труба", qty="1", price="100", article_id=str(world.arts.pipe.id))]))
    metal, pipe = (_part(card, "goods", world.arts.metal),
                   _part(card, "goods", world.arts.pipe))
    resp = _post(world, card, f"parts/{pipe['id']}/exclude")
    assert (resp.status_code, resp.json()["code"]) == (409, "E-STS-01")

    _decide(world, metal, s.TD, "reject", "Металлопрокат не нужен")
    _decide(world, pipe, s.TD, "approve")
    _decide(world, pipe, s.OD, "approve")
    card = _get(world, card)
    assert card["status"] == "rejected"

    resp = _post(world, card, f"parts/{metal['id']}/exclude")
    assert resp.status_code == 200, resp.content
    card = resp.json()
    assert card["status"] == "approved"
    assert _part(card, "goods", world.arts.metal)["excluded_at"]
    assert [i["name"] for i in card["items"]] == ["Труба"]
    assert [i["line_no"] for i in card["items"]] == [1]
    assert "exclude" not in card["allowed_actions"]


# ── подсказки формы ─────────────────────────────────────────────────────

def test_articles_budget_and_projects_for_the_form(world):
    resp = h.call("get", f"requests/articles?project_id={world.proj.id}&role=sn",
                  world.slug, h.SN)
    assert resp.status_code == 200, resp.content
    assert [a["code"] for a in resp.json()] == ["T-DELIV", "T-METAL", "T-PIPE", "T-SMR"]
    assert resp.json()[0]["available"] == "10000.00"

    budget = _budget(world, world.arts.metal)
    assert budget == {"limit": "10000.00", "committed": "0.00", "available": "10000.00",
                      "currency_code": "KZT"}
    resp = h.call("get", f"requests/budget?project_id={world.proj.id}"
                         f"&article_id={world.arts.design.id}", world.slug, h.SN)
    assert (resp.status_code, resp.json()["code"]) == (403, "E-REQ-04")

    sn = h.call("get", "requests/projects?q=П-1", world.slug, h.SN).json()
    pm = h.call("get", "requests/projects?q=П-1", world.slug, h.PM).json()
    assert [p["code"] for p in sn] == ["П-101", "П-102"]
    assert pm == [{"id": str(world.proj.id), "code": "П-101", "name": "Объект П-101"}]

    viewer = h.call("get", "requests/projects", world.slug, h.VIEWER)
    assert viewer.status_code == 403


# ── одно действие — одна версия и одна строка журнала ───────────────────

def _journal(world, card) -> int:
    with use_company(world.slug):
        return AuditLog.objects.filter(object_id=card["id"]).count()


def _step(world, card, action, body=None):
    """Действие пользователя: версия +1 и ровно одна новая строка журнала
    заявки — даже если по дороге слушатель получил статусы ЗЗ."""
    rows = _journal(world, card)
    resp = _post(world, card, action, body)
    assert resp.status_code == 200, resp.content
    after = resp.json()
    assert after["version"] == card["version"] + 1, action
    assert _journal(world, after) == rows + 1, action
    return after


def test_each_action_is_one_version_and_one_journal_row(world):
    card = _create(world, items=[
        h.item(qty="1", price="100"),
        h.item("Труба", qty="1", price="100", article_id=str(world.arts.pipe.id))])
    card = _step(world, card, "submit")
    card = _step(world, card, "withdraw")
    card = _step(world, card, "submit")            # ЗЗ уже есть — пересборка
    metal, pipe = (_part(card, "goods", world.arts.metal),
                   _part(card, "goods", world.arts.pipe))

    _decide(world, metal, s.TD, "reject", "Металлопрокат не нужен")
    _decide(world, pipe, s.TD, "approve")
    _decide(world, pipe, s.OD, "approve")
    card = _get(world, card)                       # решения в БЗО — журнал слушателя
    card = _step(world, card, f"parts/{metal['id']}/exclude")
    assert card["status"] == "approved"
    card = _step(world, card, "cancel", {"comment": REASON})
    assert card["status"] == "cancelled"
    # Исключённая часть в отмену не уходит: её ЗЗ остаётся «Отклонена».
    assert _zz(world, metal).status == "rejected"
    assert _zz(world, pipe).status == "closed"
    with use_company(world.slug):
        actions = list(AuditLog.objects.filter(object_id=card["id"])
                       .order_by("created_at").values_list("action", flat=True))
    assert actions[-2:] == ["part_excluded", "cancelled"]
