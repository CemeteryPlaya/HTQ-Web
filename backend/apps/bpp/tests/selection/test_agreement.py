"""Выбор альтернативы по договору — голоса ФД и ГД (B5.1; ТЗ §12.4 п.1, 3, 5;
D-25, D-26; план B5.1, D-B51-8, D-B51-9, D-B51-11; ревью этапа 5 B-6)."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from django.utils import timezone

from apps.bpp.models import (
    Agreement,
    AgreementStatus,
    AuditLog,
    KpiRecord,
    KpiStatus,
    OfferStatus,
)
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.alternatives import lifecycle
from apps.bpp.services.selection import voting
from apps.bpp.tests import stage2 as s
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.alternatives import common
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.hr.models import Department, Employee, EmployeeStatus, Position
from apps.notifications import interface as notifications
from apps.signoff import interface as signoff
from apps.signoff.models import ApprovalProcess, ApprovalRoute

pytestmark = pytest.mark.django_db
GD = invoice_flow.GD


def _position_route() -> dict[str, int]:
    """Маршрут договора по должностям «ФД → ГД», оба этапа выбирают вариант
    (как у ``bpp_configure_routes``): у задачи есть должность — её и
    предсогласует новый договор (D-26)."""
    dept = Department.objects.create(name="Дирекция", path="b51-dir")
    positions = {}
    for weight, (key, user_id, title) in enumerate(
            (("fd", s.FD, "Финансовый директор"), ("gd", GD, "Генеральный директор")),
            start=600):
        s.user(user_id)
        position = Position.objects.create(title=title, department=dept, weight=weight)
        Employee.objects.create(user_id=user_id, first_name=title, last_name="Тест",
                                email=f"b51-{user_id}@htq.test", department=dept,
                                position=position, hire_date="2024-01-01",
                                status=EmployeeStatus.ACTIVE)
        positions[key] = position.pk
    ApprovalRoute.objects.filter(subject_type="bpp.agreement", scope="").update(
        is_active=False)
    signoff.configure_route(subject_type="bpp.agreement", name="Договор: ФД → ГД", stages=[
        {"order": n, "name": name, "quorum": "any", "position_ids": [positions[key]],
         "votes_option": True}
        for n, (key, name) in enumerate((("fd", "ФД"), ("gd", "ГД")), start=1)])
    return positions


def _on_review(slug, *amounts, limit=20_000_000, positions=False):
    """Договор «На согласовании» от СН; ``positions`` — по маршруту должностей."""
    proj = invoice_flow._setup(slug, limit)
    route = _position_route() if positions else None
    author = s.actor(slug, s.SN, "bpp-sn")
    req = invoice_flow._approved_request(author, proj, *amounts)
    agr = agreement_service.create_from_plan(author, [str(i.id) for i in req.items.all()])
    agr, _ = agreement_service.update_draft(author, agr.id, expected_version=None, data={
        "counterparty_id": str(invoice_flow._counterparty("100000000009").pk),
        "ext_number": "Д-1", "ext_date": timezone.localdate()})
    common.with_file(agr, "agreement")
    agr = agreement_service.submit(author, agr.id, expected_version=None)
    return author, agr, route


def _vote(agr, user_id, option_key, decision="approve") -> dict:
    process = signoff.get_process_for("bpp.agreement", str(agr.pk))
    task = next(t for stage in process["stages"] for t in stage["tasks"]
                if t["user_id"] == user_id and t["state"] == "pending")
    return signoff.decide_many(actor_id=user_id, items=[
        {"task_id": task["id"], "decision": decision, "option_key": option_key}])[0]


def _offer(slug, agr, price, n=2):
    return common.filed(common.sn(slug, common.SN2 if n == 2 else common.SN3), agr,
                        common.cp(n), price=price, source_type=common.AGREEMENT)


def _key(offer) -> str:
    return f"{lifecycle.OFFER_PREFIX}{offer.pk}"


def test_fd_and_gd_vote_for_the_alternative_and_it_replaces_the_agreement(company_context):
    slug = company_context["slug"]
    _, agr, _ = _on_review(slug, 1_000_000)
    offer = _offer(slug, agr, 900_000)

    assert _vote(agr, s.FD, _key(offer))["ok"]
    assert _vote(agr, GD, _key(offer))["ok"]

    agr.refresh_from_db(), offer.refresh_from_db()
    assert agr.status == AgreementStatus.REPLACED and agr.approval_state == "approved"
    assert offer.status == OfferStatus.SELECTED and offer.decided_by_id == GD
    new = Agreement.objects.get(pk=offer.result_id)
    assert (new.status, new.author_id, new.counterparty_id, new.amount) == (
        AgreementStatus.DRAFT, s.SN, offer.counterparty_id, D("900000.00"))
    record = KpiRecord.objects.get(offer=offer)
    assert (record.status, record.selected_by_id) == (KpiStatus.PRELIMINARY, GD)
    votes = AuditLog.objects.filter(object_id=str(agr.pk), action="option_vote")
    assert sorted(row.actor_id for row in votes) == sorted([s.FD, GD])     # D-26


@pytest.mark.parametrize("fd_votes_offer", [True, False])
def test_gd_vote_decides_when_the_votes_diverge(company_context, fd_votes_offer):
    slug = company_context["slug"]
    _, agr, _ = _on_review(slug, 1_000_000)
    offer = _offer(slug, agr, 900_000)

    assert _vote(agr, s.FD, _key(offer) if fd_votes_offer else lifecycle.ORIGINAL)["ok"]
    assert _vote(agr, GD, lifecycle.ORIGINAL if fd_votes_offer else _key(offer))["ok"]

    agr.refresh_from_db(), offer.refresh_from_db()
    if fd_votes_offer:          # ГД — за исходный: договор вступает в силу
        assert (agr.status, offer.status) == (AgreementStatus.ACTIVE, OfferStatus.NOT_SELECTED)
        assert not KpiRecord.objects.filter(offer=offer).exists()
    else:                       # ГД — за альтернативу: договор заменён
        assert (agr.status, offer.status) == (AgreementStatus.REPLACED, OfferStatus.SELECTED)


def test_vote_for_an_alternative_over_the_article_is_refused(company_context):
    """BR-093 — на момент голоса: голос за АП, которой не хватает остатка
    статьи, не принимается; за исходный — принимается."""
    slug = company_context["slug"]
    _, agr, _ = _on_review(slug, 1_000_000, limit=1_100_000)
    offer = _offer(slug, agr, 1_300_000)

    refused = _vote(agr, s.FD, _key(offer))
    assert not refused["ok"] and "свободного остатка статьи" in refused["error"]
    assert _vote(agr, s.FD, lifecycle.ORIGINAL)["ok"]


def test_new_agreement_by_voted_alternative_has_the_gd_stage_preapproved(company_context):
    """D-26: новый договор по АП, выбранной голосованием, — этап ГД
    предсогласован, ФД проверяет своим этапом; утверждение ФД вводит договор
    в силу и подтверждает KPI."""
    slug = company_context["slug"]
    author, agr, positions = _on_review(slug, 1_000_000, positions=True)
    offer = _offer(slug, agr, 900_000)
    assert _vote(agr, s.FD, _key(offer))["ok"] and _vote(agr, GD, _key(offer))["ok"]
    offer.refresh_from_db()
    new = Agreement.objects.get(pk=offer.result_id)

    new, _ = agreement_service.update_draft(author, new.id, expected_version=None, data={
        "ext_number": "Д-2", "ext_date": timezone.localdate()})
    common.with_file(new, "agreement")
    agreement_service.submit(author, new.id, expected_version=None)

    process = ApprovalProcess.objects.get(subject_type="bpp.agreement", subject_id=str(new.pk))
    # ``company`` пуст — должность ГД своей компании (B8.1: у дочерней это
    # была бы должность холдинга со слагом холдинга).
    assert process.preapproved == [{"position_id": positions["gd"], "company": "",
                                    "actor_id": GD, "label": voting.PREAPPROVED_LABEL}]
    assert _vote(new, s.FD, lifecycle.ORIGINAL)["ok"]          # ГД уже согласовал
    new.refresh_from_db()
    assert new.status == AgreementStatus.ACTIVE
    assert KpiRecord.objects.get(offer=offer).status == KpiStatus.CONFIRMED


def test_voters_hear_of_an_alternative_filed_after_their_vote(company_context):
    """§12.4 п.1: АП подана после голоса ФД — ФД уведомлён; ГД ещё не голосовал."""
    slug = company_context["slug"]
    _, agr, _ = _on_review(slug, 1_000_000)
    first = _offer(slug, agr, 950_000)
    assert _vote(agr, s.FD, _key(first))["ok"]

    _offer(slug, agr, 900_000, n=3)

    def heard(user_id):
        return [row for row in notifications.latest(user_id, company_slug=slug)
                if row["event"] == voting.EVENT_VOTED_OFFER]
    assert len(heard(s.FD)) == 1 and heard(GD) == []
