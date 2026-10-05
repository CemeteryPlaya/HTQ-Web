"""Ручки справочника «Контрагенты» ``/api/bpp/v1/counterparties…`` (A2.3):
права по узлам, 404 на неверный UUID, идемпотентность, реестр L-08."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.bpp.models.counterparties import Counterparty
from apps.bpp.tests import stage2 as s
from htqweb.tenancy.db import use_company

from . import common

BASE = "/api/bpp/v1/counterparties"
FD, BUH, SN, TD, NOBODY = 921, 922, 923, 924, 925


def _post(client, url, body, headers):
    return client.post(url, json.dumps(body), **headers)


def _patch(client, url, body, headers):
    return client.patch(url, json.dumps(body), **headers)


@pytest.fixture
def slug(company_context):
    common.countries()
    slug = company_context["slug"]
    s.grant(slug, FD, "bpp-fd")
    s.grant(slug, BUH, "bpp-buh")
    s.grant(slug, SN, "bpp-sn")
    s.grant(slug, TD, "bpp-td")
    s.user(NOBODY)
    return slug


@pytest.mark.django_db
def test_without_role_is_403(slug):
    client = Client()
    assert client.get(BASE, **s.auth(slug, NOBODY)).status_code == 403
    response = _post(client, BASE, common.data(common.bin_first_pass()), s.auth(slug, NOBODY))
    assert response.status_code == 403


@pytest.mark.django_db
def test_sn_creates_but_does_not_block(slug):
    client = Client()
    created = _post(client, BASE, common.data(common.bin_first_pass()), s.auth(slug, SN))
    assert created.status_code == 201, created.json()
    card = created.json()
    assert card["status"] == "active" and card["is_verified"] is False
    assert card["allowed_actions"] == []  # СН не правит и не блокирует
    url = f"{BASE}/{card['id']}"
    blocked = _post(client, f"{url}/block",
                    {"version": card["version"], "reason": "нет оригиналов документов"},
                    s.auth(slug, SN))
    assert blocked.status_code == 403 and blocked.json()["code"] == "E-ACC-01"
    assert _patch(client, url, {"phone": "1"}, s.auth(slug, SN)).status_code == 403
    assert _post(client, f"{url}/verified", {"verified": True},
                 s.auth(slug, SN)).status_code == 403

    # ФД блокирует; ТД (только просмотр справочника) не создаёт.
    fd = _post(client, f"{url}/block",
               {"version": card["version"], "reason": "нет оригиналов документов"},
               s.auth(slug, FD))
    assert fd.status_code == 200, fd.json()
    assert fd.json()["status"] == "blocked" and "unblock" in fd.json()["allowed_actions"]
    td = _post(client, BASE, common.data(common.bin_second_pass()), s.auth(slug, TD))
    assert td.status_code == 403


@pytest.mark.django_db
def test_invalid_uuid_is_404(slug):
    client = Client()
    for url in (f"{BASE}/not-a-uuid", f"{BASE}/123/", f"{BASE}/123/accounts",
                f"{BASE}/accounts/123"):
        response = (client.get(url, **s.auth(slug, FD)) if "accounts/123" not in url
                    else _patch(client, url, {"bank_name": "x"}, s.auth(slug, FD)))
        assert response.status_code == 404, url
        assert "detail" in response.json()
    missing = client.get(f"{BASE}/00000000-0000-0000-0000-000000000000", **s.auth(slug, FD))
    assert missing.status_code == 404


@pytest.mark.django_db
def test_repeat_with_same_idempotency_key_creates_once(slug):
    client = Client()
    headers = {**s.auth(slug, BUH), "HTTP_IDEMPOTENCY_KEY": "cp-create-1"}
    body = common.data(common.bin_first_pass())
    first = _post(client, BASE, body, headers)
    again = _post(client, BASE, body, headers)
    assert first.status_code == 201, first.json()
    assert again.status_code == 201 and again["Idempotent-Replay"] == "true"
    assert again.json()["id"] == first.json()["id"]
    with use_company(slug):  # запрос вернул search_path в public
        assert Counterparty.objects.count() == 1
    # Без ключа повтор — это второй запрос: дубль отвечает 422 со ссылкой.
    dup = _post(client, BASE, body, s.auth(slug, BUH))
    assert dup.status_code == 422
    assert dup.json()["code"] == "E-CTR-02"
    assert dup.json()["fields"][0]["existing_id"] == first.json()["id"]


@pytest.mark.django_db
def test_patch_with_stale_version_is_409(slug):
    client = Client()
    card = _post(client, BASE, common.data(common.bin_first_pass()), s.auth(slug, BUH)).json()
    url = f"{BASE}/{card['id']}"
    ok = _patch(client, url, {"version": card["version"], "phone": "1"}, s.auth(slug, BUH))
    assert ok.status_code == 200 and ok.json()["version"] == card["version"] + 1
    stale = _patch(client, url, {"version": card["version"], "phone": "2"}, s.auth(slug, FD))
    assert stale.status_code == 409 and stale.json()["code"] == "E-CON-01"


@pytest.mark.django_db
def test_invalid_bin_is_422_e_ctr_03(slug):
    body = common.data(common.bin_body_ten_twice() + "0")
    response = _post(Client(), BASE, body, s.auth(slug, FD))
    assert response.status_code == 422 and response.json()["code"] == "E-CTR-03"


@pytest.mark.django_db
def test_taken_ext_1c_ref_is_422_on_post_and_patch(slug):
    """Занятый «Код в 1С» — 422 с полем ext_1c_ref, а не 500."""
    guid = "0f8fad5b-d9cb-469f-a165-70867728950e"
    first, second, third = common.valid_bins(3)
    client = Client()
    assert _post(client, BASE, common.data(first, ext_1c_ref=guid), s.auth(slug, FD)).status_code == 201
    dup = _post(client, BASE, common.data(second, ext_1c_ref=guid), s.auth(slug, FD))
    assert dup.status_code == 422 and dup.json()["fields"][0]["field"] == "ext_1c_ref"
    other = _post(client, BASE, common.data(third), s.auth(slug, FD)).json()
    patched = _patch(client, f"{BASE}/{other['id']}",
                     {"version": other["version"], "ext_1c_ref": guid.upper()}, s.auth(slug, FD))
    assert patched.status_code == 422 and patched.json()["fields"][0]["field"] == "ext_1c_ref"


@pytest.mark.django_db
def test_registry_search_filters_and_page_size(slug):
    client = Client()
    numbers = common.valid_bins(2)
    for number, name in zip(numbers, ("ТОО Альфа", "ТОО Бета")):
        assert _post(client, BASE, common.data(number, name=name, short_name=""),
                     s.auth(slug, FD)).status_code == 201
    assert _post(client, BASE, common.data("7707083893", name="ПАО Гамма", kind="nonresident",
                                           country_code="RU"),
                 s.auth(slug, FD)).status_code == 201

    page = client.get(BASE, **s.auth(slug, SN)).json()
    assert set(page) == {"items", "total", "page", "page_size"}
    assert (page["total"], page["page"], page["page_size"]) == (3, 1, 50)
    assert [row["name"] for row in page["items"]] == ["ПАО Гамма", "ТОО Альфа", "ТОО Бета"]

    by_name = client.get(BASE, {"q": "Бет"}, **s.auth(slug, SN)).json()
    assert [row["name"] for row in by_name["items"]] == ["ТОО Бета"]
    spaced = f"{numbers[0][:4]} {numbers[0][4:]}"
    by_number = client.get(BASE, {"q": spaced}, **s.auth(slug, SN)).json()
    assert [row["reg_number"] for row in by_number["items"]] == [numbers[0]]
    by_country = client.get(BASE, {"country": "RU"}, **s.auth(slug, SN)).json()
    assert [row["name"] for row in by_country["items"]] == ["ПАО Гамма"]
    assert client.get(BASE, {"status": "blocked"}, **s.auth(slug, SN)).json()["total"] == 0
    assert client.get(BASE, {"page_size": 25}, **s.auth(slug, SN)).json()["page_size"] == 25
    assert client.get(BASE, {"page_size": 30}, **s.auth(slug, SN)).json()["page_size"] == 50
    assert client.get(BASE, {"page": "x"}, **s.auth(slug, SN)).status_code == 422


@pytest.mark.django_db
def test_accounts_endpoints(slug):
    client = Client()
    card = _post(client, BASE, common.data(common.bin_first_pass()), s.auth(slug, FD)).json()
    url = f"{BASE}/{card['id']}/accounts"
    iban = common.kz_iban("125KZT5004100100")
    bad = _post(client, url, {"iban": "KZ00125KZT5004100100", "bic": "HSBKKZKX"},
                s.auth(slug, BUH))
    assert bad.status_code == 422 and bad.json()["code"] == "E-CTR-04"
    assert _post(client, url, {"iban": iban, "bic": "HSBKKZKX"},
                 s.auth(slug, SN)).status_code == 403
    created = _post(client, url, {"iban": iban, "bic": "HSBKKZKX"}, s.auth(slug, BUH))
    assert created.status_code == 201, created.json()
    account = created.json()
    assert account["is_primary"] is True
    listed = client.get(url, **s.auth(slug, SN))
    assert [row["iban"] for row in listed.json()] == [iban]
    patched = _patch(client, f"{BASE}/accounts/{account['id']}", {"bank_name": "Халык"},
                     s.auth(slug, BUH))
    assert patched.status_code == 200 and patched.json()["bank_name"] == "Халык"
