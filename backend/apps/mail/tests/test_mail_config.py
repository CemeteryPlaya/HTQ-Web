"""Резолвер настроек почты: БД поверх env.

Отдельно — сторож границы: реквизиты сервера читаются ТОЛЬКО через
``mail_config``. Прямой ``getattr(settings, "IMAP_HOST", ...)`` где-нибудь в
домене означал бы, что значение, заданное админом в интерфейсе, для этого
куска кода не существует, — и такой разрыв заметили бы уже на живой почте.
"""
from __future__ import annotations

import pathlib
import re

import pytest
from django.test import override_settings

from apps.mail.models import MailServerConfig
from apps.mail.services import mail_config


@pytest.fixture(autouse=True)
def _clear_cache():
    mail_config.invalidate()
    yield
    mail_config.invalidate()


def _row(**kw) -> MailServerConfig:
    row, _ = MailServerConfig.objects.get_or_create(pk=MailServerConfig.SINGLETON_PK)
    for key, value in kw.items():
        setattr(row, key, value)
    row.save()
    mail_config.invalidate()
    return row


# ── слияние ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_without_a_row_everything_comes_from_env():
    """Обратная совместимость: окружение, где UI не трогали, — как раньше."""
    with override_settings(IMAP_HOST="mail-tunnel", IMAP_PORT=1143, MAILCOW_DOMAIN="htq.group"):
        cfg = mail_config.get_config()

    assert cfg.imap_host == "mail-tunnel"
    assert cfg.imap_port == 1143
    assert cfg.domain == "htq.group"
    assert cfg.overridden == frozenset()


@pytest.mark.django_db
def test_db_value_wins_over_env():
    _row(imap_host="mail.htq.group")
    with override_settings(IMAP_HOST="mail-tunnel"):
        cfg = mail_config.get_config()

    assert cfg.imap_host == "mail.htq.group"
    assert "imap_host" in cfg.overridden


@pytest.mark.django_db
def test_empty_db_field_falls_back_to_env():
    _row(imap_host="")
    with override_settings(IMAP_HOST="mail-tunnel"):
        assert mail_config.get_config().imap_host == "mail-tunnel"


@pytest.mark.django_db
def test_whitespace_only_counts_as_empty():
    _row(imap_host="   ")
    with override_settings(IMAP_HOST="mail-tunnel"):
        assert mail_config.get_config().imap_host == "mail-tunnel"


@pytest.mark.django_db
def test_false_from_db_overrides_true_from_env():
    """Ради этого случая булевы поля nullable: обычный BooleanField не
    отличил бы «выключено» от «не задано»."""
    _row(imap_ssl=False)
    with override_settings(IMAP_SSL=True):
        assert mail_config.get_config().imap_ssl is False


@pytest.mark.django_db
def test_null_boolean_means_inherit():
    _row(imap_ssl=None)
    with override_settings(IMAP_SSL=True):
        assert mail_config.get_config().imap_ssl is True


@pytest.mark.django_db
def test_domain_typos_are_normalized():
    _row(domain="@htq.group")
    assert mail_config.get_config().domain == "htq.group"


@pytest.mark.django_db
def test_sync_folders_are_split_from_a_comma_list():
    _row(sync_folders="INBOX, Sent Items ,Черновики")
    assert mail_config.get_config().sync_folders == ["INBOX", "Sent Items", "Черновики"]


@pytest.mark.django_db
def test_smtp_falls_back_to_the_imap_host():
    """Типовой случай: один хост и для IMAP, и для submission."""
    _row(imap_host="mail-tunnel", smtp_host="")
    assert mail_config.get_config().effective_smtp_host() == "mail-tunnel"


@pytest.mark.django_db
def test_override_settings_is_not_defeated_by_the_cache():
    """Кэшируется только чтение строки. Закэшируй мы смерженный результат,
    подмена настроек молча не действовала бы до истечения TTL."""
    with override_settings(IMAP_HOST="first"):
        assert mail_config.get_config().imap_host == "first"
    with override_settings(IMAP_HOST="second"):
        assert mail_config.get_config().imap_host == "second"


@pytest.mark.django_db
def test_configured_flags_reflect_reality():
    with override_settings(MAILCOW_API_URL="", MAILCOW_API_KEY="", IMAP_HOST=""):
        cfg = mail_config.get_config()
        assert cfg.imap_configured is False and cfg.mailcow_configured is False

    _row(imap_host="mail-tunnel", mailcow_api_url="https://mail/api/v1")
    with override_settings(MAILCOW_API_KEY="k"):
        cfg = mail_config.get_config()
    assert cfg.imap_configured is True and cfg.mailcow_configured is True


# ── сторож границы ───────────────────────────────────────────────────────

BACKEND = pathlib.Path(__file__).resolve().parents[3]
MAIL_APP = BACKEND / "apps" / "mail"

#: настройки, которые обязаны идти через mail_config
GUARDED = re.compile(
    r'getattr\(\s*settings\s*,\s*["\'](MAILCOW_[A-Z_]+|IMAP_[A-Z_]+|SMTP_[A-Z_]+|MAIL_SYNC_[A-Z_]+|MAIL_PROVISIONER|MAIL_RECONCILE_[A-Z_]+)["\']'
)

#: единственный файл, которому положено читать их напрямую — сам резолвер
ALLOWED = {"services/mail_config.py"}


def test_mail_settings_are_read_only_through_the_resolver():
    """Сторож: значение, заданное админом в интерфейсе, должно действовать
    ВЕЗДЕ. Прямое чтение settings в обход ``mail_config`` создало бы участок
    кода, для которого UI-настройки просто не существуют."""
    violations = []
    for path in MAIL_APP.rglob("*.py"):
        rel = path.relative_to(MAIL_APP).as_posix()
        if "tests/" in rel or rel in ALLOWED:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = GUARDED.search(line)
            if match:
                violations.append(f"apps/mail/{rel}:{lineno}: {match.group(1)}")

    assert violations == [], (
        "Настройки почты читаются только через apps.mail.services.mail_config."
        "get_config() — иначе значения, заданные в интерфейсе, для этого кода "
        "не существуют:\n  " + "\n  ".join(violations)
    )


# ── шаблон адреса ────────────────────────────────────────────────────────

@pytest.mark.parametrize("pattern,expected", [
    ("first.last", "sanzhar.inamzhanov"),
    ("f.last", "s.inamzhanov"),
    ("firstlast", "sanzharinamzhanov"),
    ("first_last", "sanzhar_inamzhanov"),
    ("flast", "sinamzhanov"),
    ("last.first", "inamzhanov.sanzhar"),
    ("first", "sanzhar"),
])
def test_local_part_patterns(pattern, expected):
    """Соглашение об именовании у каждой компании своё; в IMAP-режиме промах
    здесь означает адрес, которого на сервере нет."""
    from apps.mail.services.mailbox_service import autogen_local_part

    assert autogen_local_part("Санжар", "Инамжанов", pattern) == expected


def test_unknown_pattern_falls_back_to_the_historical_default():
    from apps.mail.services.mailbox_service import autogen_local_part

    assert autogen_local_part("Санжар", "Инамжанов", "нет-такого") == "s.inamzhanov"


def test_pattern_is_skipped_when_one_name_is_missing():
    from apps.mail.services.mailbox_service import autogen_local_part

    assert autogen_local_part("Санжар", "", "first.last") == "sanzhar"
    assert autogen_local_part("", "", "first.last") == "user"


@pytest.mark.django_db
def test_pattern_default_stays_historical_for_untouched_installs():
    """Менять дефолт глобально нельзя — сломались бы уже работающие
    инсталляции, где адреса выданы как i.ivanov."""
    from apps.mail.services.mailbox_service import autogen_local_part

    with override_settings(MAILBOX_LOCAL_PART_PATTERN="f.last"):
        assert autogen_local_part("Иван", "Иванов") == "i.ivanov"


@pytest.mark.django_db
def test_pattern_from_db_overrides_env():
    from apps.mail.services.mailbox_service import autogen_local_part

    _row(local_part_pattern="first.last")
    with override_settings(MAILBOX_LOCAL_PART_PATTERN="f.last"):
        assert autogen_local_part("Санжар", "Инамжанов") == "sanzhar.inamzhanov"
