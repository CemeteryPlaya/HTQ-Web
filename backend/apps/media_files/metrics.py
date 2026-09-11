"""Бизнес-метрики файлового хранилища.

Собирается по расписанию через ``apps.core.metrics`` — см. докстринг там.
Обращается только к своим моделям (правило изоляции аппок).

Обе метрики — зонды здоровья фоновых механизмов, а не величины хранилища:

* ``purge_backlog`` меряет задачу ``tasks.purge_soft_deleted`` (ежедневно
  03:00 UTC) её же работой: она удаляет ровно те строки, которые здесь
  считаются. Устойчиво ненулевое значение = beat или воркер не отработали;
* ``images_without_variants`` меряет ``tasks.make_variants``, который при
  ошибке обработки пишет ``logger.warning`` и идёт дальше — то есть
  сломанный конвейер превью сегодня не виден нигде.

Объём хранилища в байтах сюда сознательно не попал: полный ``Sum(size)`` по
самой большой таблице аппки раз в минуту — дорого, а вопрос «кончается место»
уже закрыт правилом ``htqweb-disk-space-low`` по метрикам хоста.
"""
from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from .models import FileKind, FileMetadata

# Окно, в котором отсутствие превью означает поломку, а не наследие. Сутки:
# всё, что старше, — это файлы, загруженные до появления обработчика, и
# пересоздавать их превью никто не собирается.
VARIANTS_WINDOW_HOURS = 24


def collect() -> dict:
    now = timezone.now()

    grace_days = getattr(settings, "MEDIA_SOFT_DELETE_GRACE_DAYS", 30)
    purge_backlog = FileMetadata.objects.filter(
        deleted_at__isnull=False,
        deleted_at__lt=now - timezone.timedelta(days=grace_days),
    ).count()

    # Свежие картинки, у которых не создалось ни одного варианта.
    without_variants = FileMetadata.objects.filter(
        kind=FileKind.IMAGE,
        deleted_at__isnull=True,
        created_at__gte=now - timezone.timedelta(hours=VARIANTS_WINDOW_HOURS),
        variants__isnull=True,
    ).count()

    return {
        "media_purge_backlog": {
            "help": ("Мягко удалённые файлы, пережившие срок хранения "
                     "(%d дн.) и не вычищенные" % grace_days),
            "values": [((), purge_backlog)],
        },
        "media_images_without_variants": {
            "help": ("Картинки за последние %d ч без единого превью"
                     % VARIANTS_WINDOW_HOURS),
            "values": [((), without_variants)],
        },
    }
