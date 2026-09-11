"""Бизнес-метрики мессенджера.

Собирается по расписанию через ``apps.core.metrics`` — см. докстринг там.
Обращается только к своим моделям (правило изоляции аппок).

Доставка сообщений в мессенджере — fire-and-forget через Socket.IO, состояния
доставки в базе нет вовсе, поэтому «сколько не доставлено» здесь невыразимо в
принципе. Присутствие живёт только в Redis и тоже не считается.

Что остаётся измеримым — две вещи:

* возраст последнего сообщения. Транспорт ломается молча: сообщения просто
  перестают появляться, и все считают, что сегодня тихо. Метрика ПАНЕЛЬНАЯ и
  порога не имеет намеренно — ночью, в выходные и в отпуск она законно растёт
  до суток, и любой алерт по ней горел бы вечно;
* вложения, у которых нет ссылки на файл. На пути создания поле заполняется
  всегда, поэтому NULL на свежей строке означает, что запись в чат прошла, а
  загрузка в файловое хранилище — нет.
"""
from __future__ import annotations

from django.db.models import Max
from django.utils import timezone

from .models import ChatAttachment, Message

# Окно для битых вложений: строки старше недели — это наследие, а не
# сегодняшняя поломка, и держать их в метрике значит держать её ненулевой
# навсегда.
BROKEN_WINDOW_DAYS = 7


def collect() -> dict:
    now = timezone.now()

    broken = ChatAttachment.objects.filter(
        file_metadata_id__isnull=True,
        created_at__gte=now - timezone.timedelta(days=BROKEN_WINDOW_DAYS),
    ).count()

    result = {
        "messenger_attachments_broken": {
            "help": ("Вложения за %d дн. без ссылки на файл в хранилище"
                     % BROKEN_WINDOW_DAYS),
            "values": [((), broken)],
        },
    }

    # Условная метрика: на пустой базе «сообщений не было никогда» и «только
    # что написали» нулём выглядели бы одинаково.
    latest = Message.objects.aggregate(last=Max("created_at"))["last"]
    if latest is not None:
        result["messenger_last_message_age_seconds"] = {
            "help": "Секунд с последнего сообщения в любом чате",
            "values": [((), (now - latest).total_seconds())],
        }
    return result
