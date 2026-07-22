"""Бизнес-логика писем — порт ``services/email/app/api/v1/emails.py`` (6
эндпойнтов): ``GET /folder/{folder}``, ``GET /unread-counts/``,
``GET /{message_id}``, ``POST /send``, ``POST /{message_id}/read``,
``POST /draft``.

Авторизация (решение 2 брифа mail-messages): все шесть — обычный залогиненный
пользователь (``get_current_user`` исходника) → ``api_view(auth="jwt")``,
СТРОГИЙ user-scoping — каждый запрос фильтрует ``EmailMessage`` по
``user_id`` из JWT, чужое/несуществующее → 404 "Email not found" (не 403,
буквально как в исходнике и как в mail-core account_service.py).

``services/email/app/services/email_service.py`` исходника — МЁРТВЫЙ код: он
импортирует ``app.models.domain`` (модуль, которого не существует в этом
сервисе) и оперирует полями (``sender_id``, ``is_draft``, ``sent_at``,
``EmailRecipientStatus``), которых нет ни в одной реальной модели
(``app/models/email.py``). Ни один роутер его не импортирует — реальная
бизнес-логика ``send_email`` целиком инлайнена в
``app/api/v1/emails.py::send_email``. Порт здесь идёт от РЕАЛЬНОГО кода
роутера, а не от мёртвого файла.
"""
from __future__ import annotations

from django.db.models import Count
from django.utils import timezone

from apps.mail.models import EmailAccount, EmailMessage, RecipientStatus
from apps.mail.services.dlp_scanner import dlp_scanner

VALID_FOLDERS = {"inbox", "sent", "drafts", "trash", "archive", "spam", "outbox"}


class InvalidFolder(Exception):
    """400 "Invalid folder"."""


class EmailNotFound(Exception):
    """404 "Email not found"."""


class AccountNotFound(Exception):
    """404 "Account not found" (не найден ИЛИ не свой — как в mail-core)."""


class AccountInactive(Exception):
    """409 "Account is inactive"."""


class DLPViolation(Exception):
    """403 "DLP Policy Violation: Sensitive data detected."."""


def _serialize_summary(msg: EmailMessage) -> dict:
    """EmailMessageRead (schemas/email.py исходника)."""
    return {
        "id": str(msg.id),
        "account_id": msg.account_id,
        "subject": msg.subject,
        "snippet": msg.snippet,
        "sender_email": msg.sender_email,
        "sender_name": msg.sender_name,
        "to_recipients": msg.to_recipients,
        "cc_recipients": msg.cc_recipients,
        "date": msg.date.isoformat(),
        "is_read": msg.is_read,
        "is_flagged": msg.is_flagged,
        "has_attachments": msg.has_attachments,
        "folder": msg.folder,
        "provider_folder": msg.provider_folder,
    }


def _serialize_detail(msg: EmailMessage) -> dict:
    """EmailMessageDetail (schemas/email.py исходника).

    ``attachments`` ВСЕГДА ``[]`` — буквальный перенос особенности
    исходника: ``get_email`` (emails.py) комментирует "Optional: fetch
    attachments if needed (not fully joined here for simplicity)" и
    возвращает ORM-объект ``msg`` напрямую; ``EmailMessage`` SQLAlchemy-модель
    не объявляет relationship ``attachments`` вовсе, так что
    ``EmailMessageDetail.model_validate(msg)`` всегда падает на дефолт схемы
    (``[]``), а не на реальный список вложений — не наша недоработка, а
    воспроизведённое поведение исходника."""
    out = _serialize_summary(msg)
    out["body_html"] = msg.body_html
    out["body_text"] = msg.body_text
    out["attachments"] = []
    return out


def list_emails(
    user_id: int, *, folder: str, account_id: int | None = None,
    limit: int = 50, offset: int = 0,
) -> list[dict]:
    if folder not in VALID_FOLDERS:
        raise InvalidFolder
    qs = EmailMessage.objects.filter(user_id=user_id, folder=folder)
    if account_id is not None:
        qs = qs.filter(account_id=account_id)
    qs = qs.order_by("-date")[offset:offset + limit]
    return [_serialize_summary(m) for m in qs]


def unread_counts(user_id: int) -> dict:
    """``{by_account: {id: n}, by_folder: {name: n}}`` — порт
    emails.py::unread_counts (два коррелированных COUNT ... GROUP BY)."""
    by_account_rows = (
        EmailMessage.objects.filter(
            user_id=user_id, folder="inbox", is_read=False, account_id__isnull=False,
        )
        .values("account_id")
        .annotate(n=Count("id"))
    )
    by_account = {int(row["account_id"]): int(row["n"]) for row in by_account_rows}

    by_folder_rows = (
        EmailMessage.objects.filter(user_id=user_id, is_read=False)
        .values("folder")
        .annotate(n=Count("id"))
    )
    by_folder = {str(row["folder"]): int(row["n"]) for row in by_folder_rows}

    return {"by_account": by_account, "by_folder": by_folder}


def get_email(user_id: int, message_id) -> dict:
    msg = EmailMessage.objects.filter(id=message_id, user_id=user_id).first()
    if msg is None:
        raise EmailNotFound
    return _serialize_detail(msg)


def send_email(
    user_id: int, *, account_id: int, to_recipients: list[dict],
    cc_recipients: list[dict] | None = None, bcc_recipients: list[dict] | None = None,
    subject: str = "", body_html: str | None = None, body_text: str | None = None,
) -> dict:
    """Порт emails.py::send_email — до постановки в очередь доставки.

    ``attachment_ids`` схемы исходника (schemas/email.py::EmailSendRequest)
    намеренно НЕ принимается здесь — сам роутер исходника его тоже никогда
    не читает (см. schemas.py::EmailSendRequest docstring) — не наше
    упрощение, а буквальный перенос mёртвого поля.
    """
    account = EmailAccount.objects.filter(id=account_id).first()
    if account is None or account.user_id != user_id:
        raise AccountNotFound
    if not account.is_active:
        raise AccountInactive

    # DLP-скан только пользовательского ввода — как в исходнике.
    content = (subject or "") + " " + (body_text or "") + " " + (body_html or "")
    if dlp_scanner.scan(content):
        raise DLPViolation

    msg = EmailMessage.objects.create(
        user_id=user_id,
        account_id=account.id,
        folder="outbox",
        subject=subject or "",
        snippet=(subject or "")[:255],
        body_html=body_html,
        body_text=body_text,
        sender_email=account.address,
        sender_name=account.display_name,
        to_recipients=to_recipients or [],
        cc_recipients=cc_recipients or [],
        bcc_recipients=bcc_recipients or [],
        is_read=True,  # outbound messages are always read by sender
        date=timezone.now(),
    )

    for r in (to_recipients or []) + (cc_recipients or []) + (bcc_recipients or []):
        addr = r.get("email") if isinstance(r, dict) else None
        if not addr:
            continue
        RecipientStatus.objects.create(
            message=msg, recipient_email=addr, status="pending",
        )

    # TODO(workers-под-задача): исходник здесь вызывает
    # ``deliver_email.send(str(msg.id))`` — dramatiq-актор
    # (workers/actors.py::_do_deliver), который резолвит
    # ``apps/mail/services/sender/factory.py::get_sender(account.provider)``
    # и реально шлёт письмо (SMTP/Gmail API/Graph API) АСИНХРОННО, уже ПОСЛЕ
    # того, как этот HTTP-эндпоинт вернул 202. Наблюдаемый контракт ЭТОГО
    # эндпойнта (202 + outbox-строка + pending recipient-статусы) идентичен
    # исходнику ДО постановки в очередь — сама постановка (Celery-эквивалент
    # dramatiq-актора) появится вместе с под-задачей workers (Р2 брифа).
    # Sender-стратегии (mailcow SMTP / Gmail API / Graph API) уже перенесены
    # и юнит-тестируются в apps/mail/services/sender/* — актор здесь их
    # просто ещё не вызывает.

    return {"status": "queued", "id": str(msg.id)}


def mark_as_read(user_id: int, message_id) -> None:
    """UPDATE ... WHERE id= AND user_id=, БЕЗ проверки rowcount — 204
    возвращается независимо от того, нашлась ли строка (буквально как в
    исходнике: ``update(EmailMessage).where(...)`` без проверки, попал ли
    UPDATE хоть в одну строку)."""
    EmailMessage.objects.filter(id=message_id, user_id=user_id).update(is_read=True)


def save_draft(user_id: int, *, subject: str = "", body: str = "") -> dict:
    """Минимальный stub — порт emails.py::save_draft (без MTA, без
    получателей — существует только чтобы кнопка "Save draft" в SPA не
    падала 404-кой, буквально как в исходнике)."""
    msg = EmailMessage.objects.create(
        user_id=user_id,
        account_id=None,
        folder="drafts",
        subject=subject or "",
        snippet=(subject or "")[:100],
        body_text=body or "",
        body_html="",
        sender_email="",
        to_recipients=[],
        cc_recipients=[],
        bcc_recipients=[],
        date=timezone.now(),
    )
    return {"id": str(msg.id), "folder": "drafts"}
