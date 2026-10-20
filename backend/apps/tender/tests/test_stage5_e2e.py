"""Сквозной сценарий этапа 5: от заявки до «Закрыт» (T5.6; спека этапа 5,
§3 T5.6) — без заглушек БЗО.

Заявка закупщика (две позиции металла, доставка, СМР) уходит в БЗО четырьмя
ЗЗ по маршруту «ТД → ОД»; тендер с двумя контрагентами (A — аванс 30 %, B —
предоплата), предложения подаются сервисом портала, вскрытие, выбор по
позициям, доставке и СМР, утверждение «Проверка качества → ФД» настоящим
маршрутом ``tender.award``. Передача создаёт настоящие документы БЗО: у A —
договор (товар выше 1000 МРП) и счёт на СМР, у B — счета на товар и доставку.
Дальше — штатные сервисы БЗО: отправка, «Оплатить» ФД, отметки БУХ (у A —
аванс 30 % до отгрузки), приёмка в тендере, сканы приёмки уходят на счёт,
когда БУХ запросил закрывающие, «Документы вложены» автора, приём БУХ.
Последний закрытый счёт — тендер и заявка «Закрыт».

Счёт по договору из тендера оформляется в БЗО (ТЗ §9.4) и своего ключа
передачи не имеет — тендер всё равно ведёт по нему поставку: сканы и
закрытие идут через ключ договора (``bpp.tender_documents.TENDER_INVOICE``).
Этот счёт закрывается последним — проверка, что слушатель его слышит.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.bpp.models import Agreement, Invoice, InvoiceStatus, PurchaseRequest
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.invoices import decisions, payments
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)
from apps.bpp.tests.test_invoices import BUH, GD, _attach, _counterparty, _routes
from apps.files import interface as files
from apps.signoff import interface as signoff
from apps.tender.models import TenderRequest, TenderRequestItem
from apps.tender.tests import helpers as h
from apps.tender.tests.stage5 import _lines, send
from apps.tender.tests.test_award_signoff import decide, route, td_position
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

#: (позиция, кол-во, плановая цена) — швеллер у A выше 1000 МРП 2026 года
#: (4 325 000 — договор).
ITEMS = (("Швеллер 12П", "10", "480000"), ("Уголок 50×5", "4", "100000"))
DELIVERY_PLAN, WORKS_PLAN = "300000", "1200000"


@pytest.fixture
def world(company_context, memory_storage):  # noqa: F811
    slug = company_context["slug"]
    h.staff(slug)
    with use_company(slug):
        proj = h.project("П-501", members=(h.PM,))
        arts = SimpleNamespace(metal=h.article("T-METAL", "Металлопрокат"),
                               deliv=h.article("T-DELIV", "Доставка грузов"),
                               smr=h.article("T-SMR", "Монтаж"))
        s.approved_budget(slug, proj, {arts.metal: 10_000_000, arts.deliv: 1_000_000,
                                       arts.smr: 5_000_000})
        s.request_route()                  # ЗЗ: ТД → ОД
        _routes()                          # счёт: ФД; договор: ФД → ГД
        route()                            # выбор поставщиков: проверка качества → ФД
        td_position()
        cps = {"A": _counterparty("100000000501", name="ТОО «Металл А»", email="a@metall.kz"),
               "B": _counterparty("100000000502", name="ТОО «Снаб Б»", email="b@snab.kz")}
    return SimpleNamespace(slug=slug, proj=proj, arts=arts, cps=cps,
                           sn=s.actor(slug, h.SN, "tender-buyer", "bpp-sn"),
                           fd=s.actor(slug, s.FD, "bpp-fd"), buh=s.actor(slug, BUH, "bpp-buh"))


def ok(resp, status: int = 200) -> dict:
    assert resp.status_code == status, resp.content
    return resp.json()


def tender_get(world, suffix: str = "") -> dict:
    return ok(h.call("get", f"tenders/{world.tender_id}{suffix}", world.slug, h.SN))


def version(world) -> int:
    return tender_get(world)["version"]


def tender_post(world, action: str, body=None, status: int = 200) -> dict:
    return ok(h.call("post", f"tenders/{world.tender_id}/{action}", world.slug, h.SN,
                     body if body is not None else {"version": version(world)}), status)


def stages(world) -> dict[str, str]:
    rows = tender_get(world, "/delivery")["suppliers"]
    return {world.key_of[r["invitation_id"]]: r["stage"] for r in rows}


# ── 1. заявка → четыре ЗЗ, утверждены ───────────────────────────────────

def _request(world) -> dict:
    items = [h.item(name, qty=qty, price=price, article_id=str(world.arts.metal.id))
             for name, qty, price in ITEMS]
    card = ok(h.call("post", "requests", world.slug, h.SN, h.body(
        world.proj, world.arts.metal, items=items, needs_delivery=True,
        delivery_article_id=str(world.arts.deliv.id), delivery_plan_amount=DELIVERY_PLAN,
        needs_works=True, works_scope="Монтаж металлокаркаса",
        works_article_id=str(world.arts.smr.id), works_plan_amount=WORKS_PLAN)), 201)
    card = ok(h.call("post", f"requests/{card['id']}/submit", world.slug, h.SN,
                     {"version": card["version"]}))
    assert sorted(p["kind"] for p in card["parts"]) == ["delivery", "goods", "works"]
    with use_company(world.slug):
        for part in card["parts"]:
            zz = PurchaseRequest.objects.get(pk=part["bpp_request_id"])
            assert s.decide(zz, s.TD, "approve")["ok"]
            assert s.decide(zz, s.OD, "approve")["ok"]
        assert TenderRequest.objects.get(pk=card["id"]).status == "approved"
    return card


# ── 2. тендер: участники, предложения, вскрытие ─────────────────────────

def _tender(world, req: dict) -> None:
    card = ok(h.call("post", "tenders", world.slug, h.SN,
                     {"request_id": req["id"], "deadline_at": h.future(),
                      "currency_code": "KZT", "delivery_terms": "DAP Астана"}), 201)
    world.tender_id = card["id"]
    ok(h.call("put", f"tenders/{card['id']}/payment-scheme", world.slug, h.SN,
              {"kind": "advance", "advance_pct": "30"}))
    inv = {}
    for key, cp in world.cps.items():
        inv[key] = ok(h.call("post", f"tenders/{card['id']}/invitations", world.slug, h.SN,
                             {"counterparty_id": str(cp.pk)}), 201)["id"]
    tender_post(world, "publish")
    world.inv = inv
    world.key_of = {v: k for k, v in inv.items()}

    valid = timezone.localdate() + timedelta(days=45)
    with use_company(world.slug):
        from apps.tender.models import Invitation, Tender

        items = list(TenderRequestItem.objects.filter(request_id=req["id"]).order_by("line_no"))
        send(Invitation.objects.get(pk=inv["A"]), {
            "currency_code": "KZT", "with_vat": False, "valid_until": valid,
            "lines": _lines(items, [("450000", None, ""), ("95000", None, "")]),
            "extras": {"delivery": {"amount": "260000", "included_in_price": False},
                       "works": {"amount": "1100000", "included_in_price": False}},
            "payment_scheme": {"kind": "advance", "advance_pct": "30"}})
        send(Invitation.objects.get(pk=inv["B"]), {
            "currency_code": "KZT", "with_vat": False, "valid_until": valid,
            "lines": _lines(items, [(None, None, ""), ("90000", None, "")]),
            "extras": {"delivery": {"amount": "250000", "included_in_price": False},
                       "works": {"amount": "1150000", "included_in_price": False}},
            "payment_scheme": {"kind": "prepay"}})
        Tender.objects.filter(pk=world.tender_id).update(
            deadline_at=timezone.now() - timedelta(hours=1))
    assert tender_post(world, "open")["status"] == "opened"


# ── 3. выбор, утверждение, передача в БЗО ───────────────────────────────

def _award(world) -> None:
    table = tender_get(world, "/comparison")
    item1, item2 = table["items"]
    extra = {row["kind"]: row for row in table["extras"]}
    a, b = world.inv["A"], world.inv["B"]
    assert (item1["cheapest_invitation_id"], item2["cheapest_invitation_id"]) == (a, b)
    ok(h.call("put", f"tenders/{world.tender_id}/award", world.slug, h.SN, {
        "version": version(world), "comment": "",
        "lines": [{"line_id": item1["offers"][a]["line_id"]},
                  {"line_id": item2["offers"][b]["line_id"]}],
        "extras": [{"extra_id": extra["delivery"]["offers"][b]["extra_id"]},
                   {"extra_id": extra["works"]["offers"][a]["extra_id"]}]}))
    tender_post(world, "award/submit")
    ns = SimpleNamespace(slug=world.slug, tender=SimpleNamespace(pk=world.tender_id))
    decide(ns, h.TD, "approve")                # проверка качества — ТД по должности
    decide(ns, h.FD, "approve")
    assert tender_get(world)["status"] == "awarded"


def _handover(world) -> dict[tuple[str, str], str]:
    """Документы передачи: ``{(поставщик, вид документа + часть): id}``."""
    result = tender_post(world, "handover")
    assert result["status"] == "handed_over"
    request_id = tender_get(world)["request_id"]
    with use_company(world.slug):
        parts = {str(p.pk): p.kind for p in TenderRequest.objects.get(pk=request_id).parts.all()}
    docs = {(world.key_of[d["invitation_id"]], d["doc_type"], parts[d["part_id"]]): d["doc_id"]
            for d in result["documents"]}
    assert set(docs) == {("A", "agreement", "goods"), ("A", "invoice", "works"),
                         ("B", "invoice", "goods"), ("B", "invoice", "delivery")}
    return docs


# ── 4. документы БЗО штатными сервисами ─────────────────────────────────

def _send_invoice(world, invoice_id, number: str) -> Invoice:
    inv, _ = invoice_service.update_draft(world.sn, invoice_id, expected_version=None, data={
        "ext_number": number, "ext_date": timezone.localdate()})
    _attach(inv)
    invoice_service.submit(world.sn, inv.id, expected_version=None)
    return decisions.decide(world.fd, inv.id, decision="pay")


def _activate(world, agreement_id) -> Agreement:
    agr, _ = agreement_service.update_draft(world.sn, agreement_id, expected_version=None,
                                            data={"ext_number": "Д-501",
                                                  "ext_date": timezone.localdate()})
    _attach(agr, "agreement", "dogovor.pdf")
    agreement_service.submit(world.sn, agr.id, expected_version=None)
    for user_id in (s.FD, GD):
        process = signoff.get_process_for("bpp.agreement", str(agr.pk))
        task = next(t for st in process["stages"] for t in st["tasks"]
                    if t["user_id"] == user_id and t["state"] == "pending")
        signoff.decide_many(actor_id=user_id, items=[{"task_id": task["id"],
                                                      "decision": "approve"}])
    agr.refresh_from_db()
    assert agr.status == "active"
    return agr


def _pay(world, inv: Invoice, amount) -> Invoice:
    return payments.mark_paid(world.buh, inv.id, pay_date=timezone.localdate(),
                              amount=Decimal(str(amount)))


def _close(world, inv: Invoice) -> Invoice:
    """БУХ запросил закрывающие — сканы приёмки приходят сами; автор
    подтверждает «Документы вложены», БУХ принимает — «Закрыт»."""
    inv = payments.request_docs(world.buh, inv.id)
    wanted = [k for k, need in inv.docs_required.items() if need]
    assert payments.missing_docs(inv, wanted) == [], "сканы приёмки не дошли до счёта"
    payments.submit_docs(world.sn, inv.id)
    return payments.accept_docs(world.buh, inv.id)


# ── 5. приёмка в тендере ────────────────────────────────────────────────

def _receive(world, key: str, kind: str, rows) -> str:
    awards = tender_get(world, "/award")
    by_name = {**{a["name"]: a["award_id"] for a in awards["lines"]},
               **{a["kind"]: a["award_id"] for a in awards["extras"]}}
    receipt = ok(h.call("post", f"tenders/{world.tender_id}/receipts", world.slug, h.SN, {
        "invitation_id": world.inv[key], "received_at": str(timezone.localdate()),
        "kind": kind, "lines": [{"award_id": by_name[name], "qty": qty} for name, qty in rows]}),
        201)
    return receipt["id"]


def _scan(world, receipt_id: str, file_type: str, name: str) -> None:
    with use_company(world.slug):
        files.attach_bytes("tender.receipt", receipt_id, file_type=file_type, data=PDF,
                           filename=name, mime="application/pdf", actor_id=h.SN)


def test_request_to_closed_tender_through_real_bpp(world):
    req = _request(world)
    _tender(world, req)
    _award(world)
    docs = _handover(world)

    with use_company(world.slug):
        # Аванс у A и предоплата у B — счета «аванс»; товар A — договор.
        kinds = {k: Invoice.objects.get(pk=v).is_advance for k, v in docs.items()
                 if k[1] == "invoice"}
        assert set(kinds.values()) == {True}
        b_goods = _send_invoice(world, docs[("B", "invoice", "goods")], "Б-1")
        b_deliv = _send_invoice(world, docs[("B", "invoice", "delivery")], "Б-2")
        a_works = _send_invoice(world, docs[("A", "invoice", "works")], "А-1")
        agr = _activate(world, docs[("A", "agreement", "goods")])
        a_goods = invoice_service.create_from_agreement(world.sn, agr.id)
        a_goods = _send_invoice(world, a_goods.id, "А-2")
        assert (b_goods.amount, b_deliv.amount, a_works.amount, a_goods.amount) == (
            Decimal("360000.00"), Decimal("250000.00"), Decimal("1100000.00"),
            Decimal("4500000.00"))
        assert a_goods.status == InvoiceStatus.TO_PAY and not a_goods.tender_key
    assert stages(world) == {"A": "awaiting_shipment_payment", "B": "awaiting_shipment_payment"}

    with use_company(world.slug):
        _pay(world, b_goods, "360000")             # предоплата B — целиком
        _pay(world, b_deliv, "250000")
        _pay(world, a_works, "330000")             # аванс A — 30 % от 5 600 000
        _pay(world, a_goods, "1350000")
    assert stages(world) == {"A": "in_delivery", "B": "in_delivery"}

    # Приёмка и сканы: B — товар (доставка — вместе с ним), A — товар и работы.
    b_receipt = _receive(world, "B", "goods", [("Уголок 50×5", "4")])
    _scan(world, b_receipt, "tender_waybill", "Накладная Б.pdf")
    _scan(world, b_receipt, "tender_act", "АВР доставки Б.pdf")
    a_goods_receipt = _receive(world, "A", "goods", [("Швеллер 12П", "10")])
    _scan(world, a_goods_receipt, "tender_waybill", "Накладная А.pdf")
    assert stages(world) == {"A": "partially_received", "B": "received"}
    a_works_receipt = _receive(world, "A", "works", [("works", "1")])
    _scan(world, a_works_receipt, "tender_act", "АВР монтажа.pdf")
    assert stages(world) == {"A": "awaiting_final_payment", "B": "received"}
    with use_company(world.slug):
        b_goods.refresh_from_db()
        assert b_goods.received_at == timezone.localdate()     # приёмка — на счёте БЗО

        _close(world, b_goods)
        _close(world, b_deliv)
        a_works = _close(world, _pay(world, a_works, "770000"))
        a_goods = _pay(world, a_goods, "3150000")
    # У A всё принято и оплачено, но счёт по договору ещё не закрыт.
    assert stages(world) == {"A": "received", "B": "closed"}
    assert tender_get(world)["status"] == "delivery"

    with use_company(world.slug):
        a_goods = _close(world, a_goods)           # последний — счёт по договору
        assert a_goods.status == InvoiceStatus.CLOSED
        assert TenderRequest.objects.get(pk=req["id"]).status == "closed"
    assert stages(world) == {"A": "closed", "B": "closed"}
    assert tender_get(world)["status"] == "closed"
