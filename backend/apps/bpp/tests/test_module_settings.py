"""Параметры модуля — ``/api/bpp/v1/settings…`` (вкладка «Параметры модуля»
экрана «Настройки»): умолчание без строки, запись с журналом, проверка
значения E-VAL-01, служебный ключ — 404, права по узлу ``bpp.settings``, и
новый порог действительно меняет метку «Проверенный» у контрагента."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.bpp.models import AuditLog
from apps.bpp.models.settings import ModuleSetting
from apps.bpp.services.budget.check import RESULT_KEY
from apps.bpp.services.core import settings as module_settings
from apps.bpp.services.counterparties import lookup, service as counterparties
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.counterparties import common
from htqweb.tenancy.db import use_company

ADM, FD, TD = 941, 942, 943
URL = "/api/bpp/v1/settings"
KEY = "counterparty_verified_threshold"


@pytest.fixture
def slug(company_context):
    slug = company_context["slug"]
    s.grant(slug, ADM, "bpp-adm")
    s.grant(slug, FD, "bpp-fd")
    s.grant(slug, TD, "bpp-td")
    return slug


def _patch(client, key, body, headers):
    return client.patch(f"{URL}/{key}", json.dumps(body), **headers)


def test_every_editable_param_has_a_default():
    """Строки в таблице может не быть — тогда значение берётся из умолчаний,
    и параметра без умолчания в реестре быть не должно."""
    assert set(module_settings.EDITABLE) <= set(module_settings.DEFAULTS)
    assert RESULT_KEY not in module_settings.EDITABLE


@pytest.mark.django_db
def test_list_shows_default_when_unset(slug):
    response = Client().get(URL, **s.auth(slug, FD))
    assert response.status_code == 200, response.content
    params = {item["key"]: item for item in response.json()}
    assert list(params) == [KEY]  # служебного ключа сверки в списке нет
    item = params[KEY]
    assert (item["value"], item["default"], item["kind"]) == (3, 3, "integer")
    assert (item["min"], item["max"], item["updated_at"]) == (1, 100, None)
    assert "Проверенный" in item["label"] and item["help"]


@pytest.mark.django_db
def test_list_hides_system_rows_written_by_the_module(slug):
    ModuleSetting.objects.create(key=RESULT_KEY, value={"at": "2026-09-29T00:00:00+00:00",
                                                        "count": 0})
    keys = [item["key"] for item in Client().get(URL, **s.auth(slug, ADM)).json()]
    assert keys == [KEY]


@pytest.mark.django_db
def test_patch_persists_and_writes_audit(slug):
    client = Client()
    response = _patch(client, KEY, {"value": 5}, s.auth(slug, ADM))
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["key"], body["value"], body["default"]) == (KEY, 5, 3)
    assert body["updated_at"]
    with use_company(slug):  # запрос вернул search_path в public
        row = ModuleSetting.objects.get(pk=KEY)
        assert (row.value, row.updated_by) == (5, ADM)
        audit = AuditLog.objects.get(object_type="bpp.modulesetting", object_id=KEY)
        assert audit.action == "updated" and audit.actor_id == ADM
        assert audit.changes == {"value": [3, 5]}
    listed = client.get(URL, **s.auth(slug, FD)).json()
    assert listed[0]["value"] == 5

    # То же значение ещё раз — без второй строки журнала.
    assert _patch(client, KEY, {"value": 5}, s.auth(slug, ADM)).status_code == 200
    with use_company(slug):
        assert AuditLog.objects.filter(object_type="bpp.modulesetting").count() == 1

    # Журнал параметра читает тот, кто видит параметры; ТД — как несуществующий.
    history = client.get(f"/api/bpp/v1/history/bpp.modulesetting/{KEY}", **s.auth(slug, FD))
    assert history.status_code == 200, history.content
    assert client.get(f"/api/bpp/v1/history/bpp.modulesetting/{KEY}",
                      **s.auth(slug, TD)).status_code == 404


@pytest.mark.django_db
def test_repeat_patch_with_same_idempotency_key_replays(slug):
    client = Client()
    headers = {**s.auth(slug, ADM), "HTTP_IDEMPOTENCY_KEY": "module-param-1"}
    first = _patch(client, KEY, {"value": 7}, headers)
    again = _patch(client, KEY, {"value": 7}, headers)
    assert first.status_code == 200, first.content
    assert again.status_code == 200 and again["Idempotent-Replay"] == "true"
    assert again.json() == first.json()


@pytest.mark.django_db
@pytest.mark.parametrize("value", [0, 101, -1, 2.5, "5", True, None, [5]])
def test_bad_value_is_422_e_val_01(slug, value):
    client = Client()
    response = _patch(client, KEY, {"value": value}, s.auth(slug, ADM))
    assert response.status_code == 422, response.content
    body = response.json()
    assert body["code"] == "E-VAL-01" and body["fields"][0]["field"] == "value"
    assert "от 1 до 100" in body["detail"]
    with use_company(slug):
        assert not ModuleSetting.objects.filter(pk=KEY).exists()
        assert not AuditLog.objects.filter(object_type="bpp.modulesetting").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("key", [RESULT_KEY, "no_such_param"])
def test_system_or_unknown_key_is_404(slug, key):
    response = _patch(Client(), key, {"value": 5}, s.auth(slug, ADM))
    assert response.status_code == 404, response.content
    assert response.json()["code"] == "E-NOT-FOUND"
    with use_company(slug):
        assert not ModuleSetting.objects.filter(pk=key).exists()


@pytest.mark.django_db
def test_rights_view_for_fd_edit_only_for_adm(slug):
    client = Client()
    # ФД видит параметры (bpp.settings — просмотр), но не правит.
    assert client.get(URL, **s.auth(slug, FD)).status_code == 200
    denied = _patch(client, KEY, {"value": 5}, s.auth(slug, FD))
    assert denied.status_code == 403 and denied.json()["code"] == "E-ACC-01"
    # ТД узла bpp.settings не имеет вовсе: ни чтения, ни правки.
    read = client.get(URL, **s.auth(slug, TD))
    assert read.status_code == 403 and read.json()["code"] == "E-ACC-01"
    assert _patch(client, KEY, {"value": 5}, s.auth(slug, TD)).status_code == 403
    with use_company(slug):
        assert not ModuleSetting.objects.filter(pk=KEY).exists()


@pytest.mark.django_db
def test_new_threshold_drives_the_verified_mark(slug):
    common.countries()
    cp = counterparties.create(common.data(common.bin_first_pass()), actor_id=FD)
    for _ in range(3):
        lookup.record_success(cp.pk)
    cp.refresh_from_db()
    assert lookup.is_verified(cp)  # умолчание — 3 удачных документа

    client = Client()
    assert _patch(client, KEY, {"value": 4}, s.auth(slug, ADM)).status_code == 200
    with use_company(slug):
        cp.refresh_from_db()
        assert lookup.verified_threshold() == 4
        assert not lookup.is_verified(cp)
        assert lookup.needs_confirmation(cp.pk)
        lookup.record_success(cp.pk)
        cp.refresh_from_db()
        assert lookup.is_verified(cp)
