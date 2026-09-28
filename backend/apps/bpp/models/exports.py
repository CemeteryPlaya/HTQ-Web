"""Фоновая выгрузка реестра в xlsx (ТЗ §19, мастер-план D-32; A2.2, задача 6).

Строка на каждый экспорт больше ``export.SYNC_LIMIT`` строк: кто заказал,
что собирается, чем кончилось и где лежит файл. Малые выгрузки (до 10 000
строк) отдаются тем же запросом и строки здесь не оставляют.

Почему таблица, а не запись в кэше. Redis платформы работает с
``maxmemory-policy allkeys-lru`` (все три compose-файла): под нагрузкой
запись о задании вытесняется молча, и ссылка из уведомления, которое в
центре живёт бессрочно, отвечала бы 404 на готовый файл, лежащий в S3 без
хозяина. Строка в схеме компании не вытесняется, а файл остаётся
привязан к тому, кто его заказал.

Не документ модуля: без номера, версии и согласования — поэтому не
``BppModel``/``VersionedModel``. Скачивание журналируется в ``AuditLog``
(ТЗ §25.2: «скачивание файлов») с типом ``bpp.exportjob``.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now

__all__ = ["ExportJob", "ExportStatus"]


class ExportStatus(models.TextChoices):
    QUEUED = "queued", "Готовится"
    DONE = "done", "Готов"
    ERROR = "error", "Не собран"


class ExportJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requested_by = models.IntegerField()
    name = models.CharField(max_length=255)
    #: Сколько строк насчитала ручка реестра в момент заказа (фон
    #: пересобирает выборку заново, поэтому в файле может оказаться иначе).
    row_count = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=ExportStatus.choices,
                              default=ExportStatus.QUEUED, db_default=ExportStatus.QUEUED)
    #: Файл в ``apps.media_files`` (scope ``generic``) — ``None``, пока не собран.
    media_file_id = models.UUIDField(null=True, blank=True)
    #: Причина отказа сборки — текст для человека (ТЗ §26: что, почему, что делать).
    error = models.TextField(default="", blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["requested_by", "-created_at"],
                                name="ix_bpp_export_requester")]
        ordering = ("-created_at",)
        verbose_name = "Фоновая выгрузка"
        verbose_name_plural = "Фоновые выгрузки"
