"""Счета организации и шаблоны выписок — справочник АДМ (ТЗ §11.1, §18,
задача A3.1): проверки IBAN, дубль E-BNK-01, права, архив вместо удаления,
версия, журнал."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.bpp.models import AuditLog
from apps.bpp.models.bank import OrgBankAccount, StatementTemplate
from apps.bpp.services.bank import settings as service
from apps.bpp.tests import stage2 as s
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

from . import common

ADM, FD, BUH, TD = 931, 932, 933, 934
BANK = "/api/bpp/v1/bank"


def _error(fn, *args, **kwargs) -> DomainError:
    with pytest.raises(DomainError) as exc:
        fn(*args, **kwargs)
    return exc.value


def _template(**over) -> StatementTemplate:
    data = {"name": "Halyk Excel", "format": "xlsx", "columns": dict(common.HEADERS), **over}
    return service.create_template(data, actor_id=ADM)


def _account(tpl: StatementTemplate, n: int = 1, **over) -> OrgBankAccount:
    data = {"iban": common.iban(n), "bank_name": "Halyk Bank", "bic": "HSBKKZKX",
            "currency": "KZT", "template_id": str(tpl.pk), **over}
    return service.create_account(data, actor_id=ADM)


@pytest.fixture
def slug(company_context):
    slug = company_context["slug"]
    s.grant(slug, ADM, "bpp-adm")
    s.grant(slug, FD, "bpp-fd")
    s.grant(slug, BUH, "bpp-buh")
    s.grant(slug, TD, "bpp-td")
    return slug


def _post(client, url, body, headers):
    return client.post(url, json.dumps(body), **headers)


def _patch(client, url, body, headers):
    return client.patch(url, json.dumps(body), **headers)


# ── шаблон: правила ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_template_defaults_encoding_by_format_and_writes_audit(company_context):
    xlsx = _template()
    csv = _template(name="Kaspi CSV", format="csv")
    onec = _template(name="1С", format="onec", columns={})
    assert (xlsx.encoding, csv.encoding, onec.encoding) == ("utf-8", "cp1251", "cp1251")
    assert xlsx.version == 1 and xlsx.is_active
    row = AuditLog.objects.get(object_type="bpp.statementtemplate", object_id=str(xlsx.pk))
    assert row.action == "created" and row.changes["format"] == "xlsx"


@pytest.mark.django_db
@pytest.mark.parametrize(("over", "field"), [
    ({"columns": {"date": "Дата", "doc_number": "№", "amount": "Сумма"}}, "columns"),
    ({"columns": {**common.HEADERS, "bogus": "Что-то"}}, "columns"),
    ({"columns": {**common.HEADERS, "purpose": "  "}}, "columns"),
    ({"columns": {**common.HEADERS, "purpose": "сумма"}}, "columns"),   # тот же заголовок
    ({"amount_mode": "split"}, "columns"),                             # нет дебета и кредита
    ({"format": "pdf"}, "format"),
    ({"encoding": "klingon-8"}, "encoding"),
    ({"encoding": "rot13"}, "encoding"),            # кодек есть, но не текстовый
    ({"encoding": "hex"}, "encoding"),
    ({"format": "csv", "delimiter": ""}, "delimiter"),
    ({"date_format": "ММ.ГГГГ"}, "date_format"),
    ({"name": " "}, "name"),
])
def test_template_rules(company_context, over, field):
    err = _error(_template, **over)
    assert err.code == "E-VAL-01" and err.fields[0]["field"] == field


@pytest.mark.django_db
def test_split_template_with_debit_and_credit_is_fine(company_context):
    columns = {k: v for k, v in common.HEADERS.items() if k != "amount"}
    tpl = _template(amount_mode="split",
                    columns={**columns, "debit": "Дебет", "credit": "Кредит"})
    assert tpl.amount_mode == "split"


@pytest.mark.django_db
def test_template_in_use_is_not_archived(company_context):
    tpl = _template()
    _account(tpl)
    err = _error(service.update_template, tpl.pk, {"is_active": False},
                 expected_version=tpl.version, actor_id=ADM)
    assert err.code == "E-STATE-01" and err.status == 409
    # Архивный счёт шаблон не держит.
    account = OrgBankAccount.objects.get(template=tpl)
    service.update_account(account.pk, {"is_active": False}, expected_version=1, actor_id=ADM)
    archived = service.update_template(tpl.pk, {"is_active": False},
                                       expected_version=tpl.version, actor_id=ADM)
    assert archived.is_active is False and archived.version == 2


# ── счёт организации: правила ──────────────────────────────────────────

@pytest.mark.django_db
def test_account_iban_is_normalized_and_checked(company_context):
    tpl = _template()
    number = common.iban(1)
    account = _account(tpl, iban=f"{number[:4].lower()} {number[4:12]} {number[12:]}")
    assert account.iban == number and account.bic == "HSBKKZKX"
    broken = number[:-1] + ("0" if number[-1] != "0" else "1")
    err = _error(_account, tpl, 2, iban=broken)
    assert err.status == 422 and err.fields[0]["field"] == "iban"


@pytest.mark.django_db
def test_account_duplicate_iban_is_e_bnk_01_even_archived(company_context):
    tpl = _template()
    first = _account(tpl)
    service.update_account(first.pk, {"is_active": False}, expected_version=1, actor_id=ADM)
    err = _error(_account, tpl)
    assert err.code == "E-BNK-01" and err.status == 422
    assert common.iban(1) in err.message and "архив" in err.message
    assert err.fields[0]["existing_id"] == str(first.pk)


@pytest.mark.django_db
def test_account_duplicate_iban_race_is_e_bnk_01_not_500(company_context, monkeypatch):
    """Предварительная проверка пропустила (как у проигравшего гонку) —
    уникальный ключ БД превращается в E-BNK-01."""
    tpl = _template()
    _account(tpl)
    monkeypatch.setattr(service, "_existing_account", lambda iban, exclude_id=None: None)
    err = _error(_account, tpl)
    assert err.code == "E-BNK-01"


@pytest.mark.django_db
def test_account_needs_active_template(company_context):
    tpl = _template()
    service.update_template(tpl.pk, {"is_active": False}, expected_version=1, actor_id=ADM)
    err = _error(_account, tpl)
    assert err.code == "E-VAL-01" and err.fields[0]["field"] == "template_id"


@pytest.mark.django_db
def test_account_version_conflict_is_e_con_01(company_context):
    account = _account(_template())
    service.update_account(account.pk, {"bank_name": "Народный банк"}, expected_version=1,
                           actor_id=ADM)
    err = _error(service.update_account, account.pk, {"bank_name": "Другой"},
                 expected_version=1, actor_id=ADM)
    assert err.code == "E-CON-01" and err.status == 409


# ── ручки и права ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_adm_creates_fd_and_buh_read_only(slug):
    client = Client()
    tpl = _post(client, f"{BANK}/templates",
                {"name": "Halyk Excel", "format": "xlsx", "columns": common.HEADERS},
                s.auth(slug, ADM))
    assert tpl.status_code == 201, tpl.json()
    tpl_id = tpl.json()["id"]
    body = {"iban": common.iban(1), "bank_name": "Halyk Bank", "bic": "HSBKKZKX",
            "template_id": tpl_id}
    created = _post(client, f"{BANK}/accounts", body, s.auth(slug, ADM))
    assert created.status_code == 201, created.json()
    card = created.json()
    assert card["template"] == {"id": tpl_id, "name": "Halyk Excel", "format": "xlsx"}
    assert card["currency"] == "KZT" and card["version"] == 1

    # ФД (bpp.settings — только просмотр) и БУХ (bpp.bank — просмотр) читают,
    # но не правят.
    for user_id in (FD, BUH):
        listed = client.get(f"{BANK}/accounts", **s.auth(slug, user_id))
        assert listed.status_code == 200 and [a["id"] for a in listed.json()] == [card["id"]]
        assert client.get(f"{BANK}/templates/{tpl_id}", **s.auth(slug, user_id)).status_code == 200
        body2 = {**body, "iban": common.iban(2)}
        denied = _post(client, f"{BANK}/accounts", body2, s.auth(slug, user_id))
        assert denied.status_code == 403 and denied.json()["code"] == "E-ACC-01"
        patched = _patch(client, f"{BANK}/accounts/{card['id']}", {"bank_name": "x"},
                         s.auth(slug, user_id))
        assert patched.status_code == 403
        assert _patch(client, f"{BANK}/templates/{tpl_id}", {"name": "x"},
                      s.auth(slug, user_id)).status_code == 403

    # ТД — ни счетов, ни шаблонов.
    assert client.get(f"{BANK}/accounts", **s.auth(slug, TD)).status_code == 403
    assert client.get(f"{BANK}/templates", **s.auth(slug, TD)).status_code == 403


@pytest.mark.django_db
def test_api_invalid_iban_and_duplicate(slug):
    client = Client()
    tpl = _template()
    body = {"iban": "KZ00" + "1" * 16, "bic": "HSBKKZKX", "template_id": str(tpl.pk)}
    bad = _post(client, f"{BANK}/accounts", body, s.auth(slug, ADM))
    assert bad.status_code == 422 and bad.json()["fields"][0]["field"] == "iban"
    good = {**body, "iban": common.iban(3)}
    assert _post(client, f"{BANK}/accounts", good, s.auth(slug, ADM)).status_code == 201
    dup = _post(client, f"{BANK}/accounts", good, s.auth(slug, ADM))
    assert dup.status_code == 422 and dup.json()["code"] == "E-BNK-01"


@pytest.mark.django_db
def test_archived_account_is_not_offered_for_import(slug):
    """``?active=1`` — список для формы загрузки: архивных счетов в нём нет,
    в справочнике АДМ (без фильтра) они есть."""
    client = Client()
    tpl = _template()
    live, old = _account(tpl, 1), _account(tpl, 2)
    archived = _patch(client, f"{BANK}/accounts/{old.pk}", {"version": 1, "is_active": False},
                      s.auth(slug, ADM))
    assert archived.status_code == 200, archived.json()
    assert archived.json()["is_active"] is False and archived.json()["version"] == 2
    active = client.get(f"{BANK}/accounts?active=1", **s.auth(slug, FD)).json()
    assert [a["id"] for a in active] == [str(live.pk)]
    everything = client.get(f"{BANK}/accounts", **s.auth(slug, FD)).json()
    assert {a["id"] for a in everything} == {str(live.pk), str(old.pk)}

    # Шаблоны — так же.
    with use_company(slug):  # запрос вернул search_path в public
        other = _template(name="Запасной")
    retired = _patch(client, f"{BANK}/templates/{other.pk}", {"version": 1, "is_active": False},
                     s.auth(slug, ADM))
    assert retired.status_code == 200, retired.json()
    names = [t["name"] for t in client.get(f"{BANK}/templates?active=1",
                                           **s.auth(slug, ADM)).json()]
    assert names == ["Halyk Excel"]


@pytest.mark.django_db
def test_patch_stale_version_is_409_and_bad_uuid_404(slug):
    client = Client()
    account = _account(_template())
    url = f"{BANK}/accounts/{account.pk}"
    assert _patch(client, url, {"version": 1, "bank_name": "Народный"},
                  s.auth(slug, ADM)).status_code == 200
    stale = _patch(client, url, {"version": 1, "bank_name": "Другой"}, s.auth(slug, ADM))
    assert stale.status_code == 409 and stale.json()["code"] == "E-CON-01"
    for bad in (f"{BANK}/accounts/not-a-uuid", f"{BANK}/templates/123",
                f"{BANK}/templates/123/preview"):
        method = client.post if bad.endswith("preview") else client.get
        assert method(bad, **s.auth(slug, ADM)).status_code == 404, bad


@pytest.mark.django_db
def test_history_of_account_is_readable_by_bank_viewer(slug):
    account = _account(_template())
    client = Client()
    url = f"/api/bpp/v1/history/bpp.orgbankaccount/{account.pk}"
    history = client.get(url, **s.auth(slug, BUH))
    assert history.status_code == 200, history.content
    assert client.get(url, **s.auth(slug, TD)).status_code == 404  # как несуществующий


@pytest.mark.django_db
def test_repeat_account_create_with_same_idempotency_key_creates_once(slug):
    tpl = _template()
    client = Client()
    headers = {**s.auth(slug, ADM), "HTTP_IDEMPOTENCY_KEY": "org-account-1"}
    body = {"iban": common.iban(5), "bank_name": "Halyk Bank", "bic": "HSBKKZKX",
            "template_id": str(tpl.pk)}
    first = _post(client, f"{BANK}/accounts", body, headers)
    again = _post(client, f"{BANK}/accounts", body, headers)
    assert first.status_code == 201, first.json()
    assert again.status_code == 201 and again["Idempotent-Replay"] == "true"
    assert again.json() == first.json()
    with use_company(slug):  # запрос вернул search_path в public
        assert OrgBankAccount.objects.count() == 1
        assert AuditLog.objects.filter(object_type="bpp.orgbankaccount",
                                       action="created").count() == 1
    # Без ключа повтор — второй запрос: дубль IBAN отвечает E-BNK-01.
    dup = _post(client, f"{BANK}/accounts", body, s.auth(slug, ADM))
    assert dup.status_code == 422 and dup.json()["code"] == "E-BNK-01"
    assert dup.json()["fields"][0]["existing_id"] == first.json()["id"]
