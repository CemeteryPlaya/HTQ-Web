"""Синхронизация писем корпоративного ящика по IMAP — в обе стороны.

Замыкает цепочку, у которой раньше было собрано всё, кроме середины:
``imap_client.py`` (новый) даёт живое соединение, ``mailcow_imap.parse_eml``
разбирает байты письма, ``mapper.upsert_message`` кладёт результат в БД. Не
хватало модуля, который свяжет их и будет вести курсор — вот он.

**Вниз (сервер → платформа).** По каждой папке из ``MAIL_SYNC_FOLDERS``
забираются письма с UID больше сохранённого курсора. Курсор лежит в
``EmailAccount.sync_state`` — поле, заведённое «для паритета схемы» и до сих
пор никем не заполнявшееся:

    {"imap": {"INBOX": {"uidvalidity": 12, "last_uid": 940}, ...}}

``UIDVALIDITY`` проверяется обязательно: если сервер её сменил, прежние UID
недействительны и курсор сбрасывается — иначе синхронизация тихо пропустила
бы всю папку.

**Вверх (платформа → сервер).** Письма, прочитанные в интерфейсе платформы,
помечаются ``\\Seen`` на сервере (``MAIL_SYNC_PUSH_FLAGS``), поэтому в
почтовом клиенте они тоже перестают быть новыми. Без этого «синхронизация»
была бы односторонней выгрузкой.

``message_id`` для IMAP-писем собирается как ``<папка>:<uidvalidity>:<uid>``:
он обязан быть стабильным (на нём висит уникальный индекс
``ux_email_messages_account_message`` и весь UPSERT) и обязан позволять
обратное преобразование в UID, иначе флаги некуда толкать. RFC822 Message-ID
для этого не годится: он есть не у всех писем и не говорит, где письмо лежит.
"""
from __future__ import annotations

import logging
import re

from django.conf import settings
from django.utils import timezone

from apps.mail.models import EmailMessage, ProvisionedMailbox
from apps.mail.services.crypto import crypto_service
from apps.mail.services.imap_client import ImapClient, ImapError, ImapNotConfigured
from apps.mail.services.mail_config import get_config
from apps.mail.services.sync.base import SyncResult
from apps.mail.services.sync.mailcow_imap import parse_eml
from apps.mail.services.sync.mapper import imap_mailbox_to_folder, replace_attachments, upsert_message

log = logging.getLogger(__name__)

#: провайдеры, которые ходят на почтовый сервер по IMAP
IMAP_PROVIDERS = ("mailcow", "imap")

_MESSAGE_ID_RE = re.compile(r"^(?P<folder>.+):(?P<uidvalidity>\d+):(?P<uid>\d+)$")


def build_message_id(folder: str, uidvalidity: int | None, uid: int) -> str:
    return f"{folder}:{uidvalidity or 0}:{uid}"


def parse_message_id(message_id: str) -> tuple[str, int, int] | None:
    """``INBOX:12:940`` → ``("INBOX", 12, 940)``; чужой формат → None."""
    match = _MESSAGE_ID_RE.match(message_id or "")
    if not match:
        return None
    return (
        match.group("folder"),
        int(match.group("uidvalidity")),
        int(match.group("uid")),
    )


def resolve_credentials(account) -> tuple[str, str] | None:
    """``(логин, пароль)`` ящика или None, если учётки нет.

    Два источника: собственные реквизиты аккаунта (подключён пользователем по
    IMAP) и пароль выданного корпоративного ящика. Первый проверяется раньше:
    если пользователь ввёл свои реквизиты, они и есть истина для этого
    аккаунта.
    """
    if account.imap_settings_id is not None:
        from apps.mail.services import imap_account_service

        return imap_account_service.credentials_for(account)

    if not account.mailbox_id:
        return None
    mb = ProvisionedMailbox.objects.filter(id=account.mailbox_id).first()
    if mb is None or not mb.encrypted_smtp_app_password:
        return None
    try:
        return account.address, crypto_service.decrypt(mb.encrypted_smtp_app_password)
    except Exception as exc:  # noqa: BLE001 — битый шифротекст не должен ронять воркер
        log.warning("imap_credentials_decrypt_failed account=%s: %s", account.id, exc)
        return None


def imap_client_for(account) -> ImapClient:
    """Клиент на СВОЙ сервер аккаунта, иначе — на корпоративный.

    Аккаунт, подключённый пользователем по IMAP, живёт на чужом сервере
    (gmail, хостинг подрядчика): ходить за его письмами на корпоративный хост
    бессмысленно и опасно — попали бы в чужой ящик при совпадении логинов.
    """
    if account.imap_settings_id is not None:
        from apps.mail.services import imap_account_service

        client = imap_account_service.client_for(account)
        if client is not None:
            return client
    return ImapClient.from_settings()


def _folder_state(account, folder: str) -> dict:
    return ((account.sync_state or {}).get("imap") or {}).get(folder) or {}


def _save_folder_state(account, folder: str, *, uidvalidity: int | None, last_uid: int) -> None:
    state = dict(account.sync_state or {})
    imap_state = dict(state.get("imap") or {})
    imap_state[folder] = {"uidvalidity": uidvalidity, "last_uid": last_uid}
    state["imap"] = imap_state
    account.sync_state = state
    account.save(update_fields=["sync_state", "updated_at"])


def sync_account(account, *, limit: int | None = None) -> SyncResult:
    """Прогнать одну синхронизацию для одного ``EmailAccount``.

    Ошибки соединения не выбрасываются наружу — они пишутся в
    ``account.last_sync_error`` и возвращаются в ``SyncResult.errors``:
    периодический воркер не должен падать из-за одного недоступного ящика.
    """
    result = SyncResult()

    credentials = resolve_credentials(account)
    if credentials is None:
        message = "нет сохранённой учётки ящика — синхронизировать нечем"
        result.errors.append(message)
        _stamp_error(account, message)
        return result

    username, password = credentials
    cfg = get_config()
    folders = list(cfg.sync_folders)
    max_messages = limit or cfg.sync_max_messages

    try:
        client = imap_client_for(account)
    except ImapNotConfigured as exc:
        result.errors.append(str(exc))
        _stamp_error(account, str(exc))
        return result

    try:
        with client.login(username, password) as imap:
            for folder in folders:
                try:
                    result = result.merge(
                        _sync_folder(imap, account, folder, limit=max_messages)
                    )
                except (ImapError, OSError) as exc:
                    # Одна недоступная папка (например, «Sent» названа иначе)
                    # не повод бросать остальные. OSError — сетевые сбои,
                    # они тоже не должны уносить весь прогон.
                    log.info("imap_folder_skipped account=%s folder=%s: %s", account.id, folder, exc)
                    result.errors.append(f"{folder}: {exc}")
    except (ImapError, OSError) as exc:
        result.errors.append(str(exc))
        _stamp_error(account, str(exc))
        return result

    account.last_sync_at = timezone.now()
    account.last_sync_error = "; ".join(result.errors) if result.errors else None
    account.save(update_fields=["last_sync_at", "last_sync_error", "updated_at"])
    log.info(
        "imap_sync_done account=%s inserted=%d updated=%d attachments=%d errors=%d",
        account.id, result.inserted, result.updated, result.attachments_saved, len(result.errors),
    )
    return result


def _stamp_error(account, message: str) -> None:
    account.last_sync_error = message
    account.save(update_fields=["last_sync_error", "updated_at"])


def _sync_folder(imap: ImapClient, account, folder: str, *, limit: int) -> SyncResult:
    result = SyncResult()

    state = _folder_state(account, folder)
    server_state = imap.select(folder, readonly=True)
    uidvalidity = server_state.get("uidvalidity")

    last_uid = state.get("last_uid") or 0
    if state.get("uidvalidity") and uidvalidity and state["uidvalidity"] != uidvalidity:
        # Сервер пересобрал папку — старые UID больше ничего не значат.
        log.info(
            "imap_uidvalidity_changed account=%s folder=%s %s→%s — курсор сброшен",
            account.id, folder, state.get("uidvalidity"), uidvalidity,
        )
        last_uid = 0

    canonical_folder, provider_folder = imap_mailbox_to_folder(folder)

    uids = imap.search_uids(since_uid=last_uid or None)
    if not uids:
        return result

    highest = last_uid
    try:
        # Берём САМЫЕ СТАРЫЕ из необработанных, а не самые новые.
        # С «новыми» курсор после первого же прогона прыгал на максимальный
        # UID, и всё, что старее, навсегда считалось обработанным: в ящике
        # 299 писем, в платформе — 73, и больше ничего не приезжало.
        # Хронологический порядок докачивает ящик порциями за несколько
        # прогонов, а новая почта (uid > курсора) приходит как обычно.
        for uid in uids[:limit] if limit else uids:
            try:
                fetched = imap.fetch(uid)
            except (ImapError, OSError) as exc:
                # Сетевой сбой (типично: таймаут на большом письме с
                # вложением) — ПРЕКРАЩАЕМ папку, а не пропускаем письмо.
                # Пропуск сдвинул бы курсор за неполученное письмо, и оно
                # исчезло бы навсегда; обрыв же сохраняет прогресс до
                # последнего успешного UID, и следующий прогон продолжит
                # ровно оттуда.
                #
                # ``OSError`` здесь обязателен: socket-таймаут — НЕ ImapError,
                # и раньше он улетал наружу мимо сохранения курсора. Из-за
                # этого каждый прогон начинался с нуля, добирался до того же
                # письма и падал — синхронизация крутилась вечно, не двигаясь.
                log.warning(
                    "imap_fetch_failed account=%s folder=%s uid=%s: %s — "
                    "прогон папки прерван, прогресс сохранён до uid=%s",
                    account.id, folder, uid, exc, highest,
                )
                result.errors.append(f"{folder}:{uid}: {exc}")
                break
            if fetched is None:
                result.skipped += 1
                continue

            try:
                parsed = parse_eml(fetched.raw)
            except Exception as exc:  # noqa: BLE001 — одно битое письмо не рушит прогон
                # В отличие от сетевого сбоя это НЕ пройдёт при повторе:
                # письмо действительно не разбирается. Пропускаем и двигаем
                # курсор, иначе одно битое письмо заблокировало бы папку.
                log.warning("imap_parse_failed account=%s uid=%s: %s", account.id, uid, exc)
                result.errors.append(f"{folder}:{uid}: parse failed")
                highest = max(highest, uid)
                continue

            attachments = parsed.pop("attachments", []) or []
            parsed.pop("rfc822_message_id", None)

            message_pk, created = upsert_message(
                user_id=account.user_id,
                account_id=account.id,
                message_id=build_message_id(folder, uidvalidity, uid),
                folder=canonical_folder,
                provider_folder=provider_folder,
                is_read=fetched.is_read,
                is_flagged=fetched.is_flagged,
                has_attachments=bool(attachments),
                **parsed,
            )
            if created:
                result.inserted += 1
            else:
                result.updated += 1

            if attachments:
                message = EmailMessage.objects.filter(id=message_pk).first()
                if message is not None:
                    result.attachments_saved += replace_attachments(message, attachments)

            highest = max(highest, uid)
    finally:
        # Курсор сохраняется ВСЕГДА, даже если прогон прервался исключением.
        # Иначе уже сохранённые в БД письма не считались бы обработанными, и
        # следующий прогон начинал бы папку заново — вплоть до бесконечного
        # цикла без единого нового письма.
        if highest != last_uid or uidvalidity != state.get("uidvalidity"):
            _save_folder_state(account, folder, uidvalidity=uidvalidity, last_uid=highest)

    return result


# ── обратное направление: локальные флаги → сервер ────────────────────────

def push_read_flags(imap: ImapClient, account) -> int:
    """Проставить ``\\Seen`` на сервере письмам, прочитанным в платформе.

    Идёт по прочитанным письмам аккаунта, группирует их по папке и толкает
    одним ``UID STORE`` на папку. Повторный вызов безвреден: ``+FLAGS
    (\\Seen)`` идемпотентен, поэтому отдельная колонка «уже синхронизировано»
    не нужна.
    """
    if not get_config().sync_push_flags:
        return 0

    by_folder: dict[str, list[int]] = {}
    rows = EmailMessage.objects.filter(
        account_id=account.id, is_read=True, message_id__isnull=False,
    ).values_list("message_id", flat=True)
    for message_id in rows:
        parsed = parse_message_id(message_id)
        if parsed is None:
            continue
        folder, _uidvalidity, uid = parsed
        by_folder.setdefault(folder, []).append(uid)

    pushed = 0
    for folder, uids in by_folder.items():
        try:
            pushed += imap.set_seen(folder, sorted(uids), seen=True)
        except ImapError as exc:
            log.info("imap_flag_push_failed account=%s folder=%s: %s", account.id, folder, exc)
    return pushed


def sync_account_two_way(account, *, limit: int | None = None) -> SyncResult:
    """Полный двусторонний прогон: сначала вниз, потом флаги наверх.

    Порядок важен: сперва забираем серверное состояние (чтобы не затереть
    прочтения, сделанные в почтовом клиенте), затем толкаем своё.
    """
    result = sync_account(account, limit=limit)
    if result.errors and result.inserted == 0 and result.updated == 0:
        return result

    credentials = resolve_credentials(account)
    if credentials is None:
        return result
    username, password = credentials
    try:
        with imap_client_for(account).login(username, password) as imap:
            pushed = push_read_flags(imap, account)
            if pushed:
                log.info("imap_flags_pushed account=%s count=%d", account.id, pushed)
    except (ImapError, ImapNotConfigured) as exc:
        result.errors.append(f"flag push: {exc}")
    return result
