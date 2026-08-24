"""Где лежат записи конференций и как они попадают в браузер.

Байты идут через ``htqweb.storage.get_storage()`` НАПРЯМУЮ, а не через
``apps.media_files.interface.store_file()``. Тот же выбор и по той же причине
сделан в ``apps/messenger/services/history_archive_service.py`` (см. его
докстринг): у ``store_file`` семантика пользовательского файла — владелец,
scope, миниатюры, мягкое удаление, стабильная ссылка. У записи конференции
ничего этого нет: владельца нет (встреча общая), миниатюры не нужны,
а удаление у неё своё — жёсткое и по сроку, а не мягкое навсегда. Заводить
на каждое видео строку ``FileMetadata`` значило бы обещать поведение,
которого у этих объектов нет.

Бакет — ``CONFERENCE_S3_BUCKET``, по умолчанию тот же ``MEDIA_S3_BUCKET``, но
под собственным префиксом ``conference/``. Третий бакет не заводим осознанно:
``apps/core/management/commands/ensure_buckets.py`` держит ровно два и
объясняет почему.
"""

from __future__ import annotations

import logging

from django.conf import settings

from htqweb.storage import get_storage

logger = logging.getLogger(__name__)


def storage():
    return get_storage(bucket=settings.CONFERENCE_S3_BUCKET)


def session_prefix(session) -> str:
    """Каталог объектов одной встречи.

    Раскладка по годам и месяцам — не украшение: листинг бакета с десятками
    тысяч ключей в одном префиксе неудобен и в консоли MinIO, и в правилах
    жизненного цикла S3, если прод захочет продублировать нашу ретенцию
    средствами хранилища.
    """
    started = session.started_at
    return f"conference/sessions/{started:%Y}/{started:%m}/{session.pk}"


def put(path: str, data: bytes, content_type: str) -> None:
    storage().save(path, data, content_type=content_type)


def playback_url(path: str, *, download_as: str | None = None) -> str:
    """Прямая временная ссылка на объект для ``<video>`` или скачивания.

    Именно ссылка, а не отдача байтов через Django. Вариант «прочитать файл
    и вернуть ``HttpResponse``» (как это делает загрузка HR-документов)
    для часового видео не работает: он тянет файл целиком в память и теряет
    поддержку ``Range``, то есть перемотку — плеер сможет только проиграть
    запись с начала. Presigned-ссылка отдаёт Range нативно.
    """
    return storage().presigned_get_url(path, download_as=download_as)


def delete_many(paths) -> int:
    """Снести объекты, не прерываясь на первом сбое.

    Уборщик ретенции обязан дойти до конца: если один ключ не удалился
    (объекта уже нет, хранилище моргнуло), остальные всё равно должны быть
    вычищены — иначе одна плохая строка держит на диске всё, что за ней.
    Та же логика, что у ``apps/media_files/tasks.py::purge_soft_deleted``.
    """
    backend = storage()
    removed = 0
    for path in paths:
        try:
            backend.delete(path)
            removed += 1
        except Exception:
            logger.exception("conference: не удалось удалить объект %s", path)
    return removed
