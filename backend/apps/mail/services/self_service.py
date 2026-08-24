"""Самоподключение корпоративного ящика сотрудником.

Сценарий: ящик на почтовом сервере уже заведён почтовым администратором, и
сотрудник знает от него пароль. Вместо того чтобы идти к админу платформы,
он подключает ящик сам — платформа проверяет пару живым IMAP-логином и, если
вход прошёл, привязывает ящик к его учётной записи.

Функция намеренно узкая, потому что это единственная точка домена mail, где
непривилегированный пользователь заводит строки. Ограничения:

* режим должен быть включён админом (``allow_self_service``) — по умолчанию
  выключен. ЕДИНСТВЕННОЕ исключение: ящик уже назначен этому сотруднику
  платформой и помечен «ждёт пароль» (``mailbox_service.awaits_password``) —
  тогда ввод пароля разрешён всегда, иначе получилось бы «ящик ваш, но
  пользоваться им нельзя»;
* домен адреса обязан совпадать с корпоративным: подключить ``@gmail.com``
  под видом корпоративного ящика нельзя (для личной почты есть OAuth);
* если ящик уже привязан к ДРУГОМУ пользователю — отказ. Иначе знание пароля
  (например, от общего ящика) позволило бы увести чужую привязку;
* повторное подключение своего же ящика — не ошибка, а обновление пароля:
  сотрудник сменил его на сервере и синхронизирует здесь;
* пароль проверяется ДО записи в БД, поэтому нерабочая привязка не создаётся.
"""
from __future__ import annotations

import logging

from apps.mail.models import ProvisionedMailbox
from apps.mail.services import mailbox_service as mbx_svc
from apps.mail.services.mail_config import get_config
from apps.mail.services.provisioning import ProvisioningError, get_provisioner

log = logging.getLogger(__name__)


class SelfServiceDisabled(Exception):
    """403 — админ не разрешал сотрудникам подключать ящики самим."""


class WrongDomain(Exception):
    """400 — адрес не из корпоративного домена."""

    def __init__(self, domain: str) -> None:
        self.detail = f"Адрес должен быть в домене @{domain}"
        super().__init__(self.detail)


class MailboxTakenByAnotherUser(Exception):
    """409 — ящик уже привязан к другому сотруднику."""

    def __init__(self) -> None:
        self.detail = "Этот ящик уже подключён другим пользователем"
        super().__init__(self.detail)


class VerificationFailed(Exception):
    """400 — почтовый сервер не принял адрес/пароль."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def connect_own_mailbox(*, user_id: int, address: str, password: str) -> dict:
    """Проверить учётку и привязать ящик к ``user_id``.

    Возвращает сериализованный ящик. Пароль сохраняется зашифрованным — им
    затем пользуются синхронизация писем и отправка.
    """
    cfg = get_config()

    address = (address or "").strip().lower()
    domain = (address.rsplit("@", 1)[-1] if "@" in address else "")
    if not cfg.domain or domain != cfg.domain.lower():
        raise WrongDomain(cfg.domain or "?")

    existing = ProvisionedMailbox.objects.filter(address__iexact=address).first()
    if existing is not None and existing.user_id not in (None, user_id):
        raise MailboxTakenByAnotherUser

    # ``allow_self_service`` защищает от ОДНОГО: сотрудник подключает ЧУЖОЙ
    # ящик. Два случая этим риском не обладают и потому разрешены всегда:
    #
    #  * ящик уже назначен ему платформой и без пароля не работает — запрет
    #    означал бы «ящик ваш, но пользоваться им нельзя»;
    #  * адрес совпадает с его собственным email на платформе — этот адрес за
    #    ним закрепил админ, выдать себя за другого тут нечем.
    #
    # Пароль в обоих случаях всё равно обязателен и проверяется живым входом
    # ниже: он и есть доказательство владения. Знание адреса доказательством
    # не является — адреса сотрудников известны всем, кто получал от них
    # письма, и подключение «по адресу» было бы подделкой на ровном месте.
    finishing_pending = (
        existing is not None
        and existing.user_id == user_id
        and mbx_svc.awaits_password(existing)
    )
    if not cfg.allow_self_service and not finishing_pending and not _is_own_address(
        user_id, address,
    ):
        raise SelfServiceDisabled

    # Проверяем ДО записи: нерабочая привязка хуже её отсутствия — она молча
    # ломает и синхронизацию, и отправку.
    ok, error = get_provisioner().verify(address=address, password=password)
    if not ok:
        raise VerificationFailed(
            f"Почтовый сервер не принял эту пару адрес/пароль: {error}"
        )

    # verify=False — проверка уже сделана строкой выше, и повторять её значило
    # бы ходить на почтовый сервер дважды за один запрос.
    mailbox = mbx_svc.attach_existing(
        address=address, user_id=user_id, password=password, verify=False,
    )

    # Забрать письма сразу: без этого сотрудник видит пустой ящик до минуты
    # (периодический опрос) и решает, что подключение не сработало.
    mbx_svc.kick_sync(mailbox)

    log.info("mailbox_self_connected user_id=%s address=%s", user_id, address)
    return mbx_svc.serialize(mailbox)


def _is_own_address(user_id: int, address: str) -> bool:
    """Совпадает ли адрес с email этого сотрудника на платформе.

    Через ``apps.users.interface`` — прямой импорт чужих моделей запрещён
    (``apps/core/tests/test_app_isolation.py``). Тот же приём, что и у сверки
    ящиков (``reconcile_service._link_orphans``).
    """
    from apps.users import interface as users_interface

    try:
        brief = users_interface.get_user_brief(user_id)
    except Exception as exc:  # noqa: BLE001 — недоступный сосед не должен
        # превращаться в «разрешено»: молчаливое падение в открытую дверь
        # хуже отказа, который человек увидит и позовёт админа.
        log.warning("own_address_check_failed user_id=%s: %s", user_id, exc)
        return False
    own = ((brief or {}).get("email") or "").strip().lower()
    return bool(own) and own == address


def disconnect_own_mailbox(*, user_id: int) -> bool:
    """Отвязать свой корпоративный ящик от платформы.

    Ящик на почтовом сервере НЕ трогается — сотрудник не должен иметь
    возможности удалить корпоративный ящик, он лишь убирает его из платформы.
    Строка архивируется (а не удаляется), чтобы у админа остался след.
    """
    mb = ProvisionedMailbox.objects.filter(user_id=user_id).exclude(status="deleted").first()
    if mb is None:
        return False

    from apps.mail.models import AccountType, EmailAccount

    EmailAccount.objects.filter(
        user_id=user_id, type=AccountType.CORPORATE, mailbox_id=mb.id,
    ).update(is_active=False)

    if mb.status == "active":
        try:
            mbx_svc.archive(mb.id)
        except ProvisioningError:  # noqa: PERF203 — отказ сервера не мешает отвязке
            pass
        except mbx_svc.CannotArchive:
            pass
    log.info("mailbox_self_disconnected user_id=%s address=%s", user_id, mb.address)
    return True
