"""Участники тендера: контакты контрагентов, потенциальные поставщики,
приглашения со ссылкой и привязка устройства (T2.2; план этапов 0–2, §4.1;
мастер-план T-21).

Контрагент — карточка БЗО (``counterparty_id`` голым UUID, читается через
``bpp.interface``). Ссылка поставщика: в БД хранится ТОЛЬКО SHA-256 токена
(``token_hash``), сырой токен выдаётся один раз — в ответе публикации,
перевыпуска или приглашения после публикации. Секрет устройства — тоже
только хэшем (привязку выдаёт портал, этап 3).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from .core import TenderModel, VersionedModel
from .tender import Tender

__all__ = ["DeviceBinding", "Invitation", "InvitationStatus", "SupplierContact",
           "SupplierProspect"]


class SupplierContact(TenderModel):
    """Контакт контрагента для приглашений — у tender свой справочник: в
    карточке БЗО один email, а продажами занимаются разные люди."""

    counterparty_id = models.UUIDField()
    email = models.CharField(max_length=254)
    name = models.CharField(max_length=255, default="", blank=True)
    phone = models.CharField(max_length=64, default="", blank=True)
    is_primary = models.BooleanField(default=False, db_default=False)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["counterparty_id", "email"],
                                    name="uq_tender_contact_email"),
        ]
        ordering = ("-is_primary", "name")
        verbose_name = "Контакт контрагента"
        verbose_name_plural = "Контакты контрагентов"


class SupplierProspect(VersionedModel):
    """Потенциальный поставщик — ещё не контрагент БЗО. Карточку контрагента
    из него заводит выбор победителя (этап 5) — тогда ``counterparty_id``."""

    name = models.CharField(max_length=500)
    email = models.CharField(max_length=254)
    reg_number = models.CharField(max_length=30, default="", blank=True)
    country_code = models.CharField(max_length=2, default="KZ")
    source = models.CharField(max_length=16, default="manual")
    counterparty_id = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Потенциальный поставщик"
        verbose_name_plural = "Потенциальные поставщики"

    def __str__(self) -> str:
        return self.name


class InvitationStatus(models.TextChoices):
    CREATED = "created", "Создано"
    SENT = "sent", "Отправлено"
    DELIVERY_ERROR = "delivery_error", "Ошибка доставки"
    OPENED = "opened", "Открыто"
    SUBMITTED = "submitted", "Предложение подано"
    DECLINED = "declined", "Отказ от участия"
    AWARDED = "awarded", "Победитель"
    NOT_AWARDED = "not_awarded", "Не выбран"
    REVOKED = "revoked", "Отозвано"
    EXPIRED = "expired", "Срок истёк"


class Invitation(TenderModel):
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name="invitations")
    # Ровно одно из двух: контрагент БЗО или потенциальный поставщик.
    counterparty_id = models.UUIDField(null=True, blank=True)
    prospect = models.ForeignKey(SupplierProspect, on_delete=models.PROTECT, null=True,
                                 blank=True, related_name="invitations")
    email = models.CharField(max_length=254)
    name = models.CharField(max_length=500)
    # SHA-256 hex токена ссылки; пусто — ссылка ещё не выпущена (черновик).
    token_hash = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=16, choices=InvitationStatus.choices,
                              default=InvitationStatus.CREATED)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivery_error = models.TextField(default="", blank=True)
    first_opened_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    max_devices = models.PositiveSmallIntegerField(default=1, db_default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["token_hash"], name="uq_tender_invitation_token"),
            models.CheckConstraint(
                condition=(Q(counterparty_id__isnull=False, prospect__isnull=True)
                           | Q(counterparty_id__isnull=True, prospect__isnull=False)),
                name="ck_tender_invitation_party"),
            models.CheckConstraint(condition=Q(max_devices__gte=1) & Q(max_devices__lte=2),
                                   name="ck_tender_invitation_devices"),
            # Среди не отозванных: адрес, контрагент и потенциальный поставщик
            # приглашаются в тендер по одному разу.
            models.UniqueConstraint(fields=["tender", "email"],
                                    name="uq_tender_invitation_email",
                                    condition=Q(revoked_at__isnull=True)),
            models.UniqueConstraint(fields=["tender", "counterparty_id"],
                                    name="uq_tender_invitation_counterparty",
                                    condition=Q(revoked_at__isnull=True,
                                                counterparty_id__isnull=False)),
            models.UniqueConstraint(fields=["tender", "prospect"],
                                    name="uq_tender_invitation_prospect",
                                    condition=Q(revoked_at__isnull=True,
                                                prospect__isnull=False)),
        ]
        ordering = ("created_at",)
        verbose_name = "Приглашение"
        verbose_name_plural = "Приглашения"


class DeviceBinding(TenderModel):
    """Устройство, привязанное к приглашению (cookie портала, T-21). Выдаёт
    портал (``services/portal/binding.py``), сбрасывает закупщик
    (``revoked_at``). Одна cookie обслуживает несколько приглашений — по
    строке на приглашение с тем же хэшем секрета (план этапа 3, §1)."""

    invitation = models.ForeignKey(Invitation, on_delete=models.CASCADE,
                                   related_name="devices")
    secret_hash = models.CharField(max_length=64)
    user_agent = models.TextField(default="", blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    bound_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # Среди действующих: устройство привязано к приглашению один раз;
            # после сброса то же устройство может привязаться снова.
            models.UniqueConstraint(fields=["invitation", "secret_hash"],
                                    name="uq_tender_device_secret",
                                    condition=Q(revoked_at__isnull=True)),
        ]
        verbose_name = "Привязка устройства"
        verbose_name_plural = "Привязки устройств"
