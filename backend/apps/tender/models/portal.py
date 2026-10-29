"""Журнал портала поставщика (T3.2; план этапа 3, §1 «Журнал портала»).

Каждое действие поставщика по ссылке — строка ``PortalEvent``: что сделано,
с какого IP (только ``X-Real-IP`` шлюза, T-23) и браузера. Журнал только для
записи: правку и удаление запрещает триггер БД (миграция
``0005_portal_events``), как у ``AuditLog``. ``meta`` — без токенов и
секретов: их сюда не пишет ``services/portal/access.record_event``.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now

from .supplier import Invitation

__all__ = ["PortalEvent", "PortalEventKind"]


class PortalEventKind(models.TextChoices):
    BOUND = "bound", "Устройство привязано"
    BIND_REFUSED = "bind_refused", "Привязка отклонена"
    OFFER_SAVED = "offer_saved", "Черновик предложения сохранён"
    OFFER_SUBMITTED = "offer_submitted", "Предложение отправлено"
    OFFER_WITHDRAWN = "offer_withdrawn", "Предложение отозвано"
    DECLINED = "declined", "Отказ от участия"
    FILE_UPLOADED = "file_uploaded", "Файл загружен"
    FILE_REMOVED = "file_removed", "Файл удалён"
    DEVICE_RESET = "device_reset", "Привязка устройства сброшена"


class PortalEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # PROTECT: журнал переживает всё, что с приглашением происходит; удалить
    # приглашение с событиями нельзя — как и сами события.
    invitation = models.ForeignKey(Invitation, on_delete=models.PROTECT,
                                   related_name="portal_events")
    kind = models.CharField(max_length=24, choices=PortalEventKind.choices)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, default="", blank=True)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        indexes = [models.Index(fields=["invitation", "created_at"],
                                name="ix_tender_portal_event")]
        ordering = ("created_at",)
        verbose_name = "Событие портала"
        verbose_name_plural = "Журнал портала"
