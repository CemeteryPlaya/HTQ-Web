"""Двусторонняя сверка «платформа ↔ почтовый сервер».

Зачем: списки ящиков расходятся неизбежно. Ящик заводят руками в админке
почтового сервера мимо платформы; ящик удаляют на сервере, а строка у нас
остаётся; квоту правят на сервере; создание из платформы падает на сетевой
ошибке и оставляет строку в ``error``. Раньше увидеть это было нечем — сверки
не существовало вообще.

Сверка идёт В ОБЕ СТОРОНЫ и различает четыре класса расхождений:

``only_local``    строка есть у нас, ящика на сервере нет
                  → либо создать ящик на сервере (push), либо пометить строку
                    ``error`` (сервер — источник правды)
``only_remote``   ящик есть на сервере, строки у нас нет
                  → импортировать (pull): завести ``ProvisionedMailbox``
``mismatched``    есть с обеих сторон, но отличаются квота/имя/активность
                  → выровнять в выбранную сторону
``unlinked``      ящик без владельца, а его адрес совпадает с email
                  пользователя платформы
                  → привязать к сотруднику и завести ему почтовый аккаунт
``in_sync``       совпадают — ничего делать не надо

Два режима получения «правой стороны»:

* **listing** — сервер отдаёт список ящиков домена одним запросом (Mailcow).
  Полноценная сверка, видно и ``only_remote``.
* **probe** — сервер списка не отдаёт (голый IMAP). Тогда сверка идёт
  поштучно: каждая локальная строка проверяется живым IMAP-логином под
  сохранённой учёткой. ``only_remote`` в этом режиме принципиально не
  вычисляется — о ящиках, про которые платформа не знает, узнать неоткуда;
  отчёт честно помечается ``mode="probe"``, чтобы это не выглядело как
  «на сервере лишнего нет».

По умолчанию сверка НИЧЕГО не меняет (``apply=False``) — сначала отчёт,
решение за админом.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from django.conf import settings
from django.utils import timezone

from apps.mail.models import ProvisionedMailbox
from apps.mail.services import mail_config
from apps.mail.services import mailbox_service as mbx_svc
# Поиск владельца идёт через интерфейс соседней аппки, а не по её моделям —
# правило изоляции (apps/core/tests/test_app_isolation.py).
from apps.users import interface as users_interface
from apps.mail.services.crypto import crypto_service
from apps.mail.services.provisioning import (
    ProvisioningError,
    RemoteListingUnsupported,
    RemoteMailbox,
    get_provisioner,
    resolve_provisioner_name,
)

log = logging.getLogger(__name__)

# Статусы, при которых строка считается «должна существовать на сервере».
LIVE_STATUSES = ("active", "error")


@dataclass
class Difference:
    kind: str                      # only_local | only_remote | mismatched | unlinked
    address: str
    mailbox_id: int | None = None
    user_id: int | None = None
    local: dict | None = None
    remote: dict | None = None
    fields: list[str] = field(default_factory=list)
    detail: str | None = None
    #: что сделала сверка, если её запустили с apply=True
    action: str | None = None
    error: str | None = None


@dataclass
class ReconcileReport:
    mode: str                      # listing | probe | unavailable
    provisioner: str
    domain: str
    applied: bool = False
    direction: str = "report"
    checked_local: int = 0
    checked_remote: int = 0
    in_sync: int = 0
    differences: list[Difference] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    finished_at: str = ""

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "provisioner": self.provisioner,
            "domain": self.domain,
            "applied": self.applied,
            "direction": self.direction,
            "checked_local": self.checked_local,
            "checked_remote": self.checked_remote,
            "in_sync": self.in_sync,
            "counts": {
                "only_local": sum(1 for d in self.differences if d.kind == "only_local"),
                "only_remote": sum(1 for d in self.differences if d.kind == "only_remote"),
                "mismatched": sum(1 for d in self.differences if d.kind == "mismatched"),
                "unlinked": sum(1 for d in self.differences if d.kind == "unlinked"),
                "linked": sum(1 for d in self.differences if d.action == "linked"),
            },
            "differences": [asdict(d) for d in self.differences],
            "errors": self.errors,
            "finished_at": self.finished_at or timezone.now().isoformat(),
        }


def _local_snapshot(mb: ProvisionedMailbox) -> dict:
    return {
        "id": mb.id,
        "address": mb.address,
        "status": mb.status,
        "quota_mb": mb.quota_mb,
        "display_name": mb.display_name,
        "user_id": mb.user_id,
    }


def _remote_snapshot(rm: RemoteMailbox) -> dict:
    return {
        "address": rm.address,
        "quota_mb": rm.quota_mb,
        "display_name": rm.display_name,
        "active": rm.active,
    }


def _compare(mb: ProvisionedMailbox, rm: RemoteMailbox) -> list[str]:
    """Какие поля разошлись. Квота с нулём на стороне сервера не считается
    расхождением: Mailcow отдаёт 0 для безлимитных ящиков."""
    diverged: list[str] = []
    if rm.quota_mb and rm.quota_mb != mb.quota_mb:
        diverged.append("quota_mb")
    if (rm.display_name or None) != (mb.display_name or None):
        diverged.append("display_name")
    if rm.active != (mb.status == "active"):
        diverged.append("active")
    return diverged


def _stored_password(mb: ProvisionedMailbox) -> str | None:
    if not mb.encrypted_smtp_app_password:
        return None
    try:
        return crypto_service.decrypt(mb.encrypted_smtp_app_password)
    except Exception as exc:  # noqa: BLE001 — битый шифротекст не должен ронять сверку
        log.warning("reconcile_password_decrypt_failed address=%s: %s", mb.address, exc)
        return None


# ── сверка ───────────────────────────────────────────────────────────────

def reconcile(*, apply: bool = False, direction: str = "report") -> ReconcileReport:
    """Сверить платформу с почтовым сервером.

    ``direction`` управляет тем, что делать с найденными расхождениями при
    ``apply=True``:

    * ``report`` — ничего не менять (значение по умолчанию);
    * ``pull``   — сервер источник правды: импортировать ``only_remote``,
                   подтянуть отличающиеся поля, а ``only_local`` пометить
                   ``error``;
    * ``push``   — платформа источник правды: создать недостающие ящики на
                   сервере и выровнять поля на сервере;
    * ``both``   — импортировать ``only_remote`` (pull) И досоздать
                   ``only_local`` на сервере (push). Расхождения полей при
                   этом выравниваются по серверу — трогать чужие настройки
                   молча опаснее, чем подтянуть их к себе.
    """
    provisioner = get_provisioner()
    report = ReconcileReport(
        mode="listing",
        provisioner=resolve_provisioner_name(),
        domain=mail_config.get_config().domain,
        applied=apply,
        direction=direction,
    )

    local_rows = list(ProvisionedMailbox.objects.exclude(status="deleted").order_by("address"))
    report.checked_local = len(local_rows)
    by_address = {mb.address.lower(): mb for mb in local_rows}

    try:
        remote_rows = provisioner.list_remote()
    except RemoteListingUnsupported as exc:
        report.mode = "probe"
        _reconcile_by_probe(provisioner, local_rows, report, apply=apply, direction=direction)
        # Владельцев ищем и здесь: для этого сервер списка ящиков не нужен —
        # сверяются адреса строк, которые у платформы уже есть.
        _link_orphans(report, apply=apply)
        report.errors.append(str(exc))
        report.finished_at = timezone.now().isoformat()
        return report
    except ProvisioningError as exc:
        report.mode = "unavailable"
        report.errors.append(str(exc))
        report.finished_at = timezone.now().isoformat()
        return report

    remote_by_address = {rm.address.lower(): rm for rm in remote_rows}
    report.checked_remote = len(remote_by_address)

    # ── сторона 1: локальные строки против сервера ──────────────────────
    for address, mb in by_address.items():
        rm = remote_by_address.get(address)
        if rm is None:
            if mb.status not in LIVE_STATUSES:
                # archived — ящика на сервере и не должно быть
                report.in_sync += 1
                continue
            diff = Difference(
                kind="only_local", address=mb.address, mailbox_id=mb.id,
                user_id=mb.user_id, local=_local_snapshot(mb),
                detail="Ящик есть в платформе, но отсутствует на почтовом сервере",
            )
            if apply:
                _apply_only_local(provisioner, mb, diff, direction=direction)
            report.differences.append(diff)
            continue

        diverged = _compare(mb, rm)
        if not diverged:
            report.in_sync += 1
            continue
        diff = Difference(
            kind="mismatched", address=mb.address, mailbox_id=mb.id, user_id=mb.user_id,
            local=_local_snapshot(mb), remote=_remote_snapshot(rm), fields=diverged,
            detail="Значения отличаются: " + ", ".join(diverged),
        )
        if apply:
            _apply_mismatch(provisioner, mb, rm, diff, direction=direction)
        report.differences.append(diff)

    # ── сторона 2: ящики сервера, которых нет в платформе ───────────────
    for address, rm in remote_by_address.items():
        if address in by_address:
            continue
        diff = Difference(
            kind="only_remote", address=rm.address, remote=_remote_snapshot(rm),
            detail="Ящик есть на почтовом сервере, но не заведён в платформе",
        )
        if apply:
            _apply_only_remote(rm, diff, direction=direction)
        report.differences.append(diff)

    # ── сторона 3: у кого из бесхозных ящиков есть владелец ─────────────
    # После импорта намеренно: свежепритянутые с сервера ящики проходят тот
    # же поиск владельца, что и висящие с прошлых прогонов.
    _link_orphans(report, apply=apply)

    report.finished_at = timezone.now().isoformat()
    log.info(
        "mail_reconcile mode=%s local=%d remote=%d in_sync=%d diffs=%d applied=%s",
        report.mode, report.checked_local, report.checked_remote,
        report.in_sync, len(report.differences), apply,
    )
    return report


def _reconcile_by_probe(
    provisioner, local_rows: list[ProvisionedMailbox], report: ReconcileReport,
    *, apply: bool, direction: str,
) -> None:
    """Режим для серверов без списка ящиков: проверяем каждую свою строку
    живым логином. Видно только ``only_local`` — про чужие ящики узнать
    неоткуда, и отчёт об этом честно сообщает через ``mode="probe"``."""
    for mb in local_rows:
        if mb.status not in LIVE_STATUSES:
            report.in_sync += 1
            continue
        password = _stored_password(mb)
        if not password:
            diff = Difference(
                kind="only_local", address=mb.address, mailbox_id=mb.id, user_id=mb.user_id,
                local=_local_snapshot(mb),
                detail="Нет сохранённого пароля — проверить ящик на сервере нечем",
            )
            report.differences.append(diff)
            continue

        ok, error = provisioner.verify(address=mb.address, password=password)
        report.checked_remote += 1
        if ok:
            report.in_sync += 1
            if mb.status == "error" and apply and direction in ("pull", "both"):
                mb.status = "active"
                mb.last_error = None
                mb.save(update_fields=["status", "last_error", "updated_at"])
            continue

        diff = Difference(
            kind="only_local", address=mb.address, mailbox_id=mb.id, user_id=mb.user_id,
            local=_local_snapshot(mb), detail=f"Сервер не принял учётку: {error}",
        )
        if apply and direction in ("pull", "both"):
            mbx_svc.mark_error(mb, f"Сверка: {error}", status="error")
            diff.action = "marked_error"
        report.differences.append(diff)


# ── применение решений ───────────────────────────────────────────────────

def _apply_only_local(provisioner, mb: ProvisionedMailbox, diff: Difference, *, direction: str) -> None:
    """Строка есть у нас, ящика на сервере нет."""
    if direction in ("push", "both"):
        password = _stored_password(mb) or mbx_svc.generate_password()
        try:
            provisioner.create(
                local_part=mb.local_part, domain=mb.domain, address=mb.address,
                password=password, full_name=mb.display_name or "", quota_mb=mb.quota_mb,
            )
        except ProvisioningError as exc:
            diff.action, diff.error = "create_failed", str(exc)
            mbx_svc.mark_error(mb, f"Сверка: {exc}", status="error")
            return
        mbx_svc.store_password(mb, password)
        if mb.status == "error":
            mb.status = "active"
            mb.last_error = None
            mb.save(update_fields=["status", "last_error", "updated_at"])
        diff.action = "created_on_server"
    elif direction == "pull":
        mbx_svc.mark_error(mb, "Сверка: ящик отсутствует на почтовом сервере", status="error")
        diff.action = "marked_error"


def _apply_only_remote(rm: RemoteMailbox, diff: Difference, *, direction: str) -> None:
    """Ящик есть на сервере, строки у нас нет — импортируем.

    ``user_id`` здесь не проставляется: владельца ищет отдельный шаг
    ``_link_orphans`` уже после импорта, по точному совпадению адреса с
    email пользователя. Так один и тот же код привязывает и свежий импорт, и
    строки, которые висят без владельца с прошлых прогонов.
    """
    if direction not in ("pull", "both"):
        return
    try:
        mb = ProvisionedMailbox.objects.create(
            user_id=None,
            local_part=rm.local_part or rm.address.partition("@")[0],
            domain=rm.domain or rm.address.partition("@")[2],
            address=rm.address,
            status="active" if rm.active else "archived",
            quota_mb=rm.quota_mb or mail_config.get_config().mailcow_default_quota_mb,
            display_name=rm.display_name,
            archived_at=None if rm.active else timezone.now(),
        )
    except Exception as exc:  # noqa: BLE001 — гонка/дубль не должны ронять всю сверку
        diff.action, diff.error = "import_failed", str(exc)
        return
    diff.action, diff.mailbox_id = "imported", mb.id


def _link_orphans(report: ReconcileReport, *, apply: bool) -> None:
    """Найти владельцев для ящиков, которые висят ничьими.

    Признак ровно один: **адрес ящика совпадает с email пользователя**. Это
    не догадка по имени и не эвристика — человек сам ввёл этот адрес как
    свой, и другого владельца у ``sanzhar.inamzhanov@htq.group`` быть не
    может. Ящики, под которые пользователя нет (общие ``info@``, ``sales@``),
    так и остаются без владельца: гадать по ним нечем и не нужно.

    Привязка — это две вещи, а не одна: проставить ``user_id`` и завести
    ``EmailAccount``. Без второго ящик остаётся «мёртвой» строкой в админке —
    список писем, синхронизация и отправка ходят именно через аккаунт.

    Без ``apply`` ничего не меняется: найденные пары попадают в отчёт как
    ``kind="unlinked"``, и админ видит, кому что достанется, до того как
    нажмёт «Принять данные сервера».
    """
    orphans = list(ProvisionedMailbox.objects
                   .filter(user_id__isnull=True)
                   .exclude(status="deleted")
                   .order_by("address"))
    if not orphans:
        return

    owners = users_interface.find_user_ids_by_emails([mb.address for mb in orphans])
    if not owners:
        return

    # user_id в ProvisionedMailbox — UNIQUE: у сотрудника не может быть двух
    # ящиков. Занятые владельцы отбираются заранее, чтобы каждая коллизия
    # стала строкой отчёта, а не исключением из середины прогона.
    taken = set(ProvisionedMailbox.objects
                .filter(user_id__in=set(owners.values()))
                .exclude(status="deleted")
                .values_list("user_id", flat=True))

    for mb in orphans:
        user_id = owners.get(mb.address.lower())
        if user_id is None:
            continue

        diff = Difference(
            kind="unlinked", address=mb.address, mailbox_id=mb.id, user_id=user_id,
            local=_local_snapshot(mb),
            detail=f"Ящик без владельца, а адрес совпадает с email пользователя #{user_id}",
        )

        if user_id in taken:
            diff.detail = (
                f"Адрес совпадает с email пользователя #{user_id}, но у него уже "
                f"есть другой ящик — привязка требует решения человека"
            )
            diff.action, diff.error = "skipped", "user_already_has_mailbox"
            report.differences.append(diff)
            continue

        if apply:
            try:
                mb.user_id = user_id
                mb.save(update_fields=["user_id", "updated_at"])
                mbx_svc.ensure_account(mb)
            except Exception as exc:  # noqa: BLE001 — одна привязка не роняет прогон
                diff.action, diff.error = "link_failed", str(exc)
                report.differences.append(diff)
                continue
            taken.add(user_id)
            diff.action = "linked"

        report.differences.append(diff)


def _apply_mismatch(
    provisioner, mb: ProvisionedMailbox, rm: RemoteMailbox, diff: Difference, *, direction: str,
) -> None:
    """Выровнять разошедшиеся поля.

    ``push`` толкает локальные значения на сервер; ``pull``/``both``
    подтягивают серверные к себе — молча перезаписывать настройки почтового
    сервера рискованнее, чем принять их как есть.
    """
    if direction == "push":
        try:
            provisioner.update(
                address=mb.address, full_name=mb.display_name, quota_mb=mb.quota_mb,
            )
            if "active" in diff.fields:
                provisioner.set_active(address=mb.address, active=mb.status == "active")
        except ProvisioningError as exc:
            diff.action, diff.error = "push_failed", str(exc)
            return
        diff.action = "pushed_to_server"
        return

    if direction not in ("pull", "both"):
        return

    update_fields: list[str] = []
    if "quota_mb" in diff.fields and rm.quota_mb:
        mb.quota_mb = rm.quota_mb
        update_fields.append("quota_mb")
    if "display_name" in diff.fields:
        mb.display_name = rm.display_name
        update_fields.append("display_name")
    if "active" in diff.fields:
        if rm.active and mb.status != "active":
            mb.status, mb.archived_at = "active", None
            update_fields += ["status", "archived_at"]
        elif not rm.active and mb.status == "active":
            mb.status, mb.archived_at = "archived", timezone.now()
            update_fields += ["status", "archived_at"]
    if update_fields:
        mb.save(update_fields=[*update_fields, "updated_at"])
    diff.action = "pulled_from_server"
