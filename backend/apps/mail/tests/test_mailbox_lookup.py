"""Сверка адреса: «такой ящик уже есть → подключить его, а не плодить дубль».

Проверяемое поведение и его цена, если оно сломается:

* платформа смотрит НЕ ТОЛЬКО в свою таблицу — иначе ящик, заведённый почтовым
  администратором мимо неё, оборачивается вторым, пустым ``i.ivanov2``;
* «сервер не ответил» ≠ «ящика нет» — иначе недоступный Mailcow разрешает
  создание поверх живого ящика;
* подключение — это не только ``user_id``: без ``EmailAccount`` и пароля ящик
  «подключён» лишь на бумаге, почта не идёт;
* старое поведение там, где подключать нельзя (ящик занят другим сотрудником,
  подключать некому), сохранено дословно.

Живой сети нет: подменяются ``get_provisioner`` в ``mailbox_service`` И в
``lookup_service`` — сверка ходит на сервер сама, отдельно от создания.
"""
from __future__ import annotations

import pytest
from django.test import Client, override_settings

from apps.mail.models import EmailAccount, MailboxStatus, ProvisionedMailbox
from apps.mail.services import lookup_service
from apps.mail.services import mailbox_service as mbx_svc
from apps.mail.services.crypto import crypto_service
from apps.mail.services.provisioning.base import ProvisioningError
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/email/v1/mailboxes"

#: Настройки, при которых режим РЕЗОЛВИТСЯ в mailcow. Нужны там, где тест
#: проверяет ``awaits_password``: тот читает режим из настроек, а не из
#: подменённого провижинера, и с одним лишь доменом получил бы "none".
MAILCOW_ENV = {
    "MAILCOW_DOMAIN": "htq.group",
    "MAILCOW_API_URL": "https://mailcow.test/api/v1",
    "MAILCOW_API_KEY": "test-key",
}


# ── фейковые почтовые серверы ────────────────────────────────────────────

class _FakeMailcow:
    """Сервер с админ-API: умеет и создать ящик, и сказать, есть ли он."""

    name = "mailcow"
    can_list_remote = True
    can_create = True
    requires_existing_mailbox = False

    def __init__(self, remote: set[str] | None = None, unreachable: str | None = None):
        self.remote = {a.lower() for a in (remote or set())}
        self.unreachable = unreachable
        self.calls: list[tuple[str, dict]] = []

    def create(self, **kw):
        self.calls.append(("create", kw))
        self.remote.add(kw["address"].lower())

    def issue_app_password(self, **kw):
        self.calls.append(("issue_app_password", kw))

    def exists_remote(self, *, address):
        if self.unreachable:
            return None, self.unreachable
        return address.lower() in self.remote, None

    def verify(self, *, address, password):
        exists, detail = self.exists_remote(address=address)
        return bool(exists), None if exists else (detail or "mailbox not found on server")

    def update(self, **kw):
        self.calls.append(("update", kw))

    def reset_password(self, **kw):
        self.calls.append(("reset_password", kw))

    def set_active(self, **kw):
        self.calls.append(("set_active", kw))

    def delete(self, **kw):
        self.calls.append(("delete", kw))

    def list_remote(self):
        return []


class _FakeImap:
    """Сервер без админ-API: ящик существует, но проверить его можно только
    логином, а выпустить себе пароль нельзя — нет ``issue_app_password``."""

    name = "imap"
    can_list_remote = False
    can_create = False
    requires_existing_mailbox = True

    def __init__(self, passwords: dict[str, str] | None = None):
        self.passwords = {k.lower(): v for k, v in (passwords or {}).items()}
        self.calls: list[tuple[str, dict]] = []

    def create(self, **kw):
        self.calls.append(("create", kw))

    def exists_remote(self, *, address):
        return None, "IMAP не умеет проверить существование ящика без пароля"

    def verify(self, *, address, password):
        if password and self.passwords.get(address.lower()) == password:
            return True, None
        return False, "login failed"

    def update(self, **kw):
        self.calls.append(("update", kw))

    def reset_password(self, **kw):
        self.calls.append(("reset_password", kw))

    def set_active(self, **kw):
        self.calls.append(("set_active", kw))

    def delete(self, **kw):
        self.calls.append(("delete", kw))

    def list_remote(self):
        return []


@pytest.fixture
def use_provisioner(monkeypatch):
    """Подменить сервер во ВСЕХ модулях, которые его резолвят.

    Подмен несколько, а не одна: каждый модуль делает
    ``from ...provisioning import get_provisioner``, то есть держит
    собственную ссылку. Пропусти один — и тест незаметно проверял бы часть
    сценария против настоящего провижинера (а он в тестах ходит в сеть).
    """
    from apps.mail.services import self_service

    def _install(provisioner):
        for module in (mbx_svc, lookup_service, self_service):
            monkeypatch.setattr(module, "get_provisioner", lambda: provisioner)
        return provisioner
    return _install


@pytest.fixture
def admin_auth(db):
    u = User.objects.create(
        username="lookup-admin", email="lookup-admin@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=True,
    )
    u.set_password("Adm1n!Pass")
    u.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(u)['access']}"}


@pytest.fixture
def plain_auth(db):
    u = User.objects.create(
        username="lookup-user", email="lookup-user@htq.test", password="x",
        status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!")
    u.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(u)['access']}"}


class _Payload:
    """Форма создания в том объёме, который читает ``provision``."""

    def __init__(self, **kw):
        self.local_part = kw.get("local_part", "")
        self.email = kw.get("email", "")
        self.first_name = kw.get("first_name", "")
        self.last_name = kw.get("last_name", "")
        self.full_name = kw.get("full_name", "")
        self.password = kw.get("password", "")
        self.quota_mb = kw.get("quota_mb", 0)
        self.user_id = kw.get("user_id")
        self.attach_if_exists = kw.get("attach_if_exists", True)


def _mailbox(**kw):
    kw.setdefault("local_part", "i.ivanov")
    kw.setdefault("domain", "htq.group")
    kw.setdefault("address", f"{kw['local_part']}@{kw['domain']}")
    return ProvisionedMailbox.objects.create(**kw)


# ── lookup: что именно нашли ─────────────────────────────────────────────

@pytest.mark.django_db
def test_lookup_reports_a_free_address(use_provisioner):
    use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        found = lookup_service.lookup("i.ivanov@htq.group")

    assert found.exists is False
    assert found.source == "none"
    assert found.can_attach is False
    assert found.checked_remote is True


@pytest.mark.django_db
def test_lookup_finds_a_local_orphan_and_offers_to_attach_it(use_provisioner):
    _mailbox()
    use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        found = lookup_service.lookup("i.ivanov@htq.group", for_user_id=42)

    assert (found.exists, found.source) == (True, "local")
    assert found.can_attach is True
    assert found.owner_user_id is None
    assert found.mailbox["address"] == "i.ivanov@htq.group"


@pytest.mark.django_db
def test_lookup_refuses_to_attach_someone_elses_mailbox(use_provisioner):
    _mailbox(user_id=7)
    use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        found = lookup_service.lookup("i.ivanov@htq.group", for_user_id=8)

    assert found.owner_conflict is True
    assert found.can_attach is False
    assert "#7" in found.detail


@pytest.mark.django_db
def test_lookup_sees_a_mailbox_that_exists_only_on_the_server(use_provisioner):
    """Ровно тот случай, ради которого сверка написана: строки у платформы
    нет, а ящик на сервере есть."""
    use_provisioner(_FakeMailcow(remote={"i.ivanov@htq.group"}))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        found = lookup_service.lookup("i.ivanov@htq.group", for_user_id=42)

    assert (found.exists, found.source) == (True, "remote")
    assert found.can_attach is True
    assert found.mailbox is None


@pytest.mark.django_db
def test_unreachable_server_is_not_reported_as_a_free_address(use_provisioner):
    """«Не знаю» ≠ «ящика нет». Иначе таймаут Mailcow разрешал бы создание
    поверх живого ящика."""
    use_provisioner(_FakeMailcow(unreachable="Mailcow get_mailbox: timeout"))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        found = lookup_service.lookup("i.ivanov@htq.group")

    assert found.checked_remote is False
    assert found.remote_detail == "Mailcow get_mailbox: timeout"
    assert "не проверялся" in found.detail


@pytest.mark.django_db
def test_lookup_matches_the_address_regardless_of_letter_case(use_provisioner):
    """Почтовый сервер вправе писать адрес с заглавных — для почты это тот же
    ящик, и сверка обязана его узнать."""
    _mailbox(address="I.Ivanov@htq.group")
    use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        found = lookup_service.lookup("i.ivanov@htq.group")

    assert found.exists is True
    assert found.mailbox["address"] == "I.Ivanov@htq.group"


@pytest.mark.django_db
def test_lookup_candidate_builds_the_same_address_creation_would(use_provisioner):
    use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        found = lookup_service.lookup_candidate(first_name="Иван", last_name="Иванов")

    assert found.address == "i.ivanov@htq.group"


# ── provision: mailcow ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_provision_attaches_the_mailbox_that_already_exists_on_the_server(use_provisioner):
    """Ящик на сервере есть — подключаем его целиком: строка, владелец,
    ``EmailAccount`` и пароль. Нового ящика на сервере НЕ создаём."""
    provisioner = use_provisioner(_FakeMailcow(remote={"i.ivanov@htq.group"}))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        result = mbx_svc.provision(_Payload(local_part="i.ivanov", user_id=42))

    assert result.attached is True
    assert result.mailbox.address == "i.ivanov@htq.group"
    assert result.mailbox.user_id == 42
    assert [c[0] for c in provisioner.calls] == ["issue_app_password"]
    assert ProvisionedMailbox.objects.count() == 1
    assert EmailAccount.objects.filter(user_id=42, address="i.ivanov@htq.group").exists()
    # Пароль сохранён зашифрованным — без него ни синхронизации, ни отправки.
    stored = ProvisionedMailbox.objects.get(address="i.ivanov@htq.group")
    assert crypto_service.decrypt(stored.encrypted_smtp_app_password)


@pytest.mark.django_db
def test_provision_attaches_a_local_row_that_had_no_owner(use_provisioner):
    mb = _mailbox()
    use_provisioner(_FakeMailcow(remote={"i.ivanov@htq.group"}))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        result = mbx_svc.provision(_Payload(local_part="i.ivanov", user_id=42))

    mb.refresh_from_db()
    assert result.attached is True
    assert mb.user_id == 42
    assert ProvisionedMailbox.objects.count() == 1


@pytest.mark.django_db
def test_provision_still_renames_when_the_address_belongs_to_someone_else(use_provisioner):
    """Два однофамильца не должны получить один ящик на двоих — старое
    поведение с ``i.ivanov2`` здесь обязано сохраниться."""
    _mailbox(user_id=7)
    use_provisioner(_FakeMailcow(remote={"i.ivanov@htq.group"}))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        result = mbx_svc.provision(_Payload(local_part="i.ivanov", user_id=8))

    assert result.attached is False
    assert result.mailbox.address == "i.ivanov2@htq.group"


@pytest.mark.django_db
def test_provision_without_a_user_keeps_the_old_dedupe(use_provisioner):
    """Подключать некому — «подключение» неотличимо от бездействия, поэтому
    поведение прежнее."""
    _mailbox()
    use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        result = mbx_svc.provision(_Payload(local_part="i.ivanov"))

    assert result.attached is False
    assert result.mailbox.address == "i.ivanov2@htq.group"


@pytest.mark.django_db
def test_provision_imports_a_server_only_mailbox_even_without_a_user(use_provisioner):
    """Исключение из правила выше: альтернатива подключению здесь не
    ``i.ivanov2``, а отказ сервера на ``/add/mailbox``."""
    provisioner = use_provisioner(_FakeMailcow(remote={"i.ivanov@htq.group"}))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        result = mbx_svc.provision(_Payload(local_part="i.ivanov"))

    assert result.attached is True
    assert result.mailbox.address == "i.ivanov@htq.group"
    assert not any(c[0] == "create" for c in provisioner.calls)


@pytest.mark.django_db
def test_provision_creates_a_new_mailbox_when_nothing_was_found(use_provisioner):
    provisioner = use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        result = mbx_svc.provision(_Payload(local_part="i.ivanov", user_id=42))

    assert result.attached is False
    assert any(c[0] == "create" for c in provisioner.calls)
    assert isinstance(result.generated_password, str)


@pytest.mark.django_db
def test_attach_if_exists_false_forces_a_brand_new_address(use_provisioner):
    _mailbox()
    use_provisioner(_FakeMailcow(remote={"i.ivanov@htq.group"}))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        result = mbx_svc.provision(
            _Payload(local_part="i.ivanov", user_id=42, attach_if_exists=False),
        )

    assert result.attached is False
    assert result.mailbox.address == "i.ivanov2@htq.group"


# ── provision: сервер без админ-API ──────────────────────────────────────

@pytest.mark.django_db
def test_provision_attaches_and_waits_for_the_password_on_imap(use_provisioner):
    """Пароль взять неоткуда — но это не повод не привязывать ящик.

    Отказ оставил бы сотрудника в неведении: ящик у него есть, платформа его
    нашла, а он об этом никогда не узнает. Вместо отказа ящик привязывается и
    честно помечается «ждёт пароль» — его введёт сам сотрудник.
    """
    mb = _mailbox()
    use_provisioner(_FakeImap())
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap", IMAP_HOST="mail-tunnel",
    ):
        result = mbx_svc.provision(_Payload(local_part="i.ivanov", user_id=42))
        mb.refresh_from_db()
        # Внутри override_settings: awaits_password читает режим из настроек,
        # снаружи он уже "none" и признак честно сбрасывается.
        assert mbx_svc.awaits_password(mb) is True

    assert result.attached is True
    assert result.awaiting_password is True
    assert mb.user_id == 42
    assert not mb.encrypted_smtp_app_password


@pytest.mark.django_db
def test_provision_attaches_on_imap_once_the_login_succeeds(use_provisioner):
    mb = _mailbox()
    use_provisioner(_FakeImap(passwords={"i.ivanov@htq.group": "S3cret!"}))
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap", IMAP_HOST="mail-tunnel",
    ):
        result = mbx_svc.provision(
            _Payload(local_part="i.ivanov", user_id=42, password="S3cret!"),
        )

    mb.refresh_from_db()
    assert result.attached is True
    assert mb.user_id == 42
    assert crypto_service.decrypt(mb.encrypted_smtp_app_password) == "S3cret!"
    assert EmailAccount.objects.filter(user_id=42).exists()


@pytest.mark.django_db
def test_provision_leaves_no_link_when_the_password_is_wrong(use_provisioner):
    """Нерабочая привязка хуже её отсутствия: снаружи она выглядит рабочей."""
    mb = _mailbox()
    use_provisioner(_FakeImap(passwords={"i.ivanov@htq.group": "S3cret!"}))
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap", IMAP_HOST="mail-tunnel",
    ):
        with pytest.raises(mbx_svc.MailboxVerificationFailed):
            mbx_svc.provision(
                _Payload(local_part="i.ivanov", user_id=42, password="wrong"),
            )

    mb.refresh_from_db()
    assert mb.user_id is None
    assert not mb.encrypted_smtp_app_password
    assert EmailAccount.objects.count() == 0


# ── занятый слот user_id ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_attach_names_the_deleted_row_instead_of_crashing(use_provisioner):
    """``user_id`` уникален и для ``status='deleted'``. На пути создания это
    исторический 500 (см. test_mailboxes_api.py); на пути привязки такой же
    500 был бы просто багом."""
    _mailbox(user_id=42, address="old@htq.group", local_part="old",
             status=MailboxStatus.DELETED)
    use_provisioner(_FakeMailcow(remote={"i.ivanov@htq.group"}))

    with override_settings(MAILCOW_DOMAIN="htq.group"):
        with pytest.raises(mbx_svc.MailboxUserSlotTaken) as exc:
            mbx_svc.attach_existing(address="i.ivanov@htq.group", user_id=42)

    assert "old@htq.group" in exc.value.detail


# ── HTTP ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_lookup_endpoint_requires_admin(plain_auth):
    resp = Client().get(f"{BASE}/lookup/?address=i.ivanov@htq.group", **plain_auth)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_lookup_endpoint_returns_the_verdict(admin_auth, use_provisioner):
    _mailbox(user_id=7)
    use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = Client().get(
            f"{BASE}/lookup/?first_name=Иван&last_name=Иванов&user_id=8", **admin_auth,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["address"] == "i.ivanov@htq.group"
    assert body["exists"] is True
    assert body["owner_conflict"] is True
    assert body["owner_user_id"] == 7
    assert body["can_attach"] is False


@pytest.mark.django_db
def test_lookup_endpoint_rejects_a_non_numeric_user_id(admin_auth):
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = Client().get(f"{BASE}/lookup/?address=a@htq.group&user_id=abc", **admin_auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_create_endpoint_reports_that_it_attached_instead_of_creating(admin_auth, use_provisioner):
    use_provisioner(_FakeMailcow(remote={"i.ivanov@htq.group"}))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        resp = Client().post(
            f"{BASE}/", data={"local_part": "i.ivanov", "user_id": 42},
            content_type="application/json", **admin_auth,
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["attached"] is True
    assert body["address"] == "i.ivanov@htq.group"
    assert "подключён" in body["detail"]


@pytest.mark.django_db
def test_create_endpoint_reports_a_mailbox_waiting_for_its_password(admin_auth, use_provisioner):
    """Админа не блокируем: ящик подключён, а пароль спросят у сотрудника."""
    _mailbox()
    use_provisioner(_FakeImap())
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap", IMAP_HOST="mail-tunnel",
    ):
        resp = Client().post(
            f"{BASE}/", data={"local_part": "i.ivanov", "user_id": 42},
            content_type="application/json", **admin_auth,
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["attached"] is True
    assert body["awaiting_password"] is True
    assert "сотрудник введёт пароль" in body["detail"]


# ── адрес ящика = корпоративный email пользователя ───────────────────────

@pytest.mark.django_db
def test_corporate_email_wins_over_transliterated_name(use_provisioner):
    """Админ вписал ruslan.amirov@htq.group — он НАЗВАЛ адрес. Подставить
    вместо него r.amirov значит и завести ящик мимо логина сотрудника, и
    промахнуться сверкой: искали бы один адрес, существует другой."""
    use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        found = lookup_service.lookup_candidate(
            email="ruslan.amirov@htq.group", first_name="Руслан", last_name="Амиров",
        )

    assert found.address == "ruslan.amirov@htq.group"


@pytest.mark.django_db
def test_personal_email_does_not_become_a_corporate_address(use_provisioner):
    """Чужой домен корпоративным ящиком не становится — падаем обратно на ФИО."""
    use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        found = lookup_service.lookup_candidate(
            email="ruslan.amirov@gmail.com", first_name="Руслан", last_name="Амиров",
        )

    assert found.address == "r.amirov@htq.group"


@pytest.mark.django_db
def test_provision_creates_the_mailbox_named_after_the_email(use_provisioner):
    provisioner = use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        result = mbx_svc.provision(_Payload(
            email="ruslan.amirov@htq.group", first_name="Руслан",
            last_name="Амиров", user_id=42,
        ))

    assert result.mailbox.address == "ruslan.amirov@htq.group"
    assert any(c[0] == "create" for c in provisioner.calls)


# ── attach_mailbox_by_email: подключение без всякой галки ────────────────

@pytest.mark.django_db
def test_attach_by_email_connects_a_mailbox_that_exists_on_the_server(use_provisioner):
    """Ровно заявленный сценарий: сотрудника заводят с адресом
    ruslan.amirov@htq.group, такой ящик на сервере уже есть — он подключается
    сам, без отдельной команды."""
    from apps.mail import interface as mail_interface

    use_provisioner(_FakeMailcow(remote={"ruslan.amirov@htq.group"}))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        result = mail_interface.attach_mailbox_by_email(
            user_id=42, email="ruslan.amirov@htq.group",
        )

    assert result is not None
    assert result["attached"] is True
    assert result["address"] == "ruslan.amirov@htq.group"
    assert ProvisionedMailbox.objects.get(address="ruslan.amirov@htq.group").user_id == 42
    assert EmailAccount.objects.filter(user_id=42).exists()


@pytest.mark.django_db
def test_attach_by_email_creates_nothing_when_there_is_no_mailbox(use_provisioner):
    """Ящик не заказывали — значит и создавать нечего."""
    from apps.mail import interface as mail_interface

    provisioner = use_provisioner(_FakeMailcow())
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        result = mail_interface.attach_mailbox_by_email(
            user_id=42, email="ruslan.amirov@htq.group",
        )

    assert result is None
    assert ProvisionedMailbox.objects.count() == 0
    assert provisioner.calls == []


@pytest.mark.django_db
def test_attach_by_email_ignores_a_personal_address(use_provisioner):
    from apps.mail import interface as mail_interface

    use_provisioner(_FakeMailcow(remote={"ruslan@gmail.com"}))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        assert mail_interface.attach_mailbox_by_email(
            user_id=42, email="ruslan@gmail.com",
        ) is None
    assert ProvisionedMailbox.objects.count() == 0


@pytest.mark.django_db
def test_attach_by_email_never_steals_someone_elses_mailbox(use_provisioner):
    from apps.mail import interface as mail_interface

    mb = _mailbox(local_part="ruslan.amirov", user_id=7)
    use_provisioner(_FakeMailcow(remote={"ruslan.amirov@htq.group"}))
    with override_settings(MAILCOW_DOMAIN="htq.group"):
        assert mail_interface.attach_mailbox_by_email(
            user_id=8, email="ruslan.amirov@htq.group",
        ) is None

    mb.refresh_from_db()
    assert mb.user_id == 7


@pytest.mark.django_db
def test_attach_by_email_attaches_and_waits_for_the_password(use_provisioner):
    """Сервер без админ-API: ящик всё равно привязывается, но помечается
    «ждёт пароль» — его введёт сотрудник."""
    from apps.mail import interface as mail_interface

    mb = _mailbox(local_part="ruslan.amirov")
    use_provisioner(_FakeImap())
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap", IMAP_HOST="mail-tunnel",
    ):
        result = mail_interface.attach_mailbox_by_email(
            user_id=42, email="ruslan.amirov@htq.group",
        )

    mb.refresh_from_db()
    assert result is not None
    assert result["awaiting_password"] is True
    assert mb.user_id == 42
    assert not mb.encrypted_smtp_app_password


@pytest.mark.django_db
def test_mailcow_app_password_failure_falls_back_to_asking_the_employee(use_provisioner):
    """Главный сценарий «спрашивать, только если автоматом не вышло»: Mailcow
    ящик подтвердил, но app-password не дал — ящик подключён и ждёт человека."""
    from apps.mail import interface as mail_interface

    class _RefusesAppPassword(_FakeMailcow):
        def issue_app_password(self, **kw):
            raise ProvisioningError("app-passwd: permission denied")

    use_provisioner(_RefusesAppPassword(remote={"ruslan.amirov@htq.group"}))
    with override_settings(**MAILCOW_ENV):
        result = mail_interface.attach_mailbox_by_email(
            user_id=42, email="ruslan.amirov@htq.group",
        )

    assert result is not None
    assert result["awaiting_password"] is True
    mb = ProvisionedMailbox.objects.get(address="ruslan.amirov@htq.group")
    assert mb.user_id == 42
    assert not mb.encrypted_smtp_app_password


# ── сотрудник довводит пароль к своему «ждущему» ящику ───────────────────

@pytest.mark.django_db
def test_employee_may_supply_the_password_even_with_self_service_off(use_provisioner):
    """``allow_self_service`` запрещает подключать ящики ПО СВОЕЙ инициативе.

    Здесь инициатива не сотрудника: ящик ему уже назначила платформа, и без
    пароля он не работает. Запрет тут означал бы «ящик ваш, но пользоваться
    им нельзя» — сотрудник заперт вместе со своей почтой.
    """
    from apps.mail.services import self_service

    mb = _mailbox(local_part="ruslan.amirov", user_id=42)
    use_provisioner(_FakeImap(passwords={"ruslan.amirov@htq.group": "S3cret!"}))
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap", IMAP_HOST="mail-tunnel",
    ):
        assert mbx_svc.awaits_password(mb) is True
        result = self_service.connect_own_mailbox(
            user_id=42, address="ruslan.amirov@htq.group", password="S3cret!",
        )

    mb.refresh_from_db()
    assert result["address"] == "ruslan.amirov@htq.group"
    assert crypto_service.decrypt(mb.encrypted_smtp_app_password) == "S3cret!"
    assert EmailAccount.objects.filter(user_id=42).exists()


@pytest.mark.django_db
def test_self_service_stays_closed_for_a_mailbox_that_is_not_yours(use_provisioner):
    """Послабление касается ТОЛЬКО своего назначенного ящика — иначе оно
    превратилось бы в обход выключенного самообслуживания."""
    from apps.mail.services import self_service

    _mailbox(local_part="someone.else")
    use_provisioner(_FakeImap(passwords={"someone.else@htq.group": "S3cret!"}))
    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap", IMAP_HOST="mail-tunnel",
    ):
        with pytest.raises(self_service.SelfServiceDisabled):
            self_service.connect_own_mailbox(
                user_id=42, address="someone.else@htq.group", password="S3cret!",
            )


@pytest.mark.django_db
def test_connect_corporate_info_tells_the_employee_the_mailbox_awaits_them(
    use_provisioner, db,
):
    """Карточка в профиле должна открыться сама — даже при выключенном
    самообслуживании, иначе вводить пароль будет негде."""
    u = User.objects.create(
        username="amirov", email="ruslan.amirov@htq.group", password="x",
        status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!")
    u.save()
    _mailbox(local_part="ruslan.amirov", user_id=u.id)
    use_provisioner(_FakeImap())

    with override_settings(
        MAILCOW_DOMAIN="htq.group", MAIL_PROVISIONER="imap", IMAP_HOST="mail-tunnel",
    ):
        resp = Client().get(
            "/api/email/v1/accounts/connect-corporate/",
            HTTP_AUTHORIZATION=f"Bearer {issue_token_pair(u)['access']}",
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["awaiting_password"] is True
    assert body["allowed"] is True        # карточку показать обязаны
    assert body["self_service"] is False  # но общий режим так и выключен
    assert body["mailbox"]["address"] == "ruslan.amirov@htq.group"
