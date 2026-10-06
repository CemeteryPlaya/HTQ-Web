"""Стык с тендерным модулем — пакет B-1 (T1.2; пошаговый план 2026-10-07 §2,
мастер-план tender T-07, T-09, T-20).

ЗЗ с ``source="tender"`` заводит и ведёт только ``bpp.interface``: сервисы и
API БЗО её не правят (409 ``E-STS-02``), её позиции не видны в Плане и не
выбираются в мастер F-03, а смены статуса приходят слушателю в той же
транзакции.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.test import Client

from apps.bpp import interface as bpp
from apps.bpp.models import PurchaseRequest, RequestStatus
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.budget import balance
from apps.bpp.services.plan import service as plan
from apps.bpp.services.requests import listeners
from apps.bpp.services.requests import read as request_read
from apps.bpp.services.requests import requests as service
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

BASE = "/api/bpp/v1"
TN = "ТН-2026-000001"


@pytest.fixture
def heard(monkeypatch):
    """Слушатель-самописец: реестр подменяется пустым, чтобы слушатель
    ``apps.tender`` (T1.3) не вмешивался в проверки контракта БЗО."""
    monkeypatch.setattr(listeners, "_LISTENERS", [])
    got: list = []
    bpp.register_request_listener(got.append)
    return got


def _pipe():
    return s.article("T-PIPE", "Трубы", "supply")


def _setup(slug, *, metal=1_000, pipe=1_000):
    proj = s.project(members=[s.SN])
    s.approved_budget(slug, proj, {s.metal(): metal, _pipe(): pipe, s.design(): 1_000})
    s.request_route()
    s.actor(slug, s.SN, "bpp-sn")
    return proj


def _part(art, *prices, key=None, bpp_request_id=None, kind="goods"):
    return {"key": key or str(uuid.uuid4()), "bpp_request_id": bpp_request_id,
            "article_id": str(art.id), "purchase_type": kind,
            "items": [{**item, "uom_id": str(item["uom_id"])}
                      for item in s.items(*[(1, p) for p in prices])]}


def _payload(proj, *parts, user_id=s.SN, role="sn"):
    return bpp.TenderRequestSubmit.model_validate({
        "actor": {"user_id": user_id}, "initiator_role": role,
        "project_id": str(proj.id), "tender_number": TN,
        "justification": "Нужно для монтажа каркаса",
        "need_date": s.header(proj, s.metal())["need_date"], "parts": list(parts)})


def _actor(user_id=s.SN):
    return bpp.TenderActor(user_id=user_id)


def _submit(proj, *parts, **kw):
    return bpp.submit_request_from_tender(_payload(proj, *parts, **kw))


def _approve(ref):
    req = PurchaseRequest.objects.get(pk=ref.bpp_request_id)
    s.decide(req, s.TD, "approve"), s.decide(req, s.OD, "approve")
    req.refresh_from_db()
    return req


# ── схемы — атрибуты интерфейса (сторож изоляции) ──────────────────────

def test_schemas_are_reexported_from_the_interface():
    for name in ("TenderActor", "TenderItemIn", "TenderPartIn", "TenderRequestSubmit",
                 "RequestRef", "RequestStatusOut", "BudgetFigures", "BudgetArticle"):
        assert hasattr(bpp, name), name


# ── отправка ────────────────────────────────────────────────────────────

def test_two_parts_make_two_requests_in_approval_with_reserve(company_context, heard):
    proj = _setup(company_context["slug"])
    first, second = _part(s.metal(), 300), _part(_pipe(), 120, 80)
    refs = _submit(proj, first, second)

    assert [ref.key for ref in refs] == [first["key"], second["key"]]
    assert {ref.status for ref in refs} == {RequestStatus.IN_APPROVAL}
    rows = {str(r.pk): r for r in PurchaseRequest.objects.all()}
    assert set(rows) == {ref.bpp_request_id for ref in refs}
    for ref in refs:
        req = rows[ref.bpp_request_id]
        assert (req.source, req.tender_number, req.number) == ("tender", TN, ref.number)
        assert req.author_id == s.SN and req.status == RequestStatus.IN_APPROVAL
        assert ref.items == [str(i.pk) for i in req.items.order_by("line_no")]
    assert balance.balance(proj.id, s.metal().id)["committed"] == Decimal("300.00")
    assert balance.balance(proj.id, _pipe().id)["committed"] == Decimal("200.00")
    figures = bpp.budget_available(str(proj.id), str(_pipe().id), actor=_actor(), role="sn")
    assert (figures.limit, figures.committed, figures.available, figures.currency_code) == (
        Decimal("1000.00"), Decimal("200.00"), Decimal("800.00"), "KZT")
    # Слушатель узнал о старте обеих ЗЗ в транзакции отправки.
    assert [(e.bpp_request_id, e.status) for e in heard] == [
        (ref.bpp_request_id, "in_approval") for ref in refs]


def test_br011_in_the_second_part_rolls_back_the_first(company_context, heard):
    proj = _setup(company_context["slug"], pipe=100)
    second = _part(_pipe(), 150)
    with pytest.raises(DomainError) as exc:
        _submit(proj, _part(s.metal(), 300), second)
    assert exc.value.code == "E-BUD-01"
    assert exc.value.details == {"part": second["key"]}
    assert not PurchaseRequest.objects.exists()
    assert balance.balance(proj.id, s.metal().id)["committed"] == Decimal("0")


def test_foreign_group_article_is_403_e_req_04(company_context, heard):
    proj = _setup(company_context["slug"])
    part = _part(s.design(), 100)
    with pytest.raises(DomainError) as exc:
        _submit(proj, part)
    assert (exc.value.code, exc.value.status) == ("E-REQ-04", 403)
    assert exc.value.details == {"part": part["key"]}
    assert not PurchaseRequest.objects.exists()


def test_resubmit_on_rework_rebuilds_the_same_request(company_context, heard):
    proj = _setup(company_context["slug"])
    part = _part(s.metal(), 300)
    [ref] = _submit(proj, part)
    req = PurchaseRequest.objects.get(pk=ref.bpp_request_id)
    assert s.decide(req, s.TD, "rework", "Уточните марку стали")["ok"]

    [again] = _submit(proj, _part(s.metal(), 100, 50, key=part["key"],
                                  bpp_request_id=ref.bpp_request_id))
    assert (again.bpp_request_id, again.number, again.status) == (
        ref.bpp_request_id, ref.number, "in_approval")
    req.refresh_from_db()
    assert req.total_amount == Decimal("150.00") and req.items.count() == 2
    assert again.items == [str(i.pk) for i in req.items.order_by("line_no")]
    assert PurchaseRequest.objects.count() == 1


def test_resubmit_refuses_a_request_not_from_the_tender(company_context, heard):
    proj = _setup(company_context["slug"])
    sn = s.actor(company_context["slug"], s.SN, "bpp-sn")
    own = service.create_draft(sn, {**s.header(proj, s.metal()), "items": s.items((1, 10))})
    part = _part(s.metal(), 100, bpp_request_id=str(own.pk))
    with pytest.raises(DomainError) as exc:
        _submit(proj, part)
    assert exc.value.status == 404 and exc.value.details == {"part": part["key"]}


# ── слушатель ───────────────────────────────────────────────────────────

def test_td_decisions_reach_the_listener(company_context, heard):
    proj = _setup(company_context["slug"])
    rejected, reworked, approved = (_submit(proj, _part(s.metal(), 100))[0],
                                    _submit(proj, _part(s.metal(), 100))[0],
                                    _submit(proj, _part(_pipe(), 100))[0])
    heard.clear()

    s.decide(PurchaseRequest.objects.get(pk=rejected.bpp_request_id), s.TD, "reject",
             "Металлопрокат не нужен")
    s.decide(PurchaseRequest.objects.get(pk=reworked.bpp_request_id), s.TD, "rework",
             "Уточните марку стали")
    _approve(approved)

    last = {e.bpp_request_id: e for e in heard}
    assert last[rejected.bpp_request_id].status == "rejected"
    assert last[reworked.bpp_request_id].status == "rework"
    assert last[reworked.bpp_request_id].rework_comment == "Уточните марку стали"
    assert last[approved.bpp_request_id].status == "approved"
    # ТД утвердил — ЗЗ ещё «На согласовании», второй смены статуса нет.
    assert [e.status for e in heard if e.bpp_request_id == approved.bpp_request_id] == [
        "approved"]


def test_ordinary_requests_do_not_reach_the_listener(company_context, heard):
    proj = _setup(company_context["slug"])
    sn = s.actor(company_context["slug"], s.SN, "bpp-sn")
    req = service.create_draft(sn, {**s.header(proj, s.metal()), "items": s.items((1, 10))})
    service.submit(sn, req.id, expected_version=None)
    assert heard == []


def test_listener_failure_rolls_back_the_status_change(company_context, heard):
    proj = _setup(company_context["slug"])
    [ref] = _submit(proj, _part(s.metal(), 100))
    req = PurchaseRequest.objects.get(pk=ref.bpp_request_id)
    s.decide(req, s.TD, "rework", "Уточните марку стали")

    def broken(_status):
        raise RuntimeError("tender отказал")

    bpp.register_request_listener(broken)
    with pytest.raises(RuntimeError):
        bpp.cancel_requests_from_tender([ref.bpp_request_id], actor=_actor(),
                                        comment="Закупка больше не нужна")
    req.refresh_from_db()
    assert req.status == RequestStatus.REWORK


# ── отзыв, отмена, возврат в План ───────────────────────────────────────

def test_withdraw_returns_the_request_to_draft(company_context, heard):
    proj = _setup(company_context["slug"])
    [ref] = _submit(proj, _part(s.metal(), 300))
    heard.clear()
    bpp.withdraw_requests_from_tender([ref.bpp_request_id], actor=_actor())
    req = PurchaseRequest.objects.get(pk=ref.bpp_request_id)
    assert req.status == RequestStatus.DRAFT
    assert [e.status for e in heard] == ["draft"]
    assert balance.balance(proj.id, s.metal().id)["committed"] == Decimal("0")


def test_cancel_by_status(company_context, heard):
    proj = _setup(company_context["slug"], metal=10_000)
    draft = _submit(proj, _part(s.metal(), 100))[0]
    bpp.withdraw_requests_from_tender([draft.bpp_request_id], actor=_actor())
    approved = _submit(proj, _part(s.metal(), 200))[0]
    _approve(approved)
    rejected = _submit(proj, _part(s.metal(), 300))[0]
    s.decide(PurchaseRequest.objects.get(pk=rejected.bpp_request_id), s.TD, "reject",
             "Металлопрокат не нужен")
    pending = _submit(proj, _part(s.metal(), 400))[0]

    with pytest.raises(DomainError) as exc:  # «На согласовании» — сначала отозвать
        bpp.cancel_requests_from_tender(
            [draft.bpp_request_id, pending.bpp_request_id], actor=_actor(),
            comment="Закупка больше не нужна")
    assert (exc.value.code, exc.value.status) == ("E-STS-01", 409)
    assert PurchaseRequest.objects.get(pk=draft.bpp_request_id).status == RequestStatus.DRAFT

    heard.clear()
    bpp.cancel_requests_from_tender(
        [draft.bpp_request_id, approved.bpp_request_id, rejected.bpp_request_id],
        actor=_actor(), comment="Закупка больше не нужна")
    status = {str(r.pk): r.status for r in PurchaseRequest.objects.all()}
    assert status[draft.bpp_request_id] == RequestStatus.CANCELLED
    assert status[approved.bpp_request_id] == RequestStatus.CLOSED
    assert status[rejected.bpp_request_id] == RequestStatus.REJECTED
    assert {(e.bpp_request_id, e.status) for e in heard} == {
        (draft.bpp_request_id, "cancelled"), (approved.bpp_request_id, "closed")}
    # Резерв остался только у идущей на согласовании.
    assert balance.balance(proj.id, s.metal().id)["committed"] == Decimal("400.00")


def test_request_status_skips_foreign_and_impossible_keys(company_context, heard):
    proj = _setup(company_context["slug"])
    [ref] = _submit(proj, _part(s.metal(), 100))
    sn = s.actor(company_context["slug"], s.SN, "bpp-sn")
    own = service.create_draft(sn, {**s.header(proj, s.metal()), "items": s.items((1, 10))})
    got = bpp.request_status([ref.bpp_request_id, str(own.pk), "не-uuid",
                              str(uuid.uuid4())])
    assert list(got) == [ref.bpp_request_id]
    assert got[ref.bpp_request_id].number == ref.number
    assert got[ref.bpp_request_id].status == "in_approval"


# ── замок T-07 ──────────────────────────────────────────────────────────

def test_bpp_services_refuse_tender_requests(company_context, heard):
    slug = company_context["slug"]
    proj = _setup(slug)
    [ref] = _submit(proj, _part(s.metal(), 100))
    req = PurchaseRequest.objects.get(pk=ref.bpp_request_id)
    sn = s.actor(slug, s.SN, "bpp-sn")
    text = f"Заявка {req.number} ведётся в тендерном модуле ({TN})"
    calls = [
        lambda: service.update_draft(sn, req.id, expected_version=None, data={"items": []}),
        lambda: service.delete_draft(sn, req.id, expected_version=None),
        lambda: service.submit(sn, req.id, expected_version=None),
        lambda: service.withdraw(sn, req.id, expected_version=None),
        lambda: service.cancel(sn, req.id, expected_version=None,
                               comment="Закупка больше не нужна"),
        lambda: service.close_remainder(sn, req.id, expected_version=None,
                                        comment="Закупка больше не нужна"),
        lambda: service.copy(sn, req.id),
    ]
    for call in calls:
        with pytest.raises(DomainError) as exc:
            call()
        assert (exc.value.code, exc.value.status, exc.value.message) == (
            "E-STS-02", 409, text)
    req.refresh_from_db()
    assert req.status == RequestStatus.IN_APPROVAL and PurchaseRequest.objects.count() == 1

    assert service.allowed_actions(sn, req) == ["print"]
    card = request_read.card(sn, req)
    assert (card["source"], card["tender_number"]) == ("tender", TN)
    row = request_read.registry(sn)["items"][0]
    assert (row["source"], row["tender_number"]) == ("tender", TN)


def test_bpp_api_refuses_tender_requests(company_context, heard):
    slug = company_context["slug"]
    proj = _setup(slug)
    [ref] = _submit(proj, _part(s.metal(), 100))
    client = Client()
    headers = s.auth(slug, s.SN)
    withdraw = client.post(f"{BASE}/requests/{ref.bpp_request_id}/withdraw",
                           json.dumps({}), **headers)
    patch = client.patch(f"{BASE}/requests/{ref.bpp_request_id}",
                         json.dumps({"justification": "Другое обоснование"}), **headers)
    for response in (withdraw, patch):
        assert response.status_code == 409, response.json()
        assert response.json()["code"] == "E-STS-02"
    with use_company(slug):
        assert PurchaseRequest.objects.get(pk=ref.bpp_request_id).status == "in_approval"


def test_plan_hides_tender_positions_until_released(company_context, heard):
    slug = company_context["slug"]
    proj = _setup(slug)
    [ref] = _submit(proj, _part(s.metal(), 100))
    req = _approve(ref)
    assert req.status == RequestStatus.APPROVED
    sn = s.actor(slug, s.SN, "bpp-sn")
    assert plan.plan_items(sn)["items"] == []
    assert plan.visible(sn).count() == 0

    item_ids = [str(i.pk) for i in req.items.all()]
    for target in ("contract", "invoice"):
        with pytest.raises(DomainError) as exc:
            plan.validate_selection(sn, item_ids, target=target)
        assert (exc.value.code, exc.value.status) == ("E-STS-02", 409)
    with pytest.raises(DomainError) as exc:  # ручной договор на её позицию
        agreement_service.create_from_plan(sn, item_ids)
    assert exc.value.code == "E-STS-02"

    bpp.release_to_plan([ref.bpp_request_id], actor=_actor())
    req.refresh_from_db()
    assert (req.source, req.tender_number) == ("", TN)
    assert [row["id"] for row in plan.plan_items(sn)["items"]] == item_ids
    assert plan.validate_selection(sn, item_ids, target="invoice")["ok"]
    # Статус ЗЗ, ушедшей в План, tender по-прежнему читает.
    assert list(bpp.request_status([ref.bpp_request_id])) == [ref.bpp_request_id]


def test_release_to_plan_needs_an_approved_request(company_context, heard):
    proj = _setup(company_context["slug"])
    [ref] = _submit(proj, _part(s.metal(), 100))
    with pytest.raises(DomainError) as exc:
        bpp.release_to_plan([ref.bpp_request_id], actor=_actor())
    assert (exc.value.code, exc.value.status) == ("E-STS-01", 409)
    assert PurchaseRequest.objects.get(pk=ref.bpp_request_id).source == "tender"


def test_release_to_plan_is_for_the_author_or_the_fd(company_context, heard):
    slug = company_context["slug"]
    proj = _setup(slug)
    refs = [_submit(proj, _part(s.metal(), 100))[0], _submit(proj, _part(_pipe(), 100))[0]]
    for ref in refs:
        _approve(ref)
    ids = [ref.bpp_request_id for ref in refs]

    s.actor(slug, s.SN2, "bpp-sn")
    with pytest.raises(DomainError) as exc:  # чужой снабженец
        bpp.release_to_plan(ids, actor=_actor(s.SN2))
    assert (exc.value.code, exc.value.status) == ("E-ACC-01", 403)
    assert set(PurchaseRequest.objects.values_list("source", flat=True)) == {"tender"}

    s.actor(slug, s.FD, "bpp-fd")
    bpp.release_to_plan(ids, actor=_actor(s.FD))
    assert set(PurchaseRequest.objects.values_list("source", flat=True)) == {""}


# ── статьи и остаток ────────────────────────────────────────────────────

def test_budget_articles_are_those_of_the_role_group(company_context, heard):
    proj = _setup(company_context["slug"])
    _submit(proj, _part(s.metal(), 300))
    got = bpp.budget_articles(str(proj.id), actor=_actor(), role="sn")
    assert [(a.code, a.group_code, a.available) for a in got] == [
        ("T-METAL", "supply", Decimal("700.00")), ("T-PIPE", "supply", Decimal("1000.00"))]
    with pytest.raises(DomainError) as exc:  # роли ПМ у снабженца нет
        bpp.budget_articles(str(proj.id), actor=_actor(), role="pm")
    assert exc.value.status == 403


def test_budget_available_without_a_line_is_e_bud_07(company_context, heard):
    proj = _setup(company_context["slug"])
    other = s.article("T-WOOD", "Пиломатериалы", "supply")
    with pytest.raises(DomainError) as exc:
        bpp.budget_available(str(proj.id), str(other.id), actor=_actor(), role="sn")
    assert exc.value.code == "E-BUD-07"
    with pytest.raises(DomainError) as exc:
        bpp.budget_available(str(s.project("П-016").id), str(other.id), actor=_actor(),
                             role="sn")
    assert exc.value.code == "E-BUD-02"


def test_budget_available_is_scoped_to_the_actor(company_context, heard):
    """Остаток — в правах пользователя, как у заявки (решение ревью 07.10)."""
    slug = company_context["slug"]
    proj = _setup(slug)
    with pytest.raises(DomainError) as exc:  # статья чужой группы (BR-010)
        bpp.budget_available(str(proj.id), str(s.design().id), actor=_actor(), role="sn")
    assert (exc.value.code, exc.value.status) == ("E-REQ-04", 403)
    s.actor(slug, s.PM, "bpp-pm")
    with pytest.raises(DomainError) as exc:  # ПМ — только проекты-участия (BR-014)
        bpp.budget_available(str(proj.id), str(s.design().id), actor=_actor(s.PM),
                             role="pm")
    assert (exc.value.code, exc.value.status) == ("E-REQ-05", 403)
    with pytest.raises(DomainError) as exc:  # роли ПМ у снабженца нет
        bpp.budget_available(str(proj.id), str(s.design().id), actor=_actor(), role="pm")
    assert exc.value.status == 403
    member = s.project("П-017", members=[s.PM])
    s.approved_budget(slug, member, {s.design(): 500})
    figures = bpp.budget_available(str(member.id), str(s.design().id), actor=_actor(s.PM),
                                   role="pm")
    assert figures.available == Decimal("500.00")


# ── документы ЗЗ на панели файлов (T-07) ────────────────────────────────

def test_files_of_a_tender_request_are_locked(company_context, heard, memory_storage):  # noqa: F811
    from apps.bpp import file_owners
    from apps.bpp.tests.test_request_files import _add
    from apps.files import interface as files

    slug = company_context["slug"]
    proj = _setup(slug)
    [ref] = _submit(proj, _part(s.metal(), 100))
    # Отозванная — «Черновик»: обычной заявке файлы в нём добавлять можно.
    bpp.withdraw_requests_from_tender([ref.bpp_request_id], actor=_actor())
    req = PurchaseRequest.objects.get(pk=ref.bpp_request_id)
    text = f"Заявка {req.number} ведётся в тендерном модуле ({TN})"

    response = _add(Client(), slug, s.SN, ref.bpp_request_id)
    assert response.status_code == 409, response.json()
    assert (response.json()["code"], response.json()["detail"]) == ("E-FIL-06", text)
    token = SimpleNamespace(user_id=s.SN, is_superuser=False)
    for check in (lambda: file_owners._request_can_modify(req.pk, token),
                  lambda: file_owners._request_can_version(req.pk, token, "request_attachment")):
        with use_company(slug), pytest.raises(files.FilesLocked) as exc:  # запрос вернул public
            check()
        assert str(exc.value) == text
