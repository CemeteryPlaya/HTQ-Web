"""Ссылки-приглашения в конференцию и гостевой вход.

Здесь проверяется не столько «работает ли», сколько **границы**: гостевая
ссылка — единственное место в платформе, где действие совершает человек без
учётки, и цена ошибки тут выше обычной. Отсюда упор на то, чего гость НЕ
может: попасть в чужую комнату, попасть в API платформы, войти по отозванной
или просроченной ссылке.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.cms.models import ConferenceInvite
from apps.cms.services import conference_invite_service as svc
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import decode_token, issue_guest_token
from htqweb.http import _authenticate_jwt

BASE = "/api/cms/v1/conference"


@pytest.fixture
def host(db):
    user = User.objects.create(
        username="host", email="host@htq.test", password="x",
        status=UserStatus.ACTIVE,
    )
    from htqweb.authn.jwt import issue_token_pair
    return user, {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _invite(**kw) -> ConferenceInvite:
    defaults = dict(room_id="daily-standup", created_by_id=None, title="Планёрка")
    defaults.update(kw)
    return svc.create_invite(**defaults)


# ── гостевой токен: что он открывает и, главное, что нет ──────────────────

def test_guest_token_is_rejected_by_the_platform_api():
    """Гостевой токен подписан тем же секретом, что и рабочий, — иначе SFU
    его не примет. Значит единственное, что удерживает его от API
    платформы, — проверки типа и отсутствие user_id. Обе обязаны работать."""
    token, _ = issue_guest_token(room_id="r1", display_name="Клиент")

    request = type("R", (), {"headers": {"Authorization": f"Bearer {token}"}})()
    assert _authenticate_jwt(request) is None


def test_guest_token_carries_the_room_it_was_issued_for():
    token, ttl = issue_guest_token(room_id="board-42", display_name="Гость")

    import jwt as pyjwt
    from django.conf import settings
    claims = pyjwt.decode(token, settings.JWT_SECRET,
                          algorithms=[settings.JWT_ALGORITHM],
                          issuer=settings.JWT_ISSUER)

    assert claims["token_type"] == "guest"
    assert claims["room_id"] == "board-42"
    # Без user_id: даже если проверку типа однажды ослабят, TokenPayload
    # без обязательного поля не соберётся — вторая линия обороны.
    assert "user_id" not in claims
    assert ttl > 0


def test_guest_token_does_not_decode_as_a_platform_payload():
    token, _ = issue_guest_token(room_id="r1", display_name="Гость")
    with pytest.raises(Exception):
        decode_token(token)


# ── жизненный цикл ссылки ────────────────────────────────────────────────

@pytest.mark.django_db
def test_resolve_returns_a_live_invite():
    invite = _invite()
    assert svc.resolve(invite.token).id == invite.id


@pytest.mark.django_db
def test_revoked_invite_stops_working():
    invite = _invite()
    svc.revoke(invite.id)

    with pytest.raises(svc.InviteInvalid) as info:
        svc.resolve(invite.token)
    assert info.value.code == "revoked"


@pytest.mark.django_db
def test_expired_invite_stops_working():
    invite = _invite()
    ConferenceInvite.objects.filter(pk=invite.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1))

    with pytest.raises(svc.InviteInvalid) as info:
        svc.resolve(invite.token)
    assert info.value.code == "expired"


@pytest.mark.django_db
def test_use_limit_is_enforced():
    """Ссылка «на одного»: позвали клиента, а не весь интернет."""
    invite = _invite(max_uses=1)
    svc.issue_guest_access(invite, display_name="Первый")

    with pytest.raises(svc.InviteInvalid) as info:
        svc.resolve(invite.token)
    assert info.value.code == "exhausted"


@pytest.mark.django_db
def test_invite_without_guests_refuses_to_issue_a_guest_token():
    """allow_guests=False — «зову только коллег»: ссылка ведёт в комнату, но
    входить надо под своей учёткой."""
    invite = _invite(allow_guests=False)

    with pytest.raises(svc.InviteInvalid) as info:
        svc.issue_guest_access(invite, display_name="Посторонний")
    assert info.value.code == "guests_not_allowed"


@pytest.mark.django_db
def test_guest_access_binds_the_token_to_the_invited_room():
    invite = _invite(room_id="room-77")
    payload = svc.issue_guest_access(invite, display_name="Гость")

    import jwt as pyjwt
    from django.conf import settings
    claims = pyjwt.decode(payload["access_token"], settings.JWT_SECRET,
                          algorithms=[settings.JWT_ALGORITHM],
                          issuer=settings.JWT_ISSUER)
    assert claims["room_id"] == "room-77"
    assert payload["room_id"] == "room-77"


# ── HTTP ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_creating_an_invite_returns_a_ready_link(host):
    _, auth = host
    resp = Client().post(
        f"{BASE}/invites", data={"room_id": "abc-123", "title": "Созвон"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["url"].endswith(f"/join/{ConferenceInvite.objects.get().token}")
    assert body["allow_guests"] is True


@pytest.mark.django_db
def test_creating_an_invite_requires_authorization():
    resp = Client().post(f"{BASE}/invites", data={"room_id": "abc"},
                         content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_public_page_shows_the_meeting_but_not_the_room():
    """До того как человек представился, он не участник — идентификатор
    комнаты ему знать незачем."""
    invite = _invite(title="Приёмка объекта")

    body = Client().get(f"{BASE}/join/{invite.token}").json()

    assert body["title"] == "Приёмка объекта"
    assert body["allow_guests"] is True
    assert body["room_id"] is None


@pytest.mark.django_db
def test_employee_opening_the_same_link_gets_the_room(host):
    """Сотруднику представляться незачем — он войдёт под своей учёткой, и
    страница входа сразу отправит его в комнату."""
    _, auth = host
    invite = _invite(room_id="room-for-staff")

    body = Client().get(f"{BASE}/join/{invite.token}", **auth).json()

    assert body["room_id"] == "room-for-staff"


@pytest.mark.django_db
def test_public_page_hides_why_a_bad_link_is_bad_only_as_404():
    assert Client().get(f"{BASE}/join/deadbeef").status_code == 404


@pytest.mark.django_db
def test_guest_endpoint_issues_a_token_by_name():
    invite = _invite(room_id="room-9")

    resp = Client().post(
        f"{BASE}/join/{invite.token}/guest",
        data={"display_name": "Иван (подрядчик)"},
        content_type="application/json",
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["room_id"] == "room-9"
    assert body["display_name"] == "Иван (подрядчик)"
    assert body["access_token"]


@pytest.mark.django_db
def test_opening_the_link_does_not_burn_a_use(host):
    """Предпросмотр в мессенджере и антивирус в почте открывают ссылку сами.
    Если бы просмотр считался входом, встреча «занималась» бы до прихода
    живого человека — ради этого выдача токена и отделена от проверки."""
    invite = _invite(max_uses=1)

    Client().get(f"{BASE}/join/{invite.token}")
    Client().get(f"{BASE}/join/{invite.token}")

    invite.refresh_from_db()
    assert invite.uses == 0
    assert svc.resolve(invite.token).id == invite.id


@pytest.mark.django_db
def test_revoked_link_refuses_the_guest_token():
    invite = _invite()
    svc.revoke(invite.id)

    resp = Client().post(
        f"{BASE}/join/{invite.token}/guest", data={"display_name": "Поздний"},
        content_type="application/json",
    )
    assert resp.status_code in (403, 404)


# ── отправка ссылки ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_sending_an_invite_by_email(host):
    from django.core import mail

    _, auth = host
    invite = _invite(title="Приёмка")

    resp = Client().post(
        f"{BASE}/invites/{invite.id}/send",
        data={"emails": ["client@example.com"]},
        content_type="application/json", **auth,
    )

    assert resp.status_code == 200
    assert resp.json()["emails_sent"] == 1
    assert len(mail.outbox) == 1
    # В письме — рабочая ссылка, а не идентификатор комнаты: получателю
    # некуда его вводить, страницы «войти по ID» он не видел.
    assert f"/join/{invite.token}" in mail.outbox[0].body


@pytest.mark.django_db
def test_sending_notifies_employees_in_the_messenger(host, monkeypatch):
    _, auth = host
    invite = _invite()
    sent: list[tuple] = []

    from apps.messenger import interface as messenger
    monkeypatch.setattr(messenger, "dispatch_notification",
                        lambda user_ids, payload: sent.append((user_ids, payload)))

    resp = Client().post(
        f"{BASE}/invites/{invite.id}/send", data={"user_ids": [7, 9]},
        content_type="application/json", **auth,
    )

    assert resp.status_code == 200
    assert resp.json()["notified"] == 2
    assert sent[0][0] == [7, 9]
    assert sent[0][1]["type"] == "conference_invite"
    assert f"/join/{invite.token}" in sent[0][1]["url"]


@pytest.mark.django_db
def test_one_broken_channel_does_not_cancel_the_other(host, monkeypatch):
    """Недоступный мессенджер не должен отменять письма — и наоборот. Отчёт
    честно говорит, что именно не дошло."""
    from django.core import mail

    _, auth = host
    invite = _invite()

    from apps.messenger import interface as messenger

    def boom(user_ids, payload):
        raise RuntimeError("socket.io лежит")

    monkeypatch.setattr(messenger, "dispatch_notification", boom)

    body = Client().post(
        f"{BASE}/invites/{invite.id}/send",
        data={"emails": ["a@example.com"], "user_ids": [1]},
        content_type="application/json", **auth,
    ).json()

    assert body["emails_sent"] == 1 and len(mail.outbox) == 1
    assert body["notified"] == 0
    assert any("Мессенджер" in err for err in body["errors"])


@pytest.mark.django_db
def test_sending_to_nobody_is_a_validation_error(host):
    _, auth = host
    invite = _invite()
    resp = Client().post(f"{BASE}/invites/{invite.id}/send", data={},
                         content_type="application/json", **auth)
    assert resp.status_code == 422
