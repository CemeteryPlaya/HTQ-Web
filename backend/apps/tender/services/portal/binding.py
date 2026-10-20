"""Привязка устройства к приглашению (T3.2; план этапа 3, §2 T3.2; T-21).

``bind`` — под ``select_for_update`` приглашения: параллельные привязки
сериализуются, и при ``max_devices = 1`` выигрывает ровно одна. Устройство,
чья cookie уже привязана, получает ту же привязку. Иначе, пока есть место, —
новая привязка; секрет — из cookie этого устройства, если она уже есть (одна
cookie обслуживает несколько приглашений), или новый ``token_urlsafe(32)``.
Места нет — отказ ``E-TND-06`` и событие ``bind_refused`` (пишется ПОСЛЕ
отката транзакции привязки, иначе откатилось бы и оно).

Первая привязка открывает приглашение: ``first_opened_at``, статус
«Отправлено» / «Ошибка доставки» → «Открыто». Тендер не на приёме —
привязка всё равно возможна (поставщик смотрит итог, TND-035), правка — нет.
"""

from __future__ import annotations

import secrets

from django.db import transaction
from django.utils import timezone

from apps.tender.models import DeviceBinding, Invitation, InvitationStatus, PortalEventKind
from htqweb.errors import DomainError

from . import access

_OPENS = (InvitationStatus.SENT, InvitationStatus.DELIVERY_ERROR)


def _refused() -> DomainError:
    return DomainError(
        "E-TND-06", "Ссылка уже открыта на другом устройстве. Попросите закупщика сбросить "
                    "привязку устройства.", status=409, details={"rebind": "otp"})


def bind(invitation: Invitation, request) -> tuple[DeviceBinding, str | None]:
    """``(привязка, секрет для cookie | None)``. ``None`` — устройство уже
    привязано, cookie менять незачем."""
    ip, agent = access.client_ip(request), access.user_agent(request)
    current = access.device_secret(request)
    with transaction.atomic():
        inv = Invitation.objects.select_for_update().get(pk=invitation.pk)
        existing = access.active_binding(inv, current)
        if existing is not None:
            return existing, None
        active = DeviceBinding.objects.filter(invitation=inv, revoked_at__isnull=True).count()
        if active < inv.max_devices:
            secret = current or secrets.token_urlsafe(32)
            binding = DeviceBinding.objects.create(
                invitation=inv, secret_hash=access.digest(secret), user_agent=agent, ip=ip)
            now = timezone.now()
            if inv.first_opened_at is None:
                inv.first_opened_at = now
            if inv.status in _OPENS:
                inv.status = InvitationStatus.OPENED
            inv.save(update_fields=["first_opened_at", "status", "updated_at"])
            access.log_event(inv, PortalEventKind.BOUND, ip=ip, user_agent=agent,
                             meta={"binding": str(binding.pk), "reused_cookie": bool(current)})
            return binding, secret
    access.log_event(invitation, PortalEventKind.BIND_REFUSED, ip=ip, user_agent=agent,
                     meta={"active_devices": active, "max_devices": inv.max_devices})
    raise _refused()
