"""Контракт /api/email/v1/{folder,unread-counts,send,draft,<uuid>}* — паритет
с ``services/email/app/api/v1/emails.py`` (6 эндпойнтов, mail-messages-brief.md):

  GET  /folder/{folder}          — list_emails (400 на неизвестную папку)
  GET  /unread-counts/           — unread_counts
  GET  /{message_id}             — get_email (404 на чужое/несуществующее)
  POST /send                     — send_email (202; 404/409/403)
  POST /{message_id}/read        — mark_as_read (204 всегда, без rowcount-проверки)
  POST /draft                    — save_draft (201)

Авторизация — обычный JWT-пользователь, СТРОГИЙ user-scoping (сообщения
доступны только владельцу — не владельцу аккаунта, а ``EmailMessage.user_id``
самого JWT), 404 на чужое (не 403).
"""
import datetime
import json

import pytest
from django.test import Client

from apps.mail.models import AccountProvider, AccountType, EmailAccount, EmailMessage, OAuthToken
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/email/v1"


@pytest.fixture
def user(db):
    u = User.objects.create(
        username="msg-user", email="msg@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def other_user(db):
    u = User.objects.create(
        username="msg-other", email="msg-other@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def auth(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def other_auth(other_user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(other_user)['access']}"}


def _account(user_id, address="acct@example.com", **kw):
    tok = OAuthToken.objects.create(
        user_id=user_id, provider="google", provider_account_id=address,
        encrypted_access_token="enc", expires_at=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults = dict(
        user_id=user_id, type=AccountType.PERSONAL, provider=AccountProvider.GOOGLE,
        address=address, oauth_token=tok,
    )
    defaults.update(kw)
    return EmailAccount.objects.create(**defaults)


def _message(user_id, **kw):
    defaults = dict(
        user_id=user_id,
        sender_email="from@example.com",
        date=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults.update(kw)
    return EmailMessage.objects.create(**defaults)


def _post_json(client, path, data, **headers):
    return client.post(path, data=json.dumps(data), content_type="application/json", **headers)


# ── auth ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_all_six_endpoints_require_jwt():
    c = Client()
    assert c.get(f"{BASE}/folder/inbox").status_code == 401
    assert c.get(f"{BASE}/unread-counts/").status_code == 401
    assert c.get(f"{BASE}/00000000-0000-0000-0000-000000000000").status_code == 401
    assert c.post(f"{BASE}/send", data="{}", content_type="application/json").status_code == 401
    assert c.post(f"{BASE}/00000000-0000-0000-0000-000000000000/read").status_code == 401
    assert c.post(f"{BASE}/draft", data="{}", content_type="application/json").status_code == 401


# ── GET /folder/{folder} ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_emails_scopes_to_own_user_and_orders_by_date_desc(user, other_user, auth):
    older = _message(user.id, folder="inbox", subject="older",
                      date=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
    newer = _message(user.id, folder="inbox", subject="newer",
                      date=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc))
    _message(user.id, folder="sent", subject="not-inbox",
             date=datetime.datetime(2026, 6, 2, tzinfo=datetime.timezone.utc))
    _message(other_user.id, folder="inbox", subject="not-mine",
             date=datetime.datetime(2026, 6, 3, tzinfo=datetime.timezone.utc))

    resp = Client().get(f"{BASE}/folder/inbox", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert [m["id"] for m in body] == [str(newer.id), str(older.id)]
    assert {"id", "account_id", "subject", "snippet", "sender_email", "sender_name",
            "to_recipients", "cc_recipients", "date", "is_read", "is_flagged",
            "has_attachments", "folder", "provider_folder"} == set(body[0])


@pytest.mark.django_db
def test_list_emails_filters_by_account_id(user, auth):
    acc1 = _account(user.id, "acc1@example.com")
    acc2 = _account(user.id, "acc2@example.com")
    m1 = _message(user.id, folder="inbox", account=acc1)
    _message(user.id, folder="inbox", account=acc2)

    resp = Client().get(f"{BASE}/folder/inbox?account_id={acc1.id}", **auth)
    assert resp.status_code == 200
    assert [m["id"] for m in resp.json()] == [str(m1.id)]


@pytest.mark.django_db
def test_list_emails_400_for_invalid_folder(auth):
    resp = Client().get(f"{BASE}/folder/bogus", **auth)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid folder"


@pytest.mark.django_db
def test_list_emails_pagination_limit_offset(user, auth):
    for i in range(3):
        _message(user.id, folder="inbox", subject=f"m{i}",
                  date=datetime.datetime(2026, 1, i + 1, tzinfo=datetime.timezone.utc))

    resp = Client().get(f"{BASE}/folder/inbox?limit=1&offset=1", **auth)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.django_db
def test_list_emails_422_for_out_of_range_limit(auth):
    resp = Client().get(f"{BASE}/folder/inbox?limit=101", **auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_list_emails_422_for_non_integer_offset(auth):
    resp = Client().get(f"{BASE}/folder/inbox?offset=abc", **auth)
    assert resp.status_code == 422


# ── GET /unread-counts/ ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_unread_counts_shape_and_scoping(user, other_user, auth):
    acc = _account(user.id)
    _message(user.id, account=acc, folder="inbox", is_read=False)
    _message(user.id, account=acc, folder="inbox", is_read=False)
    _message(user.id, folder="inbox", is_read=True)  # read — excluded from by_folder
    _message(user.id, folder="sent", is_read=False)
    _message(other_user.id, folder="inbox", is_read=False)  # not mine

    resp = Client().get(f"{BASE}/unread-counts/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "by_account": {str(acc.id): 2},
        "by_folder": {"inbox": 2, "sent": 1},
    }


# ── GET /{message_id} ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_email_detail_includes_body_and_empty_attachments(user, auth):
    msg = _message(user.id, subject="hi", body_html="<p>x</p>", body_text="x")
    resp = Client().get(f"{BASE}/{msg.id}", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["body_html"] == "<p>x</p>"
    assert body["body_text"] == "x"
    # Буквальный перенос особенности исходника — attachments всегда [].
    assert body["attachments"] == []


@pytest.mark.django_db
def test_get_email_404_when_not_found(auth):
    resp = Client().get(f"{BASE}/00000000-0000-0000-0000-000000000000", **auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Email not found"


@pytest.mark.django_db
def test_get_email_404_when_not_owned(other_user, auth):
    msg = _message(other_user.id)
    resp = Client().get(f"{BASE}/{msg.id}", **auth)
    assert resp.status_code == 404


# ── POST /send ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_send_email_queues_outbox_message_and_recipient_statuses(user, auth):
    acc = _account(user.id)
    resp = _post_json(
        Client(), f"{BASE}/send",
        {
            "account_id": acc.id,
            "to_recipients": [{"email": "to@example.com", "name": "To"}],
            "cc_recipients": [{"email": "cc@example.com"}],
            "subject": "Hello",
            "body_text": "Body",
        },
        **auth,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"

    msg = EmailMessage.objects.get(id=body["id"])
    assert msg.folder == "outbox"
    assert msg.is_read is True
    assert msg.sender_email == acc.address
    assert msg.user_id == user.id
    statuses = list(msg.recipient_statuses.values_list("recipient_email", "status"))
    assert sorted(statuses) == [("cc@example.com", "pending"), ("to@example.com", "pending")]


@pytest.mark.django_db
def test_send_email_404_when_account_not_found(auth):
    resp = _post_json(
        Client(), f"{BASE}/send",
        {"account_id": 999999, "to_recipients": [], "subject": "x"},
        **auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Account not found"


@pytest.mark.django_db
def test_send_email_404_when_account_not_owned(other_user, auth):
    acc = _account(other_user.id)
    resp = _post_json(
        Client(), f"{BASE}/send",
        {"account_id": acc.id, "to_recipients": [], "subject": "x"},
        **auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_send_email_409_when_account_inactive(user, auth):
    acc = _account(user.id, is_active=False)
    resp = _post_json(
        Client(), f"{BASE}/send",
        {"account_id": acc.id, "to_recipients": [], "subject": "x"},
        **auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Account is inactive"


@pytest.mark.django_db
def test_send_email_403_on_dlp_violation(user, auth):
    acc = _account(user.id)
    resp = _post_json(
        Client(), f"{BASE}/send",
        {
            "account_id": acc.id, "to_recipients": [],
            "subject": "ssn", "body_text": "my ssn is 123-45-6789",
        },
        **auth,
    )
    assert resp.status_code == 403
    assert "DLP" in resp.json()["detail"]
    assert not EmailMessage.objects.filter(sender_email=acc.address).exists()


# ── POST /{message_id}/read ──────────────────────────────────────────────

@pytest.mark.django_db
def test_mark_as_read_sets_flag_and_returns_204(user, auth):
    msg = _message(user.id, is_read=False)
    resp = Client().post(f"{BASE}/{msg.id}/read", **auth)
    assert resp.status_code == 204
    msg.refresh_from_db()
    assert msg.is_read is True


@pytest.mark.django_db
def test_mark_as_read_204_even_when_not_found_or_not_owned(other_user, auth):
    """Буквальный перенос: UPDATE ... WHERE id= AND user_id= без проверки
    rowcount — 204 независимо от того, нашлась ли строка."""
    other_msg = _message(other_user.id, is_read=False)

    resp = Client().post(f"{BASE}/00000000-0000-0000-0000-000000000000/read", **auth)
    assert resp.status_code == 204

    resp2 = Client().post(f"{BASE}/{other_msg.id}/read", **auth)
    assert resp2.status_code == 204
    other_msg.refresh_from_db()
    assert other_msg.is_read is False  # чужое сообщение не тронуто


# ── POST /draft ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_save_draft_creates_row_in_drafts_folder(user, auth):
    resp = _post_json(Client(), f"{BASE}/draft", {"subject": "Draft", "body": "text"}, **auth)
    assert resp.status_code == 201
    body = resp.json()
    assert body["folder"] == "drafts"

    msg = EmailMessage.objects.get(id=body["id"])
    assert msg.user_id == user.id
    assert msg.folder == "drafts"
    assert msg.subject == "Draft"
    assert msg.body_text == "text"
    assert msg.account_id is None


@pytest.mark.django_db
def test_save_draft_defaults_to_empty_subject_and_body(user, auth):
    resp = _post_json(Client(), f"{BASE}/draft", {}, **auth)
    assert resp.status_code == 201
    msg = EmailMessage.objects.get(id=resp.json()["id"])
    assert msg.subject == ""
    assert msg.body_text == ""
