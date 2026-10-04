"""Хранимый центр уведомлений платформы (Q-C19, D-24), схема public.

``Notification`` — запись в колокольчике. ``Delivery`` — попытка доставки
по каналу (e-mail, Telegram): outbox, который Celery разбирает с повтором.
Колокольчик — сама запись; мгновенный показ — Socket.IO мессенджера,
best-effort. ``company_slug`` — в какой компании событие: лента на
поддомене показывает уведомления своей компании и общие (пусто).
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient_id = models.IntegerField(db_index=True)
    company_slug = models.CharField(max_length=64, default="", blank=True, db_default="")
    event = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    text = models.TextField(default="", blank=True, db_default="")
    url = models.CharField(max_length=512, default="", blank=True, db_default="")
    target_type = models.CharField(max_length=32, default="", blank=True, db_default="")
    target_id = models.CharField(max_length=64, default="", blank=True, db_default="")
    actor_id = models.IntegerField(null=True, blank=True)
    actor_avatar_url = models.CharField(max_length=1024, null=True, blank=True)
    is_read = models.BooleanField(default=False, db_default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        indexes = [models.Index(fields=["recipient_id", "company_slug", "is_read", "-created_at"],
                                name="ix_notif_feed")]
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"


class Channel(models.TextChoices):
    EMAIL = "email", "E-mail"
    TELEGRAM = "telegram", "Telegram"


class DeliveryState(models.TextChoices):
    PENDING = "pending", "Ожидает"
    SENT = "sent", "Отправлено"
    FAILED = "failed", "Не доставлено"
    SKIPPED = "skipped", "Пропущено"


class Delivery(models.Model):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE,
                                     related_name="deliveries")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    state = models.CharField(max_length=16, choices=DeliveryState.choices,
                             default=DeliveryState.PENDING,
                             db_default=DeliveryState.PENDING.value)
    attempts = models.PositiveSmallIntegerField(default=0, db_default=0)
    last_error = models.TextField(default="", blank=True, db_default="")
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["notification", "channel"],
                                               name="uq_notif_delivery_channel")]


class ChannelPrefs(models.Model):
    """Каналы пользователя. Нет строки — колокольчик и e-mail (ТЗ §22)."""

    user_id = models.IntegerField(unique=True)
    bell = models.BooleanField(default=True, db_default=True)
    email = models.BooleanField(default=True, db_default=True)
    telegram = models.BooleanField(default=False, db_default=False)


class TelegramLink(models.Model):
    user_id = models.IntegerField(unique=True)
    chat_id = models.CharField(max_length=64, default="", blank=True, db_default="")
    link_code = models.CharField(max_length=32, default="", blank=True, db_default="")
    code_expires_at = models.DateTimeField(null=True, blank=True)
    linked_at = models.DateTimeField(null=True, blank=True)
