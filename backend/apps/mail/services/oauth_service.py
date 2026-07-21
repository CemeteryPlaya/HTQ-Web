"""Бизнес-логика OAuth-роутера — порт
``services/email/app/api/v1/oauth.py`` (5 эндпойнтов): status, accounts
(сырой список токенов), connect, callback, disconnect.

State (user_id/provider/code_verifier PKCE) персистится в
``django.core.cache.cache`` вместо прямого Redis-клиента исходника — тот же
TTL-KV примитив, уже подключённый платформой (``settings.CACHES``,
``apps.core.services.service_status`` использует его так же), без похода в
redis-py напрямую и без правки htqweb/settings (вне зоны mail). LocMemCache
в тестах (htqweb/settings/test.py) делает флоу тестируемым без реального
Redis; в проде — тот же Redis (settings.CACHES["default"]), что и исходник
использовал напрямую.

Р2 (бриф mail-core): пост-OAuth фоновая постановка
(``start_account_sync``/``register_account_push``, dramatiq) НЕ портируется —
под-задача workers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from apps.mail.models import AccountType, EmailAccount, OAuthToken
from apps.mail.services.crypto import crypto_service
from apps.mail.services.oauth_clients import gen_pkce_pair, gen_state_nonce, get_oauth_client

log = logging.getLogger(__name__)

_STATE_PREFIX = "mail:oauth:state:"
_DEFAULT_STATE_TTL_SEC = 600


class ProviderNotConfigured(Exception):
    """503 — GOOGLE_CLIENT_ID/SECRET (или MICROSOFT_...) не заданы."""


class InvalidOAuthState(Exception):
    """400 — state отсутствует/истёк/уже использован в Redis/cache."""


class ProviderEmailMissing(Exception):
    """502 — провайдер не вернул email в userinfo."""


def _state_ttl() -> int:
    return getattr(settings, "OAUTH_STATE_TTL_SEC", _DEFAULT_STATE_TTL_SEC)


def _state_key(nonce: str) -> str:
    return f"{_STATE_PREFIX}{nonce}"


def _extract_email(provider: str, info: dict) -> str:
    if provider == "google":
        email = info.get("email")
    else:  # microsoft
        # `mail` может быть null на личных MS-аккаунтах; фолбэк на UPN.
        email = info.get("mail") or info.get("userPrincipalName")
    if not email:
        raise ProviderEmailMissing
    return email.lower()


def _display_name(provider: str, info: dict) -> str | None:
    if provider == "google":
        return info.get("name")
    return info.get("displayName")


# ── /oauth/status — легаси-совместимость ────────────────────────────────

def status(user_id: int) -> dict:
    token = OAuthToken.objects.filter(user_id=user_id).order_by("-created_at").first()
    if token is None:
        return {
            "connected": False, "provider": None, "email": None,
            "primary_email": None, "connected_at": None, "token_expires_at": None,
        }
    return {
        "connected": True,
        "provider": token.provider,
        "email": token.provider_account_id,
        "primary_email": token.provider_account_id,
        "connected_at": token.created_at.isoformat() if token.created_at else None,
        "token_expires_at": token.expires_at.isoformat() if token.expires_at else None,
    }


# ── /oauth/accounts — сырой список токенов (легаси account-picker) ──────

def list_tokens(user_id: int) -> list[dict]:
    qs = OAuthToken.objects.filter(user_id=user_id)
    return [
        {
            "id": t.id,
            "provider": t.provider,
            "provider_account_id": t.provider_account_id,
            "expires_at": t.expires_at.isoformat(),
            "is_active": t.is_active,
        }
        for t in qs
    ]


# ── /oauth/connect/{provider} — старт PKCE-флоу ──────────────────────────

def connect(user_id: int, provider: str) -> dict:
    client = get_oauth_client(provider)

    # Guardrail — если env не заполнен, падаем громко, а не редиректим
    # пользователя на битый auth-экран.
    if provider == "google" and not (
        getattr(settings, "GOOGLE_CLIENT_ID", "") and getattr(settings, "GOOGLE_CLIENT_SECRET", "")
    ):
        raise ProviderNotConfigured("Google OAuth not configured")
    if provider == "microsoft" and not (
        getattr(settings, "MICROSOFT_CLIENT_ID", "") and getattr(settings, "MICROSOFT_CLIENT_SECRET", "")
    ):
        raise ProviderNotConfigured("Microsoft OAuth not configured")

    code_verifier, code_challenge = gen_pkce_pair()
    nonce = gen_state_nonce()

    cache.set(
        _state_key(nonce),
        {"user_id": user_id, "provider": provider, "code_verifier": code_verifier},
        timeout=_state_ttl(),
    )

    return {
        "auth_url": client.build_auth_url(state=nonce, code_challenge=code_challenge),
        "provider": provider,
        "state": nonce,
    }


# ── /oauth/callback — обмен + персист ────────────────────────────────────

@transaction.atomic
def callback(*, code: str, state: str) -> dict:
    """Редирект провайдера. Обменивает code, персистит, возвращает ack.

    Без JWT — state-нонс в cache связывает запрос с исходным user_id. State
    одноразовый (удаляется на чтении).
    """
    key = _state_key(state)
    payload = cache.get(key)
    if payload is None:
        raise InvalidOAuthState
    # Одноразовый — удаляем ДО любого вызова провайдера, чтобы replay не мог
    # дважды создать аккаунт.
    cache.delete(key)

    user_id: int = payload["user_id"]
    provider: str = payload["provider"]
    code_verifier: str = payload["code_verifier"]

    client = get_oauth_client(provider)
    bundle = client.exchange_code(code=code, code_verifier=code_verifier)
    info = client.userinfo(bundle.access_token)
    address = _extract_email(provider, info)

    # Шифруем токены at rest.
    enc_access = crypto_service.encrypt(bundle.access_token)
    enc_refresh = (
        crypto_service.encrypt(bundle.refresh_token) if bundle.refresh_token else None
    )
    expires_at = datetime.now(dt_timezone.utc) + timedelta(seconds=bundle.expires_in)

    # Upsert OAuthToken — ключ (user_id, provider, provider_account_id).
    token = OAuthToken.objects.filter(
        user_id=user_id, provider=provider, provider_account_id=address,
    ).first()
    if token is None:
        token = OAuthToken.objects.create(
            user_id=user_id, provider=provider, provider_account_id=address,
            encrypted_access_token=enc_access, encrypted_refresh_token=enc_refresh,
            expires_at=expires_at, is_active=True,
        )
    else:
        token.encrypted_access_token = enc_access
        if enc_refresh:
            token.encrypted_refresh_token = enc_refresh
        token.expires_at = expires_at
        token.is_active = True
        token.save()

    # Upsert EmailAccount.
    account = EmailAccount.objects.filter(user_id=user_id, address=address).first()
    # Если у пользователя ещё нет дефолта, свежий аккаунт становится им.
    has_default = EmailAccount.objects.filter(user_id=user_id, is_default=True).exists()

    if account is None:
        account = EmailAccount.objects.create(
            user_id=user_id, type=AccountType.PERSONAL, provider=provider, address=address,
            display_name=_display_name(provider, info), is_default=not has_default,
            is_active=True, oauth_token=token, sync_state={},
        )
    else:
        account.is_active = True
        account.oauth_token = token
        account.display_name = _display_name(provider, info) or account.display_name
        account.last_sync_error = None
        account.save()

    log.info(
        "oauth_connect_ok user_id=%s provider=%s account_id=%s", user_id, provider, account.id,
    )

    return {"status": "ok", "provider": provider, "address": address, "account_id": account.id}


# ── /oauth/disconnect — bulk-шим (легаси) ───────────────────────────────

def disconnect_all(user_id: int) -> dict:
    """Отвязывает КАЖДЫЙ личный аккаунт пользователя.

    Best-effort revoke у провайдера, затем удаление токенов + email_accounts.
    Корпоративные (Mailcow) аккаунты не трогаются — они идут через
    ``/mailboxes/{id}/archive/``.
    """
    accounts = list(
        EmailAccount.objects.filter(user_id=user_id, type=AccountType.PERSONAL)
    )

    for acc in accounts:
        if acc.oauth_token_id is None:
            continue
        token_row = OAuthToken.objects.filter(id=acc.oauth_token_id).first()
        if token_row is not None:
            try:
                client = get_oauth_client(acc.provider)
                access = crypto_service.decrypt(token_row.encrypted_access_token)
                client.revoke(access)
            except Exception as exc:  # best-effort
                log.warning("oauth_revoke_failed: %s", exc)

    EmailAccount.objects.filter(user_id=user_id, type=AccountType.PERSONAL).delete()
    OAuthToken.objects.filter(user_id=user_id).delete()
    return {"status": "disconnected", "count": len(accounts)}
