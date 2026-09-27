"""Файлы документов модуля (ТЗ §21, D-31).

Сами байты — в ``apps.media_files`` (scope ``bpp_doc``); здесь паспорт:
какому документу принадлежит, какого типа, какая версия, кто загрузил.
Новая версия не стирает старую — старая получает ``replaced`` и остаётся
в истории (ТЗ: «файлы не удаляются физически после отправки документа»).
"""

from __future__ import annotations

from django.db import models
from django.db.models.functions import Now

from .core import BppModel


class DocumentFile(BppModel):
    owner_type = models.CharField(max_length=64)
    owner_id = models.CharField(max_length=64)
    file_type = models.CharField(max_length=32)
    media_file_id = models.CharField(max_length=64)
    filename = models.CharField(max_length=255)
    mime = models.CharField(max_length=128)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    replaced = models.BooleanField(default=False, db_default=False)
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="next_versions")

    class Meta:
        indexes = [models.Index(fields=["owner_type", "owner_id", "file_type"],
                                name="ix_bpp_file_owner")]
        verbose_name = "Файл документа"
        verbose_name_plural = "Файлы документов"


class FileDownload(models.Model):
    """Журнал скачиваний (ТЗ §25.2): кто и когда получил ссылку на файл."""

    file = models.ForeignKey(DocumentFile, on_delete=models.PROTECT, related_name="downloads")
    user_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Скачивание файла"
        verbose_name_plural = "Журнал скачиваний"
