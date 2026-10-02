"""Клиент OData 1С (A7.3, D-38, D-S7-5): транспорт, безопасность, постраничность.

Сеть не трогается — ``httpx.MockTransport``. Пароль не должен попадать ни в
логи, ни в ``repr``, ни в тексты исключений.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from htqweb.integrations import onec

PASSWORD = "p@ss-S3CRET-w0rd"
BASE = "https://onec.example.kz/odata/standard.odata"
REPO = Path(__file__).resolve().parents[3]


def _client(handler, **over) -> onec.OneCClient:
    kwargs = {"user": "integration", "password": PASSWORD,
              "transport": httpx.MockTransport(handler), "page_size": 2}
    kwargs.update(over)
    return onec.OneCClient(BASE, **kwargs)


def _json(payload, status=200):
    return httpx.Response(status, json=payload)


# ── защита адреса ───────────────────────────────────────────────────────

def test_empty_url_is_disabled():
    with pytest.raises(onec.OneCDisabled):
        onec.OneCClient("", user="u", password="p")


def test_http_is_refused_without_flag_and_allowed_with_it():
    with pytest.raises(onec.OneCConfigError):
        onec.OneCClient("http://onec.example.kz/odata", user="u", password="p")
    assert onec.OneCClient("http://onec.example.kz/odata", user="u", password="p",
                           allow_http=True)


def test_userinfo_in_url_is_refused_without_echoing_it():
    with pytest.raises(onec.OneCConfigError) as exc:
        onec.OneCClient("https://admin:topsecret@onec.example.kz/odata", user="u", password="p")
    assert "topsecret" not in str(exc.value)


@pytest.mark.parametrize("url", ["ftp://onec.example.kz/odata", "https:///odata", "onec.example.kz"])
def test_other_schemes_and_hostless_urls_are_refused(url):
    with pytest.raises(onec.OneCConfigError):
        onec.OneCClient(url, user="u", password="p")


def test_entity_set_name_is_validated():
    client = _client(lambda request: _json({"value": []}))
    with pytest.raises(ValueError):
        list(client.iter_entities("Catalog_X/../secret"))


# ── чтение ──────────────────────────────────────────────────────────────

def test_paging_reads_until_a_short_page_and_sends_basic_auth():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        skip = int(request.url.params["$skip"])
        rows = [{"Ref_Key": str(n)} for n in range(5)][skip:skip + int(request.url.params["$top"])]
        return _json({"value": rows})

    rows = list(_client(handler).iter_entities("Catalog_Контрагенты"))
    assert [r["Ref_Key"] for r in rows] == ["0", "1", "2", "3", "4"]
    assert [r.url.params["$skip"] for r in seen] == ["0", "2", "4"]
    assert all(r.url.params["$format"] == "json" for r in seen)
    assert all(r.url.params["$orderby"] == "Ref_Key" for r in seen)
    assert all(r.headers["authorization"].startswith("Basic ") for r in seen)


def test_page_limit_stops_a_runaway_source():
    client = _client(lambda request: _json({"value": [{"a": 1}, {"a": 2}]}), max_pages=3)
    with pytest.raises(onec.OneCUnavailable):
        list(client.iter_entities("Catalog_X"))


def test_oversized_response_is_refused():
    client = _client(lambda request: httpx.Response(200, content=b"x" * 5000), max_bytes=1000)
    with pytest.raises(onec.OneCUnavailable):
        list(client.iter_entities("Catalog_X"))


def test_odata_error_body_becomes_odata_error():
    body = {"odata.error": {"code": "-1", "message": {"lang": "ru", "value": "Нет такой сущности"}}}
    client = _client(lambda request: _json(body, 500))
    with pytest.raises(onec.OneCODataError) as exc:
        list(client.iter_entities("Catalog_X"))
    assert "Нет такой сущности" in str(exc.value) and exc.value.code == "-1"


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_is_unavailable_and_does_not_leak_password(status):
    client = _client(lambda request: httpx.Response(status, text="denied"))
    with pytest.raises(onec.OneCUnavailable) as exc:
        list(client.iter_entities("Catalog_X"))
    assert PASSWORD not in str(exc.value) and PASSWORD not in repr(exc.value)


def test_timeout_is_unavailable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(onec.OneCUnavailable):
        list(_client(handler).iter_entities("Catalog_X"))


def test_redirect_is_not_followed():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "evil" in request.url.host:
            return _json({"value": []})
        return httpx.Response(302, headers={"location": "https://evil.example.com/steal"})

    with pytest.raises(onec.OneCUnavailable):
        list(_client(handler).iter_entities("Catalog_X"))
    assert len(calls) == 1  # на редирект не пошли — заголовок Authorization не уехал


def test_garbage_body_is_unavailable():
    client = _client(lambda request: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(onec.OneCUnavailable):
        list(client.iter_entities("Catalog_X"))


def test_read_one_returns_first_record_or_none():
    assert _client(lambda r: _json({"value": [{"Ref_Key": "a"}]})).read_one("Catalog_X") == {
        "Ref_Key": "a"}
    assert _client(lambda r: _json({"value": []})).read_one("Catalog_X") is None


# ── секрет не утекает ───────────────────────────────────────────────────

def test_password_is_not_in_repr_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    client = _client(lambda request: _json({"value": [{"Ref_Key": "a"}]}))
    list(client.iter_entities("Catalog_X"))
    assert PASSWORD not in repr(client) and PASSWORD not in str(client)
    assert PASSWORD not in caplog.text
    assert "integration" in repr(client) and "onec.example.kz" in repr(client)


# ── литералы $filter ────────────────────────────────────────────────────

def test_odata_literal_doubles_quotes():
    assert onec.odata_literal("O'Brien") == "'O''Brien'"
    assert onec.odata_literal("x' or 1 eq 1 or Description eq '") == (
        "'x'' or 1 eq 1 or Description eq '''")


def test_odata_guid_accepts_only_a_guid():
    ok = "0f8fad5b-d9cb-469f-a165-70867728950e"
    assert onec.odata_guid(ok.upper()) == f"guid'{ok}'"
    for bad in ("", "not-a-guid", ok + "' or 1 eq 1", "0f8fad5bd9cb469fa16570867728950e"):
        with pytest.raises(ValueError):
            onec.odata_guid(bad)


def test_filter_is_passed_through_to_the_request():
    seen = []

    def handler(request):
        seen.append(request.url.params["$filter"])
        return _json({"value": []})

    flt = f"Description eq {onec.odata_literal(chr(39))}"
    list(_client(handler).iter_entities("Catalog_X", filter=flt))
    assert seen == ["Description eq ''''"]


# ── настройки ───────────────────────────────────────────────────────────

def test_from_settings_is_disabled_when_url_is_empty(settings):
    settings.ONEC_ODATA_URL = ""
    with pytest.raises(onec.OneCDisabled):
        onec.OneCClient.from_settings()


def test_from_settings_reads_the_environment_values(settings):
    settings.ONEC_ODATA_URL = BASE
    settings.ONEC_USER = "svc"
    settings.ONEC_PASSWORD = PASSWORD
    settings.ONEC_TIMEOUT = 7
    client = onec.OneCClient.from_settings(transport=httpx.MockTransport(lambda r: _json({})))
    assert client.user == "svc" and PASSWORD not in repr(client)


# ── сторож игнор-файлов ─────────────────────────────────────────────────

def _lines(name: str) -> list[str]:
    return [line.strip() for line in (REPO / name).read_text(encoding="utf-8").splitlines()]


def test_secrets_directory_is_ignored_by_git_and_docker():
    assert "secrets/" in _lines(".gitignore")
    # Образ backend собирается с context ./backend — у него свой .dockerignore.
    for name in (".dockerignore", "backend/.dockerignore"):
        lines = _lines(name)
        assert "secrets/" in lines and "**/secrets/" in lines, name
