"""Привлечение партнёра ↔ договор модуля «Закупки и оплаты» (хвост этапа 6, M-5).

У замороженной компании новые договоры живут в ``bpp``, поэтому привлечение
получило ключ ``bpp_agreement_id`` (UUID строкой). Целостность голого ключа
держит ``contractor_service``: договор того же контрагента, в статусе
«Действует»/«Исполнен»; номер ``ДГ-…`` берётся у модуля, не из запроса.
Поиск договоров для выбора идёт с правами пользователя на договоры.
"""

from __future__ import annotations

import uuid

import pytest
from django.test import Client
from django.utils import timezone

from apps.access.tests.helpers import assign
from apps.bpp import interface as bpp
from apps.bpp.models import Agreement, Counterparty as BppCounterparty
from apps.contracts.models import FreezeState
from apps.contracts.tests import helpers as contracts_helpers
from apps.tasks.models import Contractor, ContractorEngagement, Site

from .helpers import BASE, COMPANY, admin_token, auth, patch_json, post_json

SEARCH = f"{BASE}/contractor-engagements/agreement-search"


def _cp(reg="123456789012", name="ТОО «Альфа»") -> BppCounterparty:
    return BppCounterparty.objects.create(name=name, kind="legal", country_code="KZ",
                                          reg_number=reg)


def _agreement(cp, number="ДГ-2026-000001", status="active", **over) -> Agreement:
    return Agreement.objects.create(
        number=number, project_id=uuid.uuid4(), article_id=uuid.uuid4(),
        counterparty=cp, amount=1000, author_id=1, status=status,
        ext_number=number[-3:], ext_date=timezone.localdate(), **over)


def _partner(cp) -> Contractor:
    return Contractor.objects.create(name=f"Монтаж {cp.name}", bpp_counterparty_id=str(cp.pk))


def _site(name="Алга") -> Site:
    return Site.objects.create(name=name)


def _grant_all_agreements() -> None:
    auth(admin_token())      # заводит компанию и роли tasks
    assign(COMPANY, 9, "bpp.agreements", "view")
    assign(COMPANY, 9, "bpp.agreements.all", "view")


def _post(partner, *, see_all: bool = True, **body):
    """Привязка от имени администратора задач (user 9); по умолчанию он видит
    все договоры — как ФД. ``see_all=False`` — права решает сам тест."""
    if see_all:
        _grant_all_agreements()
    return post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": partner.id, "site_id": _site(str(uuid.uuid4())).id,
                      **body}, **auth(admin_token()))


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["active", "fulfilled"])
def test_engagement_takes_bpp_agreement_and_its_number(status):
    cp = _cp()
    agreement = _agreement(cp, status=status)
    resp = _post(_partner(cp), bpp_agreement_id=str(agreement.pk).upper(),
                 contract_no="что-то своё")
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["bpp_agreement_id"] == str(agreement.pk)
    assert body["contract_no"] == agreement.number
    assert body["bpp_agreement"] == {"id": str(agreement.pk), "number": agreement.number,
                                     "status": status}
    assert body["agreement_id"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("raw", ["не-uuid", "123", "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"])
def test_garbage_uuid_is_422(raw):
    resp = _post(_partner(_cp()), bpp_agreement_id=raw)
    assert resp.status_code == 422, resp.content
    assert not ContractorEngagement.objects.exists()


@pytest.mark.django_db
def test_unknown_agreement_is_422():
    resp = _post(_partner(_cp()), bpp_agreement_id=str(uuid.uuid4()))
    assert resp.status_code == 422, resp.content


@pytest.mark.django_db
def test_agreement_of_another_counterparty_is_422():
    ours, theirs = _cp(), _cp(reg="210987654321", name="ТОО «Бета»")
    resp = _post(_partner(ours), bpp_agreement_id=str(_agreement(theirs).pk))
    assert resp.status_code == 422, resp.content
    assert "другим контрагентом" in resp.json()["detail"]
    assert not ContractorEngagement.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["draft", "on_review", "rework", "rejected",
                                    "terminated", "replaced"])
def test_unsuitable_status_is_422(status):
    cp = _cp()
    resp = _post(_partner(cp), bpp_agreement_id=str(_agreement(cp, status=status).pk))
    assert resp.status_code == 422, (status, resp.content)


@pytest.mark.django_db
def test_partner_without_counterparty_is_422():
    agreement = _agreement(_cp())
    resp = _post(Contractor.objects.create(name="Сами по себе"),
                 bpp_agreement_id=str(agreement.pk))
    assert resp.status_code == 422, resp.content
    assert "не связан" in resp.json()["detail"]


@pytest.mark.django_db
def test_contract_no_follows_bpp_number_on_patch_and_unlink_keeps_it():
    cp = _cp()
    agreement = _agreement(cp)
    partner = _partner(cp)
    engagement = ContractorEngagement.objects.create(
        contractor=partner, site=_site(), bpp_agreement_id=str(agreement.pk),
        contract_no=agreement.number)

    resp = patch_json(Client(), f"{BASE}/contractor-engagements/{engagement.id}/",
                      {"contract_no": "другой"}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json()["contract_no"] == agreement.number

    resp = patch_json(Client(), f"{BASE}/contractor-engagements/{engagement.id}/",
                      {"bpp_agreement_id": None}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json()["bpp_agreement_id"] is None
    assert resp.json()["contract_no"] == agreement.number


@pytest.mark.django_db
def test_changing_partner_counterparty_clears_bpp_agreement():
    cp, other = _cp(), _cp(reg="210987654321", name="ТОО «Бета»")
    agreement = _agreement(cp)
    partner = _partner(cp)
    engagement = ContractorEngagement.objects.create(
        contractor=partner, site=_site(), bpp_agreement_id=str(agreement.pk),
        contract_no=agreement.number)

    resp = patch_json(Client(), f"{BASE}/contractors/{partner.id}/",
                      {"bpp_counterparty_id": str(other.pk)}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    engagement.refresh_from_db()
    assert engagement.bpp_agreement_id == ""
    assert engagement.contract_no == agreement.number


@pytest.mark.django_db
def test_choosing_bpp_agreement_drops_the_old_contracts_link():
    cp = _cp()
    agreement = _agreement(cp)
    engagement = ContractorEngagement.objects.create(
        contractor=_partner(cp), site=_site(), agreement_id=4242, contract_no="Д-1")
    _grant_all_agreements()
    resp = patch_json(Client(), f"{BASE}/contractor-engagements/{engagement.id}/",
                      {"bpp_agreement_id": str(agreement.pk)}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    engagement.refresh_from_db()
    assert engagement.agreement_id is None
    assert engagement.bpp_agreement_id == str(agreement.pk)


# ─────────────────────────────────────────────────────────────────────────
# Поиск договоров — с правами пользователя на договоры
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_search_offers_suitable_agreements_of_the_partner_to_those_who_see_all():
    cp, other = _cp(), _cp(reg="210987654321", name="ТОО «Бета»")
    good = _agreement(cp, number="ДГ-2026-000001")
    _agreement(cp, number="ДГ-2026-000002", status="draft")
    _agreement(other, number="ДГ-2026-000003")
    partner = _partner(cp)
    auth(admin_token())            # заводит компанию и роли tasks
    assign(COMPANY, 9, "bpp.agreements", "view")
    assign(COMPANY, 9, "bpp.agreements.all", "view")

    resp = Client().get(SEARCH, {"contractor_id": partner.id}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert [row["id"] for row in resp.json()] == [str(good.pk)]
    row = resp.json()[0]
    assert {"id", "number", "status", "name"} <= set(row)

    by_number = Client().get(SEARCH, {"contractor_id": partner.id, "q": "000001"},
                             **auth(admin_token()))
    assert [r["number"] for r in by_number.json()] == ["ДГ-2026-000001"]
    nothing = Client().get(SEARCH, {"contractor_id": partner.id, "q": "000009"},
                           **auth(admin_token()))
    assert nothing.json() == []


@pytest.mark.django_db
def test_search_is_empty_without_agreement_rights():
    cp = _cp()
    _agreement(cp)
    partner = _partner(cp)
    resp = Client().get(SEARCH, {"contractor_id": partner.id}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json() == []


@pytest.mark.django_db
def test_search_is_empty_for_unlinked_partner_and_needs_edit_level():
    _agreement(_cp())
    alone = Contractor.objects.create(name="Сами по себе")
    resp = Client().get(SEARCH, {"contractor_id": alone.id}, **auth(admin_token()))
    assert resp.status_code == 200 and resp.json() == []
    from .helpers import token
    assert Client().get(SEARCH, {"contractor_id": alone.id},
                        **auth(token())).status_code == 403


# ─────────────────────────────────────────────────────────────────────────
# bpp.interface
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_agreement_brief_exposes_only_four_keys_and_skips_garbage():
    cp = _cp()
    agreement = _agreement(cp)
    brief = bpp.agreement_brief([str(agreement.pk), "мусор", str(uuid.uuid4())])
    assert brief == {str(agreement.pk): {
        "id": str(agreement.pk), "number": agreement.number, "status": "active",
        "counterparty_id": str(cp.pk)}}


# ─────────────────────────────────────────────────────────────────────────
# Заморозка «Договоров»
# ─────────────────────────────────────────────────────────────────────────

def _freeze() -> None:
    FreezeState.objects.update_or_create(
        pk=FreezeState.SINGLETON_PK, defaults={"frozen_at": timezone.now()})


@pytest.mark.django_db
def test_frozen_company_reads_old_link_but_cannot_make_new_one():
    old, cp = (contracts_helpers.make_counterparty(bin_iin="123456789012"), _cp())
    line = contracts_helpers.make_line(program=contracts_helpers.make_program(name="П"))
    old_agreement = contracts_helpers.make_agreement(line=line, counterparty=old,
                                                     number="Д-042")
    partner = _partner(cp)
    engagement = ContractorEngagement.objects.create(
        contractor=partner, site=_site(), agreement_id=old_agreement.id,
        contract_no="Д-042")
    _freeze()

    # Старая связь читается.
    resp = Client().get(f"{BASE}/contractor-engagements/", **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    [row] = resp.json()
    assert row["agreement"]["number"] == "Д-042"

    # Новая привязка к договору «Договоров» — запрещена.
    denied = _post(partner, agreement_id=old_agreement.id)
    assert denied.status_code == 409, denied.content
    assert "заморожен" in denied.json()["detail"].lower() or "перенесён" in denied.json()["detail"].lower()
    denied = patch_json(Client(), f"{BASE}/contractor-engagements/{engagement.id}/",
                        {"agreement_id": old_agreement.id + 1}, **auth(admin_token()))
    assert denied.status_code == 409

    # А договор модуля — можно.
    ok = _post(partner, bpp_agreement_id=str(_agreement(cp).pk))
    assert ok.status_code == 201, ok.content


# ─────────────────────────────────────────────────────────────────────────
# Частичный доступ и выключенный подмодуль
# ─────────────────────────────────────────────────────────────────────────

def _grant_own_agreements_only() -> None:
    """Пользователь 9 видит договоры только как их автор: узел ``bpp.agreements``
    есть, «все договоры» (``.all``) — нет."""
    auth(admin_token())
    assign(COMPANY, 9, "bpp.agreements", "view")


@pytest.mark.django_db
def test_search_and_binding_are_limited_to_agreements_the_user_may_see():
    cp = _cp()
    mine = _agreement(cp, number="ДГ-2026-000011")
    Agreement.objects.filter(pk=mine.pk).update(author_id=9)
    foreign = _agreement(cp, number="ДГ-2026-000012")        # автор 1, проект чужой
    partner = _partner(cp)
    _grant_own_agreements_only()

    found = Client().get(SEARCH, {"contractor_id": partner.id}, **auth(admin_token()))
    assert [row["id"] for row in found.json()] == [str(mine.pk)]

    denied = _post(partner, see_all=False, bpp_agreement_id=str(foreign.pk))
    assert denied.status_code == 422, denied.content
    assert "не найден" in denied.json()["detail"]
    assert not ContractorEngagement.objects.exists()

    allowed = _post(partner, see_all=False, bpp_agreement_id=str(mine.pk))
    assert allowed.status_code == 201, allowed.content


@pytest.mark.django_db
def test_binding_without_any_agreement_right_is_422():
    cp = _cp()
    agreement = _agreement(cp)
    resp = _post(_partner(cp), see_all=False, bpp_agreement_id=str(agreement.pk))
    assert resp.status_code == 422, resp.content


@pytest.mark.django_db
def test_disabled_agreements_submodule_empties_search_and_closes_binding():
    from django.core.cache import cache
    from apps.core.models import ServiceStatus

    cp = _cp()
    agreement = _agreement(cp)
    partner = _partner(cp)
    engagement = ContractorEngagement.objects.create(
        contractor=partner, site=_site(), bpp_agreement_id=str(agreement.pk),
        contract_no=agreement.number)
    auth(admin_token())
    assign(COMPANY, 9, "bpp.agreements", "view")
    assign(COMPANY, 9, "bpp.agreements.all", "view")
    ServiceStatus.objects.update_or_create(app_label="bpp_agreements",
                                           defaults={"enabled": False})
    cache.clear()

    found = Client().get(SEARCH, {"contractor_id": partner.id}, **auth(admin_token()))
    assert found.status_code == 200 and found.json() == []
    denied = _post(partner, see_all=False, bpp_agreement_id=str(agreement.pk))
    assert denied.status_code == 422 and "выключен" in denied.json()["detail"]
    # Старая привязка читается и правка соседнего поля не падает.
    listed = Client().get(f"{BASE}/contractor-engagements/", **auth(admin_token()))
    assert listed.status_code == 200 and listed.json()[0]["bpp_agreement"] is None
    ok = patch_json(Client(), f"{BASE}/contractor-engagements/{engagement.id}/",
                    {"scope": "монтаж"}, **auth(admin_token()))
    assert ok.status_code == 200, ok.content
