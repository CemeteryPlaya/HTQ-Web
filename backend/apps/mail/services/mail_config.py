"""Эффективные реквизиты почтового сервера: БД поверх env.

Единственная точка, откуда домен mail берёт настройки подключения. До этого
модуля каждый потребитель читал ``getattr(settings, "IMAP_HOST", "")``
напрямую, из-за чего настройки можно было задать только через ``.env`` +
перезапуск контейнеров. Теперь поверх env лежит редактируемая из интерфейса
строка ``MailServerConfig``.

Правило слияния одно и оно намеренно простое: **пустое поле в БД = «берём из
env»**. Поэтому

* окружение, где через UI ничего не заводили, ведёт себя бит-в-бит как
  раньше (обратная совместимость);
* env остаётся рабочим способом первоначальной раскатки и аварийного
  восстановления — его не нужно чистить, чтобы что-то поправить из UI;
* чтобы вернуть поле к значению из env, достаточно очистить его в форме.

Булевы поля в БД — ``BooleanField(null=True)``, потому что обычный булев не
отличил бы «выключено» от «не задано»: ``imap_ssl=False`` обязано уметь
перекрывать ``IMAP_SSL=true`` из env.

Кэшируется ТОЛЬКО чтение строки из БД (5 секунд, fail-open — тот же приём и
тот же TTL, что у ``apps.core.services.service_status``), а слияние с
``settings`` выполняется на каждом вызове. Разница принципиальная: закэшируй
мы готовый результат, ``override_settings`` перестал бы действовать до
истечения TTL — то есть тесты и любой код, временно подменяющий настройки,
молча получали бы устаревшие значения. Слияние стоит десяток getattr'ов,
экономить на нём нечего.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)

_CACHE_KEY = "mail-server-config"
_CACHE_TTL = 5


@dataclass(frozen=True)
class MailConfig:
    """Готовые к употреблению значения — уже слитые, без «а вдруг пусто»."""

    provisioner: str
    domain: str

    imap_host: str
    imap_port: int
    imap_ssl: bool
    imap_starttls: bool
    imap_tls_server_hostname: str
    imap_timeout: int

    smtp_host: str
    smtp_port: int
    smtp_ssl: bool
    smtp_starttls: bool
    smtp_timeout: int

    mailcow_api_url: str
    mailcow_api_key: str
    mailcow_default_quota_mb: int

    sync_folders: list[str] = field(default_factory=list)
    sync_max_messages: int = 200
    sync_push_flags: bool = True

    allow_self_service: bool = False
    reconcile_auto_apply: bool = False
    reconcile_auto_link: bool = True
    local_part_pattern: str = "f.last"

    #: какие поля реально пришли из БД — показывается в UI, чтобы админ видел,
    #: что перекрыто, а что унаследовано из окружения
    overridden: frozenset[str] = frozenset()

    @property
    def mailcow_configured(self) -> bool:
        return bool(self.mailcow_api_url and self.mailcow_api_key)

    @property
    def imap_configured(self) -> bool:
        return bool(self.imap_host)

    def effective_smtp_host(self) -> str:
        """SMTP там же, где IMAP, если отдельно не задан — типовой случай."""
        return self.smtp_host or self.imap_host


def _normalize_domain(raw: str) -> str:
    """Тот же нормализатор, что и для env (см. settings/base.py::_mail_domain).

    Значение из формы проходит ровно ту же чистку: пользователь одинаково
    легко впишет ``@htq.group`` и в ``.env``, и в поле на странице.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    for scheme in ("https://", "http://"):
        if value.lower().startswith(scheme):
            value = value[len(scheme):]
    value = value.split("/")[0].strip().lstrip("@").strip()
    if "@" in value:
        value = value.rsplit("@", 1)[-1].strip()
    return value.rstrip(".").lower()


#: поля строки настроек, участвующие в слиянии
_ROW_FIELDS = (
    "provisioner", "domain",
    "imap_host", "imap_port", "imap_ssl", "imap_starttls", "imap_tls_server_hostname",
    "smtp_host", "smtp_port", "smtp_ssl", "smtp_starttls",
    "mailcow_api_url", "encrypted_mailcow_api_key",
    "sync_folders", "sync_push_flags", "allow_self_service", "local_part_pattern",
)


def _read_row() -> dict | None:
    """Строка настроек как обычный dict (или None, если её нет).

    Dict, а не модель: значение уезжает в кэш, а пиклить модель Django ради
    шестнадцати полей незачем. Отсутствие таблицы/строки — не ошибка: до
    первого ``migrate`` таблицы ещё нет, а импорт домена уже может случиться.
    """
    from apps.mail.models import MailServerConfig

    try:
        row = MailServerConfig.objects.filter(pk=MailServerConfig.SINGLETON_PK).first()
    except Exception:  # noqa: BLE001 — таблицы может не быть до migrate
        log.debug("mail_config_table_unavailable", exc_info=True)
        return None
    if row is None:
        return None
    return {name: getattr(row, name) for name in _ROW_FIELDS}


def _row() -> dict | None:
    """Кэшированное чтение строки (5с, fail-open).

    Кэшируется именно ЭТО, а не готовый ``MailConfig`` — см. докстринг модуля
    про ``override_settings``.
    """
    try:
        cached = cache.get(_CACHE_KEY)
    except Exception:  # noqa: BLE001 — недоступный Redis не должен ронять почту
        log.warning("mail_config_cache_get_failed", exc_info=True)
        return _read_row()

    if cached is None:
        row = _read_row()
        # None кладём как сентинел: «строки нет» — тоже результат, и его надо
        # кэшировать, иначе на каждый вызов будет поход в БД.
        try:
            cache.set(_CACHE_KEY, {"row": row}, _CACHE_TTL)
        except Exception:  # noqa: BLE001
            log.warning("mail_config_cache_set_failed", exc_info=True)
        return row
    return cached.get("row")


def _decrypt(value: str) -> str:
    if not value:
        return ""
    from apps.mail.services.crypto import crypto_service

    try:
        return crypto_service.decrypt(value)
    except Exception as exc:  # noqa: BLE001 — битый шифротекст не должен ронять почту
        log.warning("mail_config_secret_decrypt_failed: %s", exc)
        return ""


def get_config() -> MailConfig:
    """Эффективные настройки: строка из БД (кэш 5с) поверх ``settings``."""
    row = _row()
    overridden: set[str] = set()

    def pick(field_name: str, env_value, *, transform=None):
        """Значение из БД, если оно задано; иначе из env."""
        if row is None:
            return env_value
        raw = row.get(field_name)
        empty = raw is None or (isinstance(raw, str) and not raw.strip())
        if empty:
            return env_value
        overridden.add(field_name)
        return transform(raw) if transform else raw

    domain = pick("domain", getattr(settings, "MAILCOW_DOMAIN", ""), transform=_normalize_domain)

    folders_raw = pick("sync_folders", None)
    if folders_raw:
        folders = [f.strip() for f in str(folders_raw).split(",") if f.strip()]
    else:
        folders = list(getattr(settings, "MAIL_SYNC_FOLDERS", ["INBOX"]))

    api_key_env = getattr(settings, "MAILCOW_API_KEY", "")
    if row is not None and row.get("encrypted_mailcow_api_key"):
        overridden.add("mailcow_api_key")
        api_key = _decrypt(row["encrypted_mailcow_api_key"])
    else:
        api_key = api_key_env

    return MailConfig(
        provisioner=(pick("provisioner", getattr(settings, "MAIL_PROVISIONER", "auto")) or "auto").strip().lower(),
        domain=domain,

        imap_host=pick("imap_host", getattr(settings, "IMAP_HOST", "")),
        imap_port=int(pick("imap_port", getattr(settings, "IMAP_PORT", 993))),
        imap_ssl=bool(pick("imap_ssl", getattr(settings, "IMAP_SSL", True))),
        imap_starttls=bool(pick("imap_starttls", getattr(settings, "IMAP_STARTTLS", False))),
        imap_tls_server_hostname=pick(
            "imap_tls_server_hostname", getattr(settings, "IMAP_TLS_SERVER_HOSTNAME", ""),
        ),
        imap_timeout=int(getattr(settings, "IMAP_TIMEOUT", 30)),

        smtp_host=pick("smtp_host", getattr(settings, "SMTP_HOST", "")),
        smtp_port=int(pick("smtp_port", getattr(settings, "SMTP_PORT", 587))),
        smtp_ssl=bool(pick("smtp_ssl", getattr(settings, "SMTP_SSL", False))),
        smtp_starttls=bool(pick("smtp_starttls", getattr(settings, "SMTP_STARTTLS", True))),
        smtp_timeout=int(getattr(settings, "SMTP_TIMEOUT", 30)),

        mailcow_api_url=pick("mailcow_api_url", getattr(settings, "MAILCOW_API_URL", "")),
        mailcow_api_key=api_key,
        mailcow_default_quota_mb=int(getattr(settings, "MAILCOW_DEFAULT_QUOTA_MB", 1024)),

        sync_folders=folders,
        sync_max_messages=int(getattr(settings, "MAIL_SYNC_MAX_MESSAGES", 200)),
        sync_push_flags=bool(pick("sync_push_flags", getattr(settings, "MAIL_SYNC_PUSH_FLAGS", True))),

        local_part_pattern=(pick(
            "local_part_pattern", getattr(settings, "MAILBOX_LOCAL_PART_PATTERN", "f.last"),
        ) or "f.last").strip().lower(),

        allow_self_service=bool(row.get("allow_self_service")) if row is not None else False,
        reconcile_auto_apply=bool(getattr(settings, "MAIL_RECONCILE_AUTO_APPLY", False)),
        reconcile_auto_link=bool(getattr(settings, "MAIL_RECONCILE_AUTO_LINK", True)),

        overridden=frozenset(overridden),
    )


def invalidate() -> None:
    """Сбросить кэш — зовётся сразу после сохранения настроек, чтобы админ
    видел результат правки немедленно, а не через 5 секунд."""
    try:
        cache.delete(_CACHE_KEY)
    except Exception:  # noqa: BLE001
        log.warning("mail_config_cache_delete_failed", exc_info=True)
