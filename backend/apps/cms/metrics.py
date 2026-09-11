"""Бизнес-метрики публичного сайта.

Собирается по расписанию через ``apps.core.metrics`` — см. докстринг там.
Обращается только к своим моделям (правило изоляции аппок).

Обе метрики документируют места, где сегодня НЕТ вообще никакого сигнала:

* обращение с сайта: единственное уведомление о нём —
  ``tasks.notify_admins_on_contact_request``, а он молча ничего не делает при
  пустом ``ADMINS`` и глотает ``OSError`` при недоступном SMTP. То есть заявка
  клиента может пролежать неделю, и об этом не узнает никто;
* отложенная публикация: ``tasks.publish_scheduled_news`` не зарегистрирован в
  расписании beat вовсе, а его фильтр (``published_at IS NOT NULL``) не может
  совпасть с запланированной новостью в принципе — планирование обнуляет это
  поле. Метрика не чинит задачу, но показывает, когда её отсутствие стало
  кому-то мешать.
"""
from __future__ import annotations

from django.utils import timezone

from .models import ContactRequest, News, NewsStatus

# Сколько часов обращение может лежать без ответа, прежде чем это станет
# поводом сказать вслух. Сутки — граница «ответили на следующий рабочий день».
UNHANDLED_HOURS = 24


def collect() -> dict:
    now = timezone.now()

    unhandled = ContactRequest.objects.filter(
        handled=False,
        created_at__lt=now - timezone.timedelta(hours=UNHANDLED_HOURS),
    ).count()

    overdue = News.objects.filter(
        status=NewsStatus.SCHEDULED, scheduled_at__lt=now).count()

    return {
        "cms_contact_requests_unhandled": {
            "help": ("Обращения с сайта без ответа дольше %d часов"
                     % UNHANDLED_HOURS),
            "values": [((), unhandled)],
        },
        "cms_news_scheduled_overdue": {
            "help": "Новости, у которых время публикации прошло, а публикации нет",
            "values": [((), overdue)],
        },
    }
