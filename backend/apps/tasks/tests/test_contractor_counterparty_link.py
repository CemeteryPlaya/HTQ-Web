"""Партнёр ↔ контрагент, привлечение ↔ договор.

Партнёр (``tasks.Contractor``) — это контрагент из «Договоров» в роли
исполнителя на объектах. Ссылки — голые id через границу аппок, поэтому
всё, что обычно держит FK, держат проверки сервиса; этот файл — их
исполняемая версия:

* у связанной пары один БИН/ИИН, одна организация — один партнёр;
* договор привлечения заключён с контрагентом ЭТОГО партнёра;
* связь ставится с обеих сторон: из карточки партнёра и при заведении
  контрагента «из партнёра» — во втором случае атомарно с созданием;
* выключенные «Договоры» стоят списку партнёров подписи, а не ответа.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client

from apps.contracts.models import Counterparty
from apps.contracts.tests import helpers as contracts_helpers
from apps.core.models import ServiceStatus
from apps.tasks.models import Contractor, ContractorEngagement, Site

from .helpers import BASE, admin_token, auth, patch_json, post_json

CONTRACTS = contracts_helpers.BASE


def _counterparty(bin_iin="123456789012", name="ТОО «Альфа»", **over):
    return contracts_helpers.make_counterparty(bin_iin=bin_iin, name=name, **over)


def _agreement(counterparty, number="Д-001"):
    return contracts_helpers.make_agreement(
        line=contracts_helpers.make_line(), counterparty=counterparty,
        number=number)


def _site(name="Алга") -> Site:
    return Site.objects.create(name=name)


# ─────────────────────────────────────────────────────────────────────────
# Карточка партнёра
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_partner_links_to_counterparty_and_takes_its_bin():
    cp = _counterparty()
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Альфа-Монтаж", "counterparty_id": cp.id},
                     **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["counterparty_id"] == cp.id
    assert body["counterparty"]["name"] == "ТОО «Альфа»"
    # Пустой БИН партнёра — это «не вписали», а не «другой»: номер берётся
    # у контрагента, иначе пара осталась бы неполной с первого же дня.
    assert body["bin_iin"] == "123456789012"


@pytest.mark.django_db
def test_different_bin_is_a_conflict_not_a_silent_overwrite():
    cp = _counterparty(bin_iin="123456789012")
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Альфа-Монтаж", "bin_iin": "999999999999",
                      "counterparty_id": cp.id},
                     **auth(admin_token()))
    assert resp.status_code == 409
    assert "не совпадает" in resp.json()["detail"]
    assert not Contractor.objects.exists()


@pytest.mark.django_db
def test_linked_partner_cannot_get_a_foreign_bin_later():
    cp = _counterparty()
    partner = Contractor.objects.create(name="Альфа-Монтаж",
                                        bin_iin=cp.bin_iin, counterparty_id=cp.id)
    resp = patch_json(Client(), f"{BASE}/contractors/{partner.id}/",
                      {"bin_iin": "999999999999"}, **auth(admin_token()))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_one_counterparty_is_one_partner():
    cp = _counterparty()
    Contractor.objects.create(name="Первый", counterparty_id=cp.id)
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Второй", "counterparty_id": cp.id},
                     **auth(admin_token()))
    assert resp.status_code == 409
    assert "Первый" in resp.json()["detail"]


@pytest.mark.django_db
def test_unknown_counterparty_is_404():
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Альфа-Монтаж", "counterparty_id": 987654},
                     **auth(admin_token()))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_partner_without_counterparty_is_still_allowed():
    """Связь необязательна: бригаду ставят на объект раньше, чем карточка
    контрагента согласована, а у компании может не быть «Договоров»."""
    resp = post_json(Client(), f"{BASE}/contractors/", {"name": "Сами по себе"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["counterparty"] is None


@pytest.mark.django_db
def test_unlinking_drops_engagement_agreements_but_keeps_the_number():
    cp = _counterparty()
    agreement = _agreement(cp, number="Д-777")
    partner = Contractor.objects.create(name="Альфа-Монтаж",
                                        bin_iin=cp.bin_iin, counterparty_id=cp.id)
    engagement = ContractorEngagement.objects.create(
        contractor=partner, site=_site(), agreement_id=agreement.id,
        contract_no="Д-777")

    resp = patch_json(Client(), f"{BASE}/contractors/{partner.id}/",
                      {"counterparty_id": None}, **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["counterparty"] is None

    engagement.refresh_from_db()
    # Договор был с ТЕМ контрагентом — ссылка уходит вместе со связью,
    # а номер остаётся историей привлечения.
    assert engagement.agreement_id is None
    assert engagement.contract_no == "Д-777"


# ─────────────────────────────────────────────────────────────────────────
# Привлечение по договору
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_engagement_takes_agreement_of_its_counterparty():
    cp = _counterparty()
    agreement = _agreement(cp, number="Д-042")
    partner = Contractor.objects.create(name="Альфа-Монтаж", counterparty_id=cp.id)

    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": partner.id, "site_id": _site().id,
                      "agreement_id": agreement.id, "contract_no": "что-то своё"},
                     **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["agreement"]["number"] == "Д-042"
    # Номер у привязанного договора — его: список и ссылка не расходятся.
    assert body["contract_no"] == "Д-042"


@pytest.mark.django_db
def test_agreement_with_another_counterparty_is_rejected():
    ours, theirs = _counterparty(), _counterparty(bin_iin="210987654321",
                                                  name="ТОО «Бета»")
    foreign = _agreement(theirs, number="Д-БЕТА")
    partner = Contractor.objects.create(name="Альфа-Монтаж", counterparty_id=ours.id)

    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": partner.id, "site_id": _site().id,
                      "agreement_id": foreign.id},
                     **auth(admin_token()))
    assert resp.status_code == 409
    assert not ContractorEngagement.objects.exists()


@pytest.mark.django_db
def test_agreement_needs_a_linked_partner():
    agreement = _agreement(_counterparty())
    partner = Contractor.objects.create(name="Без контрагента")
    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": partner.id, "site_id": _site().id,
                      "agreement_id": agreement.id},
                     **auth(admin_token()))
    assert resp.status_code == 409
    assert "не связан" in resp.json()["detail"]


@pytest.mark.django_db
def test_contract_no_of_a_linked_engagement_follows_the_agreement():
    cp = _counterparty()
    agreement = _agreement(cp, number="Д-100")
    partner = Contractor.objects.create(name="Альфа-Монтаж", counterparty_id=cp.id)
    engagement = ContractorEngagement.objects.create(
        contractor=partner, site=_site(), agreement_id=agreement.id,
        contract_no="Д-100")

    resp = patch_json(Client(), f"{BASE}/contractor-engagements/{engagement.id}/",
                      {"contract_no": "другой"}, **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["contract_no"] == "Д-100"


# ─────────────────────────────────────────────────────────────────────────
# Выключенные «Договоры»
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_partner_list_survives_disabled_contracts():
    cp = _counterparty()
    Contractor.objects.create(name="Альфа-Монтаж", counterparty_id=cp.id)
    ServiceStatus.objects.update_or_create(app_label="contracts",
                                           defaults={"enabled": False})
    cache.clear()

    resp = Client().get(f"{BASE}/contractors/", **auth(admin_token()))
    assert resp.status_code == 200
    [row] = resp.json()
    # Связь есть — показать её нечем. Не 503 на весь список.
    assert row["counterparty_id"] == cp.id
    assert row["counterparty"] is None


@pytest.mark.django_db
def test_editing_linked_partner_does_not_need_contracts():
    """Форма шлёт карточку целиком, включая неизменные БИН и связь. Правка
    телефона не касается связи и не должна упираться в выключенный модуль."""
    cp = _counterparty()
    partner = Contractor.objects.create(name="Альфа-Монтаж", bin_iin=cp.bin_iin,
                                        counterparty_id=cp.id)
    ServiceStatus.objects.update_or_create(app_label="contracts",
                                           defaults={"enabled": False})
    cache.clear()

    resp = patch_json(Client(), f"{BASE}/contractors/{partner.id}/",
                      {"phone": "+77010000000", "bin_iin": cp.bin_iin,
                       "counterparty_id": cp.id},
                      **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json()["phone"] == "+77010000000"


@pytest.mark.django_db
def test_linking_with_disabled_contracts_is_503_not_a_blind_write():
    cp = _counterparty()
    ServiceStatus.objects.update_or_create(app_label="contracts",
                                           defaults={"enabled": False})
    cache.clear()

    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Альфа-Монтаж", "counterparty_id": cp.id},
                     **auth(admin_token()))
    assert resp.status_code == 503
    assert not Contractor.objects.exists()


# ─────────────────────────────────────────────────────────────────────────
# Сторона «Договоров»
# ─────────────────────────────────────────────────────────────────────────

def _full_body(**over) -> dict:
    body = {"bin_iin": "123456789012", "name": "ТОО «Альфа»",
            "country": {"id": contracts_helpers.make_country().id}}
    body.update(over)
    return body


@pytest.mark.django_db
def test_counterparty_created_from_partner_is_linked():
    partner = Contractor.objects.create(name="Альфа-Монтаж", bin_iin="123456789012")
    resp = post_json(Client(), f"{CONTRACTS}/counterparties/full",
                     _full_body(contractor_id=partner.id),
                     **auth(contracts_helpers.token()))
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["contractor"] == {"id": partner.id, "name": "Альфа-Монтаж",
                                  "status": "active"}

    partner.refresh_from_db()
    assert partner.counterparty_id == body["id"]

    card = Client().get(f"{CONTRACTS}/counterparties/{body['id']}",
                        **auth(contracts_helpers.token()))
    assert card.json()["contractor"]["id"] == partner.id


@pytest.mark.django_db
def test_failed_link_rolls_back_the_new_counterparty():
    """«Завести из партнёра» с чужим БИН — ни контрагента, ни связи:
    полдела хуже, чем честный отказ."""
    partner = Contractor.objects.create(name="Альфа-Монтаж", bin_iin="999999999999")
    resp = post_json(Client(), f"{CONTRACTS}/counterparties/full",
                     _full_body(contractor_id=partner.id),
                     **auth(contracts_helpers.token()))
    assert resp.status_code == 409
    assert not Counterparty.objects.exists()


@pytest.mark.django_db
def test_partner_is_not_silently_taken_from_another_counterparty():
    other = _counterparty(bin_iin="210987654321", name="ТОО «Бета»")
    partner = Contractor.objects.create(name="Бета-Монтаж", counterparty_id=other.id)
    resp = post_json(Client(), f"{CONTRACTS}/counterparties/full",
                     _full_body(contractor_id=partner.id),
                     **auth(contracts_helpers.token()))
    assert resp.status_code == 409
    partner.refresh_from_db()
    assert partner.counterparty_id == other.id


@pytest.mark.django_db
def test_deleting_counterparty_unlinks_the_partner():
    cp = _counterparty()
    partner = Contractor.objects.create(name="Альфа-Монтаж", counterparty_id=cp.id)
    resp = Client().delete(f"{CONTRACTS}/counterparties/{cp.id}",
                           **auth(contracts_helpers.admin_token()))
    assert resp.status_code == 204
    partner.refresh_from_db()
    assert partner.counterparty_id is None
