"""Бизнес-логика unified-аккаунтов — порт
``services/email/app/api/v1/accounts.py`` (4 эндпойнта).

Р2 (бриф mail-core): dramatiq-события/фоновая постановка
(``incremental_sync_account.send(...)``) НЕ портируются — ``trigger_sync``
здесь только резолвит/валидирует аккаунт и возвращает форму ответа
исходника; фактическая постановка в очередь появится вместе с
под-задачей workers (Celery в этом Django-порту, см. CLAUDE.md).

Растяжка unread_count: исходник считает его коррелированным подзапросом к
``EmailMessage`` (folder=inbox, is_read=false). ``EmailMessage`` — модель
под-задачи messages, ещё не перенесена (вне зоны этой под-задачи) — здесь
``unread_count`` всегда 0. tests/test_stretch.py::
test_unread_count_todo_is_tracked падает в момент появления
``apps.mail.models.EmailMessage``, требуя раскрыть реальный подсчёт.
"""
from __future__ import annotations

import logging

from django.db import transaction

from apps.mail.models import AccountType, EmailAccount, OAuthToken
from apps.mail.services.crypto import crypto_service
from apps.mail.services.oauth_clients import get_oauth_client

log = logging.getLogger(__name__)


class AccountNotFound(Exception):
    """404 — Account not found (порт исходника: не найден ИЛИ не свой)."""


class AccountInactive(Exception):
    """409 — Account is inactive."""


class CorporateAccountProtected(Exception):
    """400 — corporate-ящики удаляются через /mailboxes/{id}/archive/."""


def _get_owned(user_id: int, account_id: int) -> EmailAccount:
    account = EmailAccount.objects.filter(id=account_id).first()
    if account is None or account.user_id != user_id:
        raise AccountNotFound
    return account


def serialize(account: EmailAccount, *, unread_count: int = 0) -> dict:
    """EmailAccountRead (schemas/account.py исходника)."""
    return {
        "id": account.id,
        "type": account.type,
        "provider": account.provider,
        "address": account.address,
        "display_name": account.display_name,
        "is_default": account.is_default,
        "is_active": account.is_active,
        "last_sync_at": account.last_sync_at.isoformat() if account.last_sync_at else None,
        "last_sync_error": account.last_sync_error,
        "watch_expires_at": account.watch_expires_at.isoformat() if account.watch_expires_at else None,
        "connected_at": account.connected_at.isoformat(),
        # TODO(messages-под-задача): реальный подсчёт непрочитанных из
        # EmailMessage (folder=inbox, is_read=false) — см. растяжку в
        # tests/test_stretch.py.
        "unread_count": unread_count,
    }


def list_accounts(user_id: int) -> list[dict]:
    qs = EmailAccount.objects.filter(user_id=user_id).order_by("-is_default", "id")
    return [serialize(a) for a in qs]


@transaction.atomic
def set_default_account(user_id: int, account_id: int) -> dict:
    account = _get_owned(user_id, account_id)
    EmailAccount.objects.filter(user_id=user_id, is_default=True).update(is_default=False)
    account.is_default = True
    account.save(update_fields=["is_default", "updated_at"])
    account.refresh_from_db()
    return serialize(account)


def trigger_sync(user_id: int, account_id: int) -> dict:
    account = _get_owned(user_id, account_id)
    if not account.is_active:
        raise AccountInactive

    from django.utils import timezone

    return {
        "account_id": account.id,
        "queued_at": timezone.now().isoformat(),
        "status": "queued",
    }


def disconnect_account(user_id: int, account_id: int) -> None:
    """Порт accounts.py::disconnect_account.

    Корпоративные (Mailcow) аккаунты защищены — их удаление идёт через
    ``/mailboxes/{id}/archive/`` (двухстадийный флоу под админ-контролем).
    Личные (OAuth) аккаунты: best-effort revoke у провайдера (никогда не
    роняет запрос — только warning в лог), затем удаление EmailAccount +
    OAuthToken.

    Порядок двух DELETE НЕ совпадает построчно с исходником (там сперва
    ``delete(OAuthToken)``, потом ``delete(EmailAccount)``) — намеренно
    развёрнут. Причина: ``EmailAccount.oauth_token`` — ``on_delete=SET_NULL``,
    а ``ck_email_accounts_type_consistency`` требует ``oauth_token_id IS NOT
    NULL`` при ``type='personal'``. Порядок исходника удаляет OAuthToken
    ПЕРВЫМ, что триггерит ON DELETE SET NULL на ещё живой personal-строке
    EmailAccount и ломает её же CHECK-констрейнт — тот же живой баг
    воспроизводится и на Postgres FastAPI-исходника (его тестовая сюита
    гоняется на SQLite, где FK-триггер не включён по умолчанию — см.
    CLAUDE.md, — поэтому там он никогда не срабатывал). Здесь тесты бьют в
    реальный Postgres (test.py), поэтому обнажили: удаление EmailAccount
    ПЕРВЫМ убирает единственную ссылающуюся строку до того, как OAuthToken
    исчезает — ON DELETE SET NULL после этого действовать не на что, CHECK
    не нарушается. Конечное состояние (обе строки удалены, revoke
    best-effort) идентично исходнику — меняется только порядок двух DELETE.
    """
    account = _get_owned(user_id, account_id)
    if account.type == AccountType.CORPORATE:
        raise CorporateAccountProtected

    token_row = None
    if account.oauth_token_id is not None:
        token_row = OAuthToken.objects.filter(id=account.oauth_token_id).first()
        if token_row is not None:
            try:
                client = get_oauth_client(account.provider)
                access = crypto_service.decrypt(token_row.encrypted_access_token)
                client.revoke(access)
            except Exception as exc:  # best-effort, буквально как в исходнике
                log.warning("oauth_revoke_failed: %s", exc)

    account.delete()
    if token_row is not None:
        token_row.delete()
