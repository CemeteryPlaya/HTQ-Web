"""Двусторонняя сверка «платформа ↔ почтовый сервер».

Правая сторона всегда фейковая: подменяется ``get_provisioner`` в самом
модуле сверки, живой сети нет.
"""
from __future__ import annotations

import pytest
from django.test import Client, override_settings

from apps.mail.models import MailboxStatus, ProvisionedMailbox
from apps.mail.services import reconcile_service
from apps.mail.services.crypto import crypto_service
from apps.mail.services.provisioning.base import (
    ProvisioningError,
    RemoteListingUnsupported,
    RemoteMailbox,
)
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/email/v1/mailboxes"


@pytest.fixture
def admin_auth(db):
    u = User.objects.create(
        username="rec-admin", email="rec-admin@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=True,
    )
    u.set_password("Adm1n!Pass")
    u.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(u)['access']}"}


def _mailbox(**kw) -> ProvisionedMailbox:
    defaults = dict(local_part="ivan", domain="htq.group", address="ivan@htq.group")
    defaults.update(kw)
    return ProvisionedMailbox.objects.create(**defaults)


class _FakeProvisioner:
    """Сервер со списком ящиков (как Mailcow)."""

    name = "mailcow"
    can_list_remote = True
    can_create = True

    def __init__(self, remote=(), fail_create=None):
        self.remote = list(remote)
        self.fail_create = fail_create
        self.calls = []

    def list_remote(self):
        return self.remote

    def create(self, **kw):
        self.calls.append(("create", kw["address"]))
        if self.fail_create:
            raise ProvisioningError(self.fail_create)

    def update(self, **kw):
        self.calls.append(("update", kw["address"]))

    def set_active(self, *, address, active):
        self.calls.append(("set_active", address, active))

    def delete(self, *, address):
        self.calls.append(("delete", address))

    def verify(self, *, address, password):
        return True, None


class _ProbeProvisioner(_FakeProvisioner):
    """Сервер без списка ящиков (голый IMAP)."""

    name = "imap"
    can_list_remote = False
    can_create = False

    def __init__(self, verify_results=None):
        super().__init__()
        self.verify_results = verify_results or {}

    def list_remote(self):
        raise RemoteListingUnsupported("нет списка")

    def verify(self, *, address, password):
        return self.verify_results.get(address, (True, None))


@pytest.fixture
def use_provisioner(monkeypatch):
    def _install(provisioner):
        monkeypatch.setattr(reconcile_service, "get_provisioner", lambda: provisioner)
        monkeypatch.setattr(reconcile_service, "resolve_provisioner_name", lambda: provisioner.name)
        return provisioner
    return _install


# ── режим listing ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_matching_rows_are_in_sync(use_provisioner):
    _mailbox(address="a@htq.group", quota_mb=1024, display_name="A")
    use_provisioner(_FakeProvisioner([
        RemoteMailbox(address="a@htq.group", quota_mb=1024, display_name="A", active=True),
    ]))

    report = reconcile_service.reconcile()
    assert report.mode == "listing"
    assert report.in_sync == 1
    assert report.differences == []


@pytest.mark.django_db
def test_only_local_is_detected(use_provisioner):
    _mailbox(address="ghost@htq.group")
    use_provisioner(_FakeProvisioner([]))

    report = reconcile_service.reconcile()
    kinds = [(d.kind, d.address) for d in report.differences]
    assert kinds == [("only_local", "ghost@htq.group")]


@pytest.mark.django_db
def test_only_remote_is_detected(use_provisioner):
    use_provisioner(_FakeProvisioner([
        RemoteMailbox.from_address("stranger@htq.group", quota_mb=512),
    ]))

    report = reconcile_service.reconcile()
    assert [(d.kind, d.address) for d in report.differences] == [
        ("only_remote", "stranger@htq.group"),
    ]


@pytest.mark.django_db
def test_archived_row_missing_on_server_is_not_a_difference(use_provisioner):
    """Архивный ящик на сервере выключен — его отсутствие ожидаемо."""
    _mailbox(address="old@htq.group", status=MailboxStatus.ARCHIVED)
    use_provisioner(_FakeProvisioner([]))

    report = reconcile_service.reconcile()
    assert report.differences == []
    assert report.in_sync == 1


@pytest.mark.django_db
def test_deleted_rows_are_excluded_entirely(use_provisioner):
    _mailbox(address="gone@htq.group", status=MailboxStatus.DELETED)
    use_provisioner(_FakeProvisioner([]))

    report = reconcile_service.reconcile()
    assert report.checked_local == 0
    assert report.differences == []


@pytest.mark.django_db
def test_field_mismatch_lists_diverged_fields(use_provisioner):
    _mailbox(address="a@htq.group", quota_mb=1024, display_name="Старое имя")
    use_provisioner(_FakeProvisioner([
        RemoteMailbox(address="a@htq.group", quota_mb=4096, display_name="Новое имя", active=True),
    ]))

    report = reconcile_service.reconcile()
    diff = report.differences[0]
    assert diff.kind == "mismatched"
    assert set(diff.fields) == {"quota_mb", "display_name"}


@pytest.mark.django_db
def test_zero_remote_quota_is_not_a_mismatch(use_provisioner):
    """Mailcow отдаёт 0 для безлимитного ящика — это не расхождение."""
    _mailbox(address="a@htq.group", quota_mb=1024, display_name=None)
    use_provisioner(_FakeProvisioner([
        RemoteMailbox(address="a@htq.group", quota_mb=0, display_name=None, active=True),
    ]))

    assert reconcile_service.reconcile().differences == []


@pytest.mark.django_db
def test_report_never_mutates_anything(use_provisioner):
    mb = _mailbox(address="ghost@htq.group")
    provisioner = use_provisioner(_FakeProvisioner([
        RemoteMailbox.from_address("stranger@htq.group"),
    ]))

    reconcile_service.reconcile(apply=False, direction="both")

    assert provisioner.calls == []
    mb.refresh_from_db()
    assert mb.status == "active" and mb.last_error is None
    assert not ProvisionedMailbox.objects.filter(address="stranger@htq.group").exists()


# ── применение ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_pull_imports_remote_only_mailbox(use_provisioner):
    use_provisioner(_FakeProvisioner([
        RemoteMailbox.from_address("stranger@htq.group", quota_mb=512, display_name="Гость"),
    ]))

    report = reconcile_service.reconcile(apply=True, direction="pull")

    imported = ProvisionedMailbox.objects.get(address="stranger@htq.group")
    assert imported.quota_mb == 512
    assert imported.local_part == "stranger"
    assert imported.domain == "htq.group"
    # Пользователя с таким email в платформе нет, значит и владельца у ящика
    # нет: адрес — единственный признак, по которому сверка связывает
    # (см. тесты привязки ниже).
    assert imported.user_id is None
    assert report.differences[0].action == "imported"


@pytest.mark.django_db
def test_pull_marks_only_local_as_error(use_provisioner):
    mb = _mailbox(address="ghost@htq.group")
    use_provisioner(_FakeProvisioner([]))

    reconcile_service.reconcile(apply=True, direction="pull")

    mb.refresh_from_db()
    assert mb.status == "error"
    assert "отсутствует на почтовом сервере" in mb.last_error


@pytest.mark.django_db
def test_push_creates_missing_mailbox_on_server(use_provisioner):
    mb = _mailbox(address="ghost@htq.group", status=MailboxStatus.ERROR)
    provisioner = use_provisioner(_FakeProvisioner([]))

    report = reconcile_service.reconcile(apply=True, direction="push")

    assert ("create", "ghost@htq.group") in provisioner.calls
    mb.refresh_from_db()
    # Успешное создание снимает признак ошибки.
    assert mb.status == "active" and mb.last_error is None
    assert report.differences[0].action == "created_on_server"


@pytest.mark.django_db
def test_push_failure_is_recorded_not_swallowed(use_provisioner):
    mb = _mailbox(address="ghost@htq.group")
    use_provisioner(_FakeProvisioner([], fail_create="server said no"))

    report = reconcile_service.reconcile(apply=True, direction="push")

    assert report.differences[0].action == "create_failed"
    assert "server said no" in report.differences[0].error
    mb.refresh_from_db()
    assert mb.status == "error"


@pytest.mark.django_db
def test_both_imports_remote_and_creates_local(use_provisioner):
    _mailbox(address="ghost@htq.group")
    provisioner = use_provisioner(_FakeProvisioner([
        RemoteMailbox.from_address("stranger@htq.group"),
    ]))

    reconcile_service.reconcile(apply=True, direction="both")

    assert ("create", "ghost@htq.group") in provisioner.calls
    assert ProvisionedMailbox.objects.filter(address="stranger@htq.group").exists()


@pytest.mark.django_db
def test_pull_aligns_diverged_fields_from_server(use_provisioner):
    mb = _mailbox(address="a@htq.group", quota_mb=1024, display_name="Старое")
    use_provisioner(_FakeProvisioner([
        RemoteMailbox(address="a@htq.group", quota_mb=4096, display_name="Новое", active=True),
    ]))

    reconcile_service.reconcile(apply=True, direction="pull")

    mb.refresh_from_db()
    assert mb.quota_mb == 4096
    assert mb.display_name == "Новое"


@pytest.mark.django_db
def test_pull_archives_row_when_server_says_inactive(use_provisioner):
    mb = _mailbox(address="a@htq.group", quota_mb=1024, display_name="A")
    use_provisioner(_FakeProvisioner([
        RemoteMailbox(address="a@htq.group", quota_mb=1024, display_name="A", active=False),
    ]))

    reconcile_service.reconcile(apply=True, direction="pull")

    mb.refresh_from_db()
    assert mb.status == "archived"
    assert mb.archived_at is not None


@pytest.mark.django_db
def test_push_sends_local_values_to_server(use_provisioner):
    _mailbox(address="a@htq.group", quota_mb=8192, display_name="Локальное")
    provisioner = use_provisioner(_FakeProvisioner([
        RemoteMailbox(address="a@htq.group", quota_mb=1024, display_name="Серверное", active=True),
    ]))

    reconcile_service.reconcile(apply=True, direction="push")

    assert ("update", "a@htq.group") in provisioner.calls


# ── режим probe (сервер без списка) ──────────────────────────────────────

@pytest.mark.django_db
def test_probe_mode_verifies_each_row_by_login(use_provisioner):
    mb = _mailbox(address="a@htq.group")
    mb.encrypted_smtp_app_password = crypto_service.encrypt("S3cret!")
    mb.save(update_fields=["encrypted_smtp_app_password"])
    use_provisioner(_ProbeProvisioner())

    report = reconcile_service.reconcile()
    assert report.mode == "probe"
    assert report.in_sync == 1
    assert report.differences == []


@pytest.mark.django_db
def test_probe_mode_flags_row_the_server_rejects(use_provisioner):
    mb = _mailbox(address="a@htq.group")
    mb.encrypted_smtp_app_password = crypto_service.encrypt("wrong")
    mb.save(update_fields=["encrypted_smtp_app_password"])
    use_provisioner(_ProbeProvisioner({"a@htq.group": (False, "AUTHENTICATIONFAILED")}))

    report = reconcile_service.reconcile()
    assert report.differences[0].kind == "only_local"
    assert "AUTHENTICATIONFAILED" in report.differences[0].detail


@pytest.mark.django_db
def test_probe_mode_without_stored_password_says_so(use_provisioner):
    _mailbox(address="a@htq.group")   # пароль не сохранён
    use_provisioner(_ProbeProvisioner())

    report = reconcile_service.reconcile()
    assert "Нет сохранённого пароля" in report.differences[0].detail


@pytest.mark.django_db
def test_probe_mode_never_reports_only_remote(use_provisioner):
    """Про ящики, о которых платформа не знает, голый IMAP рассказать не
    может — отчёт не должен создавать иллюзию, что их нет."""
    _mailbox(address="a@htq.group")
    use_provisioner(_ProbeProvisioner())

    report = reconcile_service.reconcile()
    assert all(d.kind != "only_remote" for d in report.differences)
    assert report.mode == "probe"


@pytest.mark.django_db
def test_unavailable_server_reports_error_without_touching_rows(use_provisioner):
    class _Down(_FakeProvisioner):
        def list_remote(self):
            raise ProvisioningError("mail server unreachable")

    mb = _mailbox(address="a@htq.group")
    use_provisioner(_Down())

    report = reconcile_service.reconcile(apply=True, direction="both")
    assert report.mode == "unavailable"
    assert "mail server unreachable" in report.errors[0]
    mb.refresh_from_db()
    assert mb.status == "active"


# ── HTTP ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reconcile_requires_admin(db):
    u = User.objects.create(
        username="plain", email="plain@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    u.set_password("Pass!2345")
    u.save()
    auth = {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(u)['access']}"}
    assert Client().get(f"{BASE}/reconcile/", **auth).status_code == 403


@pytest.mark.django_db
def test_reconcile_get_returns_report(admin_auth, use_provisioner):
    _mailbox(address="ghost@htq.group")
    use_provisioner(_FakeProvisioner([]))

    resp = Client().get(f"{BASE}/reconcile/", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is False
    assert body["counts"]["only_local"] == 1


@pytest.mark.django_db
def test_reconcile_post_applies(admin_auth, use_provisioner):
    use_provisioner(_FakeProvisioner([RemoteMailbox.from_address("stranger@htq.group")]))

    resp = Client().post(
        f"{BASE}/reconcile/", data={"apply": True, "direction": "pull"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["applied"] is True
    assert ProvisionedMailbox.objects.filter(address="stranger@htq.group").exists()


@pytest.mark.django_db
def test_reconcile_rejects_unknown_direction(admin_auth):
    resp = Client().post(
        f"{BASE}/reconcile/", data={"apply": True, "direction": "sideways"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_status_endpoint_reports_connection(admin_auth):
    with override_settings(
        MAIL_PROVISIONER="auto", MAILCOW_API_URL="", MAILCOW_API_KEY="",
        IMAP_HOST="mail-tunnel", MAILCOW_DOMAIN="htq.group",
    ):
        resp = Client().get(f"{BASE}/status/", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["provisioner"] == "imap"
    assert body["can_create_remotely"] is False


# ── привязка бесхозных ящиков к сотрудникам ──────────────────────────────
#
# Признак ровно один: адрес ящика совпадает с email пользователя. Раньше
# сверка оставляла владельца пустым всегда, и импортированные ящики висели
# мёртвыми строками, пока админ не проставит user_id руками каждому.

def _user(email: str, **kw) -> User:
    return User.objects.create(
        username=email.partition("@")[0], email=email, password="x",
        status=UserStatus.ACTIVE, **kw,
    )


def _unlinked(report):
    return [d for d in report.differences if d.kind == "unlinked"]


@pytest.mark.django_db
def test_imported_mailbox_is_linked_to_the_user_with_that_email(use_provisioner):
    """Главный сценарий: ящик приехал с сервера, а сотрудник с таким адресом
    в платформе уже есть — связываем без участия человека."""
    user = _user("sanzhar.inamzhanov@htq.group")
    use_provisioner(_FakeProvisioner([
        RemoteMailbox.from_address("sanzhar.inamzhanov@htq.group", quota_mb=2048),
    ]))

    report = reconcile_service.reconcile(apply=True, direction="pull")

    mb = ProvisionedMailbox.objects.get(address="sanzhar.inamzhanov@htq.group")
    assert mb.user_id == user.id
    assert [d.action for d in _unlinked(report)] == ["linked"]


@pytest.mark.django_db
def test_linking_creates_the_mail_account(use_provisioner):
    """Привязка — это две вещи. Без EmailAccount ящик остаётся строкой в
    админке: список писем, синхронизация и отправка ходят через аккаунт."""
    from apps.mail.models import AccountType, EmailAccount

    user = _user("ivan@htq.group")
    _mailbox(address="ivan@htq.group", local_part="ivan")
    use_provisioner(_FakeProvisioner([RemoteMailbox.from_address("ivan@htq.group")]))

    reconcile_service.reconcile(apply=True, direction="pull")

    account = EmailAccount.objects.get(user_id=user.id, address="ivan@htq.group")
    assert account.type == AccountType.CORPORATE
    assert account.is_active


@pytest.mark.django_db
def test_orphan_from_earlier_runs_is_linked_too(use_provisioner):
    """Не только свежий импорт: строки, которые висят без владельца с прошлых
    прогонов, — ровно та причина, по которой привязка вынесена отдельным
    шагом после импорта."""
    user = _user("old@htq.group")
    mb = _mailbox(address="old@htq.group", local_part="old")
    use_provisioner(_FakeProvisioner([RemoteMailbox.from_address("old@htq.group")]))

    reconcile_service.reconcile(apply=True, direction="pull")

    mb.refresh_from_db()
    assert mb.user_id == user.id


@pytest.mark.django_db
def test_address_case_does_not_prevent_linking(use_provisioner):
    """На сервере адрес может быть записан с заглавными — для почты это тот
    же ящик, и владельца он терять не должен."""
    user = _user("petrov@htq.group")
    use_provisioner(_FakeProvisioner([RemoteMailbox.from_address("Petrov@htq.group")]))

    reconcile_service.reconcile(apply=True, direction="pull")

    assert ProvisionedMailbox.objects.get(address="Petrov@htq.group").user_id == user.id


@pytest.mark.django_db
def test_report_only_shows_the_candidate_and_changes_nothing(use_provisioner):
    """Отчёт остаётся отчётом: админ видит, кому что достанется, до того как
    нажмёт «Принять данные сервера»."""
    _user("preview@htq.group")
    mb = _mailbox(address="preview@htq.group", local_part="preview")
    use_provisioner(_FakeProvisioner([RemoteMailbox.from_address("preview@htq.group")]))

    report = reconcile_service.reconcile(apply=False)

    mb.refresh_from_db()
    assert mb.user_id is None
    assert [d.action for d in _unlinked(report)] == [None]


@pytest.mark.django_db
def test_shared_mailbox_without_a_user_stays_ownerless(use_provisioner):
    """``info@``, ``sales@`` — общие ящики. Пользователя с таким email нет,
    и выдумывать владельца не из чего."""
    mb = _mailbox(address="info@htq.group", local_part="info")
    use_provisioner(_FakeProvisioner([RemoteMailbox.from_address("info@htq.group")]))

    report = reconcile_service.reconcile(apply=True, direction="pull")

    mb.refresh_from_db()
    assert mb.user_id is None
    assert _unlinked(report) == []


@pytest.mark.django_db
def test_user_who_already_has_a_mailbox_is_reported_not_relinked(use_provisioner):
    """user_id в ProvisionedMailbox — UNIQUE: второй ящик тому же сотруднику
    не привязать. Это решение человека, а не повод уронить прогон
    исключением из середины."""
    user = _user("dup@htq.group")
    _mailbox(address="primary@htq.group", local_part="primary", user_id=user.id)
    orphan = _mailbox(address="dup@htq.group", local_part="dup")
    use_provisioner(_FakeProvisioner([
        RemoteMailbox.from_address("primary@htq.group"),
        RemoteMailbox.from_address("dup@htq.group"),
    ]))

    report = reconcile_service.reconcile(apply=True, direction="pull")

    orphan.refresh_from_db()
    assert orphan.user_id is None
    diff = _unlinked(report)[0]
    assert diff.action == "skipped"
    assert diff.error == "user_already_has_mailbox"


@pytest.mark.django_db
def test_counts_expose_linking_to_the_admin_page(use_provisioner):
    _user("counted@htq.group")
    _mailbox(address="counted@htq.group", local_part="counted")
    use_provisioner(_FakeProvisioner([RemoteMailbox.from_address("counted@htq.group")]))

    body = reconcile_service.reconcile(apply=True, direction="pull").to_dict()

    assert body["counts"]["unlinked"] == 1
    assert body["counts"]["linked"] == 1
