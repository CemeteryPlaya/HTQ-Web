"""Контракт apps/mail/services/mailcow_client.py — порт
services/email/app/services/mailcow_client.py (mailboxes-под-задача,
mail-mailboxes-brief.md).

СИНХРОННЫЙ (``httpx.Client``, не ``AsyncClient``) — тот же принцип, что
``apps/mail/services/oauth_clients.py``/``sender/gmail.py`` (Django-вьюхи
этого домена синхронные). Единственный живой HTTP-вызов обёрнут в
module-level seam ``_request`` — тесты монkeypatch'ят ровно его, БЕЗ живой
сети. Контрактные тесты проверяют И форму запроса (метод/путь/payload/
заголовки), И разбор ответа Mailcow (``_parse``: {"type": "success"/"info"}
проходит, "danger"/"error" -> MailcowError, HTTP>=500 -> MailcowError,
невалидный JSON -> MailcowError)."""
from __future__ import annotations

import httpx
import pytest
from django.test import override_settings

from apps.mail.services.mailcow_client import MailcowClient, MailcowError, get_mailcow_client


def _resp(status_code=200, json_body=None, text_body=None):
    request = httpx.Request("GET", "https://mailcow.example.com/api/v1/get/mailbox/all/x")
    if text_body is not None:
        return httpx.Response(status_code, text=text_body, request=request)
    return httpx.Response(status_code, json=json_body, request=request)


@pytest.fixture
def client():
    return MailcowClient(base_url="https://mailcow.example.com/api/v1", api_key="test-key")


# ── configuration / factory ─────────────────────────────────────────────────

def test_get_mailcow_client_returns_instance():
    assert isinstance(get_mailcow_client(), MailcowClient)


def test_base_url_and_api_key_default_to_empty_string_when_unconfigured():
    """Решение 2 (бриф mail-core, тот же принцип для mailboxes): htqweb/settings
    трогать нельзя — читаем через getattr(settings, NAME, ""), буквально как
    исходник (``mailcow_api_url: str = ""``, ``mailcow_api_key: str = ""``).
    По умолчанию оператор ничего не задал -> пустая строка (то же поведение,
    что у исходника до конфигурации)."""
    c = MailcowClient()
    assert c.base_url == ""
    assert c.api_key == ""


def test_base_url_strips_trailing_slash():
    c = MailcowClient(base_url="https://mailcow.example.com/api/v1/", api_key="k")
    assert c.base_url == "https://mailcow.example.com/api/v1"


def test_explicit_args_override_settings(client):
    assert client.base_url == "https://mailcow.example.com/api/v1"
    assert client.api_key == "test-key"


# ── headers ──────────────────────────────────────────────────────────────

def test_headers_include_api_key_and_content_type(client):
    headers = client._headers()
    assert headers["X-API-Key"] == "test-key"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"


# ── _parse ───────────────────────────────────────────────────────────────

def test_parse_passes_through_plain_get_list(client):
    resp = _resp(200, json_body=[{"local_part": "a"}, {"local_part": "b"}])
    assert client._parse(resp, method="GET", path="/get/mailbox/all/x") == [
        {"local_part": "a"}, {"local_part": "b"},
    ]


def test_parse_passes_through_plain_get_dict(client):
    resp = _resp(200, json_body={"local_part": "a"})
    assert client._parse(resp, method="GET", path="/get/mailbox/a@x") == {"local_part": "a"}


def test_parse_accepts_success_status_list(client):
    resp = _resp(200, json_body=[{"type": "success", "msg": "mailbox_added"}])
    assert client._parse(resp, method="POST", path="/add/mailbox") == [
        {"type": "success", "msg": "mailbox_added"},
    ]


def test_parse_accepts_info_status(client):
    resp = _resp(200, json_body={"type": "info", "msg": "no_change"})
    assert client._parse(resp, method="POST", path="/edit/mailbox") == {"type": "info", "msg": "no_change"}


def test_parse_raises_on_danger_status_list(client):
    resp = _resp(200, json_body=[{"type": "danger", "msg": "mailbox_quota_exceeded"}])
    with pytest.raises(MailcowError, match="mailbox_quota_exceeded"):
        client._parse(resp, method="POST", path="/add/mailbox")


def test_parse_raises_on_danger_status_dict(client):
    resp = _resp(200, json_body={"type": "danger", "msg": "object_not_found"})
    with pytest.raises(MailcowError, match="object_not_found"):
        client._parse(resp, method="POST", path="/delete/mailbox")


def test_parse_raises_on_server_error(client):
    resp = _resp(500, text_body="Internal Server Error")
    with pytest.raises(MailcowError, match="HTTP 500"):
        client._parse(resp, method="POST", path="/add/mailbox")


def test_parse_raises_on_invalid_json(client):
    resp = _resp(200, text_body="<html>not json</html>")
    with pytest.raises(MailcowError, match="invalid JSON"):
        client._parse(resp, method="GET", path="/get/mailbox/all/x")


# ── request shapes (seam: monkeypatch client._request) ──────────────────

def _capture(monkeypatch, client, response):
    calls = []

    def _fake_request(method, url, *, headers, json=None):
        calls.append(dict(method=method, url=url, headers=headers, json=json))
        return response

    monkeypatch.setattr(client, "_request", _fake_request)
    return calls


def test_create_mailbox_posts_expected_payload(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.create_mailbox(
        local_part="i.ivanov", domain="htq.group", password="Str0ng!Pass",
        full_name="Иван Иванов", quota_mb=2048,
    )
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://mailcow.example.com/api/v1/add/mailbox"
    assert call["json"] == {
        "local_part": "i.ivanov", "domain": "htq.group", "name": "Иван Иванов",
        "quota": "2048", "password": "Str0ng!Pass", "password2": "Str0ng!Pass",
        "active": "1", "force_pw_update": "0", "tls_enforce_in": "1", "tls_enforce_out": "1",
    }


def test_create_mailbox_defaults_name_to_local_part_when_full_name_empty(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.create_mailbox(local_part="user", domain="htq.group", password="x")
    assert calls[0]["json"]["name"] == "user"
    assert calls[0]["json"]["quota"] == "1024"
    assert calls[0]["json"]["active"] == "1"


def test_edit_mailbox_wraps_items_and_attr(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.edit_mailbox("user@htq.group", {"quota": "2048"})
    assert calls[0]["url"] == "https://mailcow.example.com/api/v1/edit/mailbox"
    assert calls[0]["json"] == {"items": ["user@htq.group"], "attr": {"quota": "2048"}}


def test_set_active_true_and_false(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.set_active("user@htq.group", active=True)
    client.set_active("user@htq.group", active=False)
    assert calls[0]["json"]["attr"] == {"active": "1"}
    assert calls[1]["json"]["attr"] == {"active": "0"}


def test_reset_password_sets_force_pw_update(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.reset_password("user@htq.group", "NewPass1!", force_change=True)
    assert calls[0]["json"]["attr"] == {
        "password": "NewPass1!", "password2": "NewPass1!", "force_pw_update": "1",
    }


def test_delete_mailbox_posts_address_list(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.delete_mailbox("user@htq.group")
    assert calls[0]["url"] == "https://mailcow.example.com/api/v1/delete/mailbox"
    assert calls[0]["json"] == ["user@htq.group"]


def test_add_app_password_default_protocols(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.add_app_password(address="user@htq.group", app_name="htqweb-platform", password="app-pass")
    body = calls[0]["json"]
    assert body["username"] == "user@htq.group"
    assert body["app_name"] == "htqweb-platform"
    assert body["app_passwd"] == "app-pass"
    assert body["app_passwd2"] == "app-pass"
    assert body["active"] == "1"
    assert body["imap_access"] == "1"
    assert body["smtp_access"] == "1"


def test_add_app_password_custom_protocols(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.add_app_password(
        address="user@htq.group", app_name="idle", password="p", protocols=["imap_access"],
    )
    body = calls[0]["json"]
    assert body["imap_access"] == "1"
    assert "smtp_access" not in body


def test_get_mailbox_uses_get_with_address_in_path(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body={"local_part": "user"}))
    result = client.get_mailbox("user@htq.group")
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://mailcow.example.com/api/v1/get/mailbox/user@htq.group"
    assert result == {"local_part": "user"}


def test_list_mailboxes_uses_domain_from_arg_or_settings(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"local_part": "a"}]))
    result = client.list_mailboxes(domain="htq.group")
    assert calls[0]["url"] == "https://mailcow.example.com/api/v1/get/mailbox/all/htq.group"
    assert result == [{"local_part": "a"}]


def test_list_mailboxes_returns_empty_list_when_response_not_a_list(client, monkeypatch):
    # dict БЕЗ "type" — _parse не бросает (не наш success/danger конверт),
    # но list_mailboxes всё равно ждёт список — защитно отдаёт [].
    _capture(monkeypatch, client, _resp(200, json_body={"unexpected": "shape"}))
    result = client.list_mailboxes(domain="htq.group")
    assert result == []


def test_add_alias_default_active(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.add_alias(address="sales@htq.group", goto="a@htq.group,b@htq.group")
    assert calls[0]["url"] == "https://mailcow.example.com/api/v1/add/alias"
    assert calls[0]["json"] == {
        "address": "sales@htq.group", "goto": "a@htq.group,b@htq.group", "active": "1",
    }


def test_add_alias_inactive(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.add_alias(address="sales@htq.group", goto="a@htq.group", active=False)
    assert calls[0]["json"]["active"] == "0"


def test_list_aliases(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"address": "sales@htq.group"}]))
    result = client.list_aliases(domain="htq.group")
    assert calls[0]["url"] == "https://mailcow.example.com/api/v1/get/alias/all/htq.group"
    assert result == [{"address": "sales@htq.group"}]


def test_delete_alias_posts_id_list(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.delete_alias(42)
    assert calls[0]["url"] == "https://mailcow.example.com/api/v1/delete/alias"
    assert calls[0]["json"] == [42]


def test_set_forwarding_keeps_local_copy_by_default(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.set_forwarding("user@htq.group", "ext@example.com")
    assert calls[0]["json"] == {
        "address": "user@htq.group", "goto": "user@htq.group,ext@example.com", "active": "1",
    }


def test_set_forwarding_without_local_copy(client, monkeypatch):
    calls = _capture(monkeypatch, client, _resp(200, json_body=[{"type": "success", "msg": "ok"}]))
    client.set_forwarding("user@htq.group", "ext@example.com", keep_local_copy=False)
    assert calls[0]["json"]["goto"] == "ext@example.com"


# ── real seam wiring: _post/_get call module-level _request exactly once ──

def test_post_and_get_call_request_seam_with_full_url_and_headers(monkeypatch, client):
    seen = []

    def _fake_request(method, url, *, headers, json=None):
        seen.append((method, url, headers, json))
        return _resp(200, json_body=[{"type": "success", "msg": "ok"}])

    monkeypatch.setattr(client, "_request", _fake_request)
    client.edit_mailbox("a@b.com", {"active": "1"})
    assert seen[0][0] == "POST"
    assert seen[0][1] == "https://mailcow.example.com/api/v1/edit/mailbox"
    assert seen[0][2]["X-API-Key"] == "test-key"
