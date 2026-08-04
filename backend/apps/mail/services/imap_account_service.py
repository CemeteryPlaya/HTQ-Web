"""Подключение произвольного почтового аккаунта по IMAP/SMTP.

Третий способ добавить почту, рядом с OAuth (Gmail/Outlook) и корпоративным
ящиком платформы. Нужен для всего, что не покрывают первые два: личный ящик
на своём хостинге, почта подрядчика, второй домен компании, любой сервер, о
котором платформа ничего не знает. Пользователь указывает реквизиты сам —
ровно как в почтовом клиенте.

Отличия от ``self_service.py`` (самоподключение КОРПОРАТИВНОГО ящика), с
которым легко перепутать:

* там сервер один и задан админом — здесь пользователь вводит хост и порт;
* там домен адреса обязан совпасть с корпоративным — здесь домен любой;
* там создаётся ``ProvisionedMailbox`` (ящик числится за платформой) — здесь
  только ``EmailAccount`` + ``ImapAccountSettings``: платформа не управляет
  этим ящиком, а лишь читает и отправляет через него.

Учётка ВСЕГДА проверяется живым IMAP-входом до записи в БД: молча
сохранённые неверные реквизиты выглядели бы как рабочее подключение, а
ломались бы позже и не на глазах у пользователя.
"""
from __future__ import annotations

import logging

from django.db import transaction

from apps.mail.models import (
    AccountProvider,
    AccountType,
    EmailAccount,
    ImapAccountSettings,
)
from apps.mail.services.crypto import crypto_service
from apps.mail.services.imap_client import ImapClient, ImapConfig, ImapError

log = logging.getLogger(__name__)


class AccountAlreadyConnected(Exception):
    """409 — этот адрес у пользователя уже подключён."""

    def __init__(self, address: str) -> None:
        self.detail = f"Ящик {address} уже подключён"
        super().__init__(self.detail)


class ImapVerificationFailed(Exception):
    """400 — сервер не принял реквизиты."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


# ── Автоопределение сервера по домену ────────────────────────────────────
#
# Помогает не гадать над портами: у крупных провайдеров они общеизвестны и
# стабильны. Список намеренно короткий — только то, чем реально пользуются;
# для всего остального форма даёт ввести хост вручную, и это не хуже.
# Значения — из публичной документации соответствующих провайдеров.

WELL_KNOWN = {
    "gmail.com": {"imap_host": "imap.gmail.com", "smtp_host": "smtp.gmail.com"},
    "googlemail.com": {"imap_host": "imap.gmail.com", "smtp_host": "smtp.gmail.com"},
    "yandex.ru": {"imap_host": "imap.yandex.ru", "smtp_host": "smtp.yandex.ru", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False},
    "yandex.com": {"imap_host": "imap.yandex.com", "smtp_host": "smtp.yandex.com", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False},
    "ya.ru": {"imap_host": "imap.yandex.ru", "smtp_host": "smtp.yandex.ru", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False},
    "mail.ru": {"imap_host": "imap.mail.ru", "smtp_host": "smtp.mail.ru", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False},
    "bk.ru": {"imap_host": "imap.mail.ru", "smtp_host": "smtp.mail.ru", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False},
    "inbox.ru": {"imap_host": "imap.mail.ru", "smtp_host": "smtp.mail.ru", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False},
    "list.ru": {"imap_host": "imap.mail.ru", "smtp_host": "smtp.mail.ru", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False},
    "outlook.com": {"imap_host": "outlook.office365.com", "smtp_host": "smtp.office365.com"},
    "hotmail.com": {"imap_host": "outlook.office365.com", "smtp_host": "smtp.office365.com"},
    "icloud.com": {"imap_host": "imap.mail.me.com", "smtp_host": "smtp.mail.me.com"},
}

DEFAULTS = {
    "imap_port": 993, "imap_ssl": True, "imap_starttls": False,
    "smtp_port": 587, "smtp_ssl": False, "smtp_starttls": True,
}


def suggest_settings(address: str) -> dict:
    """Предзаполнение формы по адресу.

    Три источника, в порядке убывания достоверности:

    1. **Корпоративный сервер платформы**, если домен адреса — корпоративный.
       Это точно известный хост, а не догадка: гадать ``imap.<домен>`` там,
       где настоящий адрес уже настроен админом, — прямой путь к ошибке
       «Name or service not known» на несуществующем хосте.
    2. **Известный провайдер** (gmail, яндекс, …) — его документированные
       хосты и порты.
    3. **Догадка** ``imap.<домен>`` — верна удивительно часто, но помечается
       ``guessed``, чтобы интерфейс не выдавал её за факт.
    """
    domain = (address or "").strip().lower().rsplit("@", 1)[-1]
    if not domain or "@" in domain:
        return {**DEFAULTS, "imap_host": "", "smtp_host": "", "known": False, "guessed": False}

    corporate = _corporate_suggestion(domain)
    if corporate:
        return corporate

    known = WELL_KNOWN.get(domain)
    if known:
        return {**DEFAULTS, **known, "known": True, "guessed": False}
    return {
        **DEFAULTS,
        "imap_host": f"imap.{domain}",
        "smtp_host": f"smtp.{domain}",
        "known": False,
        "guessed": True,
    }


def _corporate_suggestion(domain: str) -> dict | None:
    """Настройки корпоративного сервера, если адрес из его домена."""
    from apps.mail.services.mail_config import get_config

    cfg = get_config()
    if not cfg.domain or domain != cfg.domain.lower() or not cfg.imap_host:
        return None
    return {
        "imap_host": cfg.imap_host,
        "imap_port": cfg.imap_port,
        "imap_ssl": cfg.imap_ssl,
        "imap_starttls": cfg.imap_starttls,
        "smtp_host": cfg.effective_smtp_host(),
        "smtp_port": cfg.smtp_port,
        "smtp_ssl": cfg.smtp_ssl,
        "smtp_starttls": cfg.smtp_starttls,
        "known": True,
        "guessed": False,
        # Чтобы интерфейс мог сказать, откуда значения, — и подсказать, что
        # для своего корпоративного ящика есть отдельная кнопка.
        "corporate": True,
    }


# ── Подключение ──────────────────────────────────────────────────────────

def _config_from(payload) -> ImapConfig:
    return ImapConfig(
        host=payload.imap_host.strip(),
        port=payload.imap_port,
        use_ssl=payload.imap_ssl,
        starttls=payload.imap_starttls,
    )


def verify(payload) -> tuple[bool, str | None, list[str]]:
    """``(ok, error, папки)`` — живой вход без записи в БД.

    Список папок возвращается, чтобы форма могла сразу показать, что именно
    увидела платформа: это лучшее подтверждение «реквизиты верные», чем
    просто «успешно».
    """
    client = ImapClient(_config_from(payload))
    username = (payload.username or payload.address).strip()
    try:
        with client.login(username, payload.password) as imap:
            return True, None, imap.list_folders()
    except ImapError as exc:
        return False, str(exc), []
    except Exception as exc:  # noqa: BLE001 — подключение не должно падать 500
        return False, f"IMAP error: {exc}", []


def explain_failure(error: str, host: str) -> str:
    """Превратить техническую ошибку в то, что можно исправить.

    ``[Errno -2] Name or service not known`` ничего не говорит человеку,
    который просто хотел подключить почту, — а означает вполне конкретное:
    такого хоста не существует. Чаще всего это наша же догадка
    ``imap.<домен>``, не совпавшая с реальностью, и правильное действие —
    спросить настоящий адрес, а не перебирать пароли.
    """
    lowered = error.lower()

    if "name or service not known" in lowered or "nodename nor servname" in lowered \
            or "getaddrinfo" in lowered or "name resolution" in lowered:
        return (
            f"Сервер «{host}» не найден — такого адреса не существует. "
            "Уточните адрес IMAP-сервера у почтового администратора или в "
            "инструкции провайдера и впишите его вручную."
        )

    if "authenticationfailed" in lowered or "login failed" in lowered \
            or "invalid credentials" in lowered or "auth" in lowered:
        return (
            "Сервер отклонил логин или пароль. Проверьте их. "
            "Многие провайдеры (Gmail, Яндекс, Mail.ru) требуют отдельный "
            "«пароль приложения» вместо пароля от аккаунта, а некоторые — "
            "логин без домена."
        )

    if "timed out" in lowered or "timeout" in lowered:
        return (
            f"Сервер «{host}» не ответил вовремя. Проверьте адрес и порт, "
            "а также доступность сервера из сети платформы."
        )

    if "refused" in lowered:
        return (
            f"Сервер «{host}» отклонил подключение на указанном порту. "
            "Обычно IMAP — 993 (SSL) или 143 (STARTTLS); проверьте порт и режим шифрования."
        )

    if "ssl" in lowered or "certificate" in lowered:
        return (
            f"Не удалось установить защищённое соединение с «{host}»: {error}. "
            "Проверьте режим шифрования — на 993 обычно SSL/TLS, на 143 — STARTTLS."
        )

    return f"Почтовый сервер не принял реквизиты: {error}"


@transaction.atomic
def connect(*, user_id: int, payload) -> EmailAccount:
    """Проверить реквизиты и подключить аккаунт пользователю."""
    address = payload.address.strip().lower()

    if EmailAccount.objects.filter(user_id=user_id, address=address).exists():
        raise AccountAlreadyConnected(address)

    ok, error, _folders = verify(payload)
    if not ok:
        raise ImapVerificationFailed(explain_failure(error or "", payload.imap_host))

    settings_row = ImapAccountSettings.objects.create(
        imap_host=payload.imap_host.strip(),
        imap_port=payload.imap_port,
        imap_ssl=payload.imap_ssl,
        imap_starttls=payload.imap_starttls,
        smtp_host=(payload.smtp_host or "").strip(),
        smtp_port=payload.smtp_port,
        smtp_ssl=payload.smtp_ssl,
        smtp_starttls=payload.smtp_starttls,
        username=(payload.username or address).strip(),
        encrypted_password=crypto_service.encrypt(payload.password),
    )

    is_first = not EmailAccount.objects.filter(user_id=user_id).exists()
    account = EmailAccount.objects.create(
        user_id=user_id,
        type=AccountType.PERSONAL,
        provider=AccountProvider.IMAP,
        address=address,
        display_name=(payload.display_name or "").strip() or None,
        imap_settings=settings_row,
        is_default=is_first,
        is_active=True,
    )
    log.info("imap_account_connected user_id=%s address=%s", user_id, address)
    return account


def update_password(*, user_id: int, account_id: int, password: str) -> EmailAccount:
    """Сменить сохранённый пароль (пользователь поменял его на сервере).

    Новый пароль тоже проверяется входом: иначе синхронизация встала бы молча.
    """
    account = EmailAccount.objects.filter(id=account_id, user_id=user_id).first()
    if account is None or account.imap_settings_id is None:
        raise EmailAccount.DoesNotExist

    row = account.imap_settings
    client = ImapClient(ImapConfig(
        host=row.imap_host, port=row.imap_port,
        use_ssl=row.imap_ssl, starttls=row.imap_starttls,
    ))
    try:
        with client.login(row.username, password):
            pass
    except ImapError as exc:
        raise ImapVerificationFailed(f"Новый пароль не принят сервером: {exc}") from exc

    row.encrypted_password = crypto_service.encrypt(password)
    row.save(update_fields=["encrypted_password", "updated_at"])
    if account.last_sync_error:
        account.last_sync_error = None
        account.save(update_fields=["last_sync_error", "updated_at"])
    return account


def credentials_for(account) -> tuple[str, str] | None:
    """``(логин, пароль)`` аккаунта или None. Используется синхронизацией и
    отправкой — они не должны знать, где именно лежит учётка."""
    if account.imap_settings_id is None:
        return None
    row = account.imap_settings
    try:
        return row.username, crypto_service.decrypt(row.encrypted_password)
    except Exception as exc:  # noqa: BLE001 — битый шифротекст не роняет воркер
        log.warning("imap_account_password_decrypt_failed account=%s: %s", account.id, exc)
        return None


def client_for(account) -> ImapClient | None:
    """IMAP-клиент, настроенный на СВОЙ сервер аккаунта."""
    if account.imap_settings_id is None:
        return None
    row = account.imap_settings
    return ImapClient(ImapConfig(
        host=row.imap_host, port=row.imap_port,
        use_ssl=row.imap_ssl, starttls=row.imap_starttls,
    ))
