"""Бизнес-метрики корпоративной почты.

Собирается по расписанию через ``apps.core.metrics`` — см. докстринг там.
Обращается только к своим моделям (правило изоляции аппок).

Почта — самый заметный для людей домен: она ломается тихо (сломался IMAP —
письма просто перестают приходить), и техническими метриками это не
детектируется никак. Отсюда упор на «когда была последняя успешная
синхронизация» и «сколько ящиков с ошибкой».
"""
from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from .models import EmailAccount, EmailMessage, Folder


def collect() -> dict:
    accounts = EmailAccount.objects.filter(is_active=True)
    total = accounts.count()
    failing = accounts.exclude(
        Q(last_sync_error__isnull=True) | Q(last_sync_error="")).count()

    # Отставание синхронизации: сколько секунд прошло с самой свежей
    # успешной синхронизации по всем ящикам. Растущее число — почта встала,
    # даже если контейнеры зелёные.
    latest = (accounts.exclude(last_sync_at__isnull=True)
              .order_by("-last_sync_at")
              .values_list("last_sync_at", flat=True).first())
    lag = (timezone.now() - latest).total_seconds() if latest else None

    result = {
        "mail_accounts_active": {
            "help": "Активные почтовые ящики",
            "values": [((), total)],
        },
        "mail_accounts_failing": {
            "help": "Ящики с непустой ошибкой последней синхронизации",
            "values": [((), failing)],
        },
        "mail_outbox_size": {
            "help": "Письма, застрявшие в папке «Исходящие»",
            "values": [((), EmailMessage.objects.filter(
                folder=Folder.OUTBOX).count())],
        },
    }

    # None не экспортируем: «ни разу не синхронизировались» и «синхронизация
    # только что прошла» нулём выглядели бы одинаково.
    if lag is not None:
        result["mail_sync_lag_seconds"] = {
            "help": "Секунд с последней успешной синхронизации любого ящика",
            "values": [((), lag)],
        }
    return result
