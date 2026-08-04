"""``manage.py mail_check`` — печать отчёта и код возврата.

Поведение самих проверок покрыто в ``test_connection_check.py`` (там же, где
живёт логика). Здесь — только то, за что отвечает команда: отрисовка шагов,
подсказок и подробностей, подстановка сохранённого пароля и ненулевой код
возврата при провале.
"""
from __future__ import annotations

import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.mail.models import ProvisionedMailbox
from apps.mail.services import connection_check
from apps.mail.services.connection_check import CheckReport, CheckStep
from apps.mail.services.crypto import crypto_service

SECRET = "SuperSecret!42"


def _run(**kwargs) -> tuple[str, bool]:
    out = io.StringIO()
    failed = False
    try:
        call_command("mail_check", stdout=out, stderr=out, **kwargs)
    except CommandError:
        failed = True
    return out.getvalue(), failed


@pytest.fixture
def stub_check(monkeypatch):
    """Подменить проверку заранее заданным отчётом и запомнить аргументы."""
    calls = {}

    def _install(report: CheckReport):
        def _fake(**kwargs):
            calls.update(kwargs)
            return report
        monkeypatch.setattr(connection_check, "run_check", _fake)
        return calls
    return _install


@pytest.mark.django_db
def test_failing_report_gives_nonzero_exit(stub_check):
    report = CheckReport()
    report.add(CheckStep(
        key="imap_port", title="IMAP: порт", status=connection_check.FAIL,
        detail="mail-tunnel:1143 — недоступен", hint="поднимите туннель",
    ))
    stub_check(report)

    output, failed = _run(timeout=1)

    assert failed, "провал проверки обязан давать ненулевой код возврата"
    assert "[FAIL]" in output
    assert "mail-tunnel:1143 — недоступен" in output
    assert "→ поднимите туннель" in output


@pytest.mark.django_db
def test_passing_report_exits_cleanly(stub_check):
    report = CheckReport()
    report.add(CheckStep(key="config", title="Настройки", status=connection_check.OK,
                         detail="Режим imap"))
    stub_check(report)

    output, failed = _run(timeout=1)

    assert not failed
    assert "[ ok ]" in output
    assert "Все проверки пройдены" in output


@pytest.mark.django_db
def test_skipped_steps_are_shown_without_failing(stub_check):
    report = CheckReport()
    report.add(CheckStep(key="imap", title="IMAP", status=connection_check.SKIP,
                         detail="Порт недоступен"))
    stub_check(report)

    output, failed = _run(timeout=1)

    assert not failed
    assert "[ -- ]" in output


@pytest.mark.django_db
def test_folder_details_are_printed(stub_check):
    """Список папок и счётчики — главное, ради чего команду и запускают
    глазами: по ним подбирают правильные имена для синхронизации."""
    report = CheckReport()
    report.add(CheckStep(
        key="folders", title="Папки синхронизации", status=connection_check.OK,
        detail="Найдены",
        data={"available": ["INBOX", "Sent Items"],
              "counts": {"INBOX": {"messages": 3, "uidvalidity": 12}}},
    ))
    stub_check(report)

    output, _ = _run(timeout=1)

    assert "Sent Items" in output
    assert "писем 3" in output
    assert "uidvalidity=12" in output


@pytest.mark.django_db
def test_stored_password_is_passed_to_the_check(stub_check):
    """Для уже заведённого ящика пароль вводить не нужно."""
    ProvisionedMailbox.objects.create(
        local_part="i.ivanov", domain="htq.group", address="i.ivanov@htq.group",
        encrypted_smtp_app_password=crypto_service.encrypt(SECRET),
    )
    calls = stub_check(CheckReport())

    output, failed = _run(mailbox="i.ivanov@htq.group", timeout=1)

    assert not failed
    assert calls["password"] == SECRET
    assert SECRET not in output      # но в вывод он не попадает


@pytest.mark.django_db
def test_explicit_password_wins_over_the_stored_one(stub_check):
    ProvisionedMailbox.objects.create(
        local_part="i.ivanov", domain="htq.group", address="i.ivanov@htq.group",
        encrypted_smtp_app_password=crypto_service.encrypt("old-one"),
    )
    calls = stub_check(CheckReport())

    _run(mailbox="i.ivanov@htq.group", password="brand-new", timeout=1)

    assert calls["password"] == "brand-new"


@pytest.mark.django_db
def test_unknown_mailbox_passes_no_password(stub_check):
    calls = stub_check(CheckReport())

    _run(mailbox="nobody@htq.group", timeout=1)

    assert calls["password"] is None
