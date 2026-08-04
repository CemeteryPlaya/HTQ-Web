"""Чтение и запись настроек почтового сервера из интерфейса.

Форма на странице «Корпоративные ящики» правит одну синглтон-строку
``MailServerConfig``. Два правила, вокруг которых собран этот модуль:

1. **Пустое поле = «брать из окружения».** Поэтому форма показывает не
   «текущее значение», а два разных факта: что записано в БД (``value``) и
   что реально действует (``effective``). Иначе админ не отличит «я задал
   993» от «993 пришло из env» и, очистив поле, удивится, что ничего не
   изменилось.
2. **Секреты не читаются наружу.** Mailcow API-ключ отдаётся флагом
   ``mailcow_api_key_set``; записать новый можно, прочитать старый — нет.
   Пустая строка в запросе означает «не менять», явный ``null`` — «стереть».
"""
from __future__ import annotations

from apps.mail.models import MailServerConfig
from apps.mail.services import mail_config
from apps.mail.services.crypto import crypto_service

#: поля, которые форма правит напрямую (секреты — отдельно)
EDITABLE = (
    "provisioner", "domain",
    "imap_host", "imap_port", "imap_ssl", "imap_starttls", "imap_tls_server_hostname",
    "smtp_host", "smtp_port", "smtp_ssl", "smtp_starttls",
    "mailcow_api_url",
    "sync_folders", "sync_push_flags", "allow_self_service", "local_part_pattern",
)


def get_row() -> MailServerConfig:
    """Синглтон-строка; создаётся при первом обращении, пустая."""
    row, _ = MailServerConfig.objects.get_or_create(pk=MailServerConfig.SINGLETON_PK)
    return row


def serialize() -> dict:
    """Что показать в форме: сохранённые значения + реально действующие."""
    row = get_row()
    cfg = mail_config.get_config()

    return {
        # то, что записано в БД («» / null = наследуем из окружения)
        "value": {name: getattr(row, name) for name in EDITABLE},
        # то, что действует прямо сейчас — с учётом окружения
        "effective": {
            "provisioner": cfg.provisioner,
            "resolved_provisioner": _resolved_name(),
            "domain": cfg.domain,
            "imap_host": cfg.imap_host,
            "imap_port": cfg.imap_port,
            "imap_ssl": cfg.imap_ssl,
            "imap_starttls": cfg.imap_starttls,
            "imap_tls_server_hostname": cfg.imap_tls_server_hostname,
            "smtp_host": cfg.effective_smtp_host(),
            "smtp_port": cfg.smtp_port,
            "smtp_ssl": cfg.smtp_ssl,
            "smtp_starttls": cfg.smtp_starttls,
            "mailcow_api_url": cfg.mailcow_api_url,
            "sync_folders": cfg.sync_folders,
            "sync_push_flags": cfg.sync_push_flags,
            "allow_self_service": cfg.allow_self_service,
            "local_part_pattern": cfg.local_part_pattern,
        },
        # какие поля перекрыты из интерфейса, а какие унаследованы из env —
        # форма помечает их, чтобы «почему не применилось» не возникало
        "overridden": sorted(cfg.overridden),
        "mailcow_api_key_set": bool(row.encrypted_mailcow_api_key or cfg.mailcow_api_key),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by_user_id": row.updated_by_user_id,
    }


def _resolved_name() -> str:
    from apps.mail.services.provisioning import resolve_provisioner_name

    return resolve_provisioner_name()


def update(payload, *, user_id: int | None = None) -> dict:
    """Записать настройки. Возвращает ту же форму, что и ``serialize``."""
    row = get_row()

    data = payload.model_dump(exclude_unset=True)

    for name in EDITABLE:
        if name not in data:
            continue
        value = data[name]
        if name == "domain" and value:
            # Та же чистка, что и для env: «@htq.group» и «https://…» —
            # типовые опечатки, и в форме их делают ровно так же.
            value = mail_config._normalize_domain(value)
        if name == "sync_folders" and isinstance(value, list):
            value = ",".join(f.strip() for f in value if f.strip())
        setattr(row, name, "" if value is None and _is_text_field(name) else value)

    # Секрет: "" = не менять (форма не знает старого значения),
    # null = стереть и вернуться к переменной окружения.
    if "mailcow_api_key" in data:
        secret = data["mailcow_api_key"]
        if secret is None:
            row.encrypted_mailcow_api_key = ""
        elif secret:
            row.encrypted_mailcow_api_key = crypto_service.encrypt(secret)

    row.updated_by_user_id = user_id
    row.save()

    # Кэш строки живёт 5 секунд — без сброса админ увидел бы старое значение
    # сразу после сохранения и решил, что форма не работает.
    mail_config.invalidate()
    return serialize()


def _is_text_field(name: str) -> bool:
    return name in (
        "provisioner", "domain", "imap_host", "imap_tls_server_hostname",
        "smtp_host", "mailcow_api_url", "sync_folders", "local_part_pattern",
    )
