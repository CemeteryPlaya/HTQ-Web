"""Связи переноса из ``contracts`` (B6.1, D-B61-9).

Одна строка — «эта запись ``contracts`` стала этой записью модуля». На ней
держится идемпотентность ``bpp_migrate_contracts``: повторный прогон видит
перенесённое и пропускает его, а не заводит второй договор. Той же таблицей
заморозка ``contracts`` (A6.2) показывает на старой карточке, куда документ
переехал (``interface.migrated_targets``).

Ключи — строками, как ``owner_id`` подсистемы файлов: у источника целые id,
у целей UUID, а межаппный FK запрещён. Один источник может дать несколько
целей разных типов (договор → договор и техническая заявка), поэтому
уникальна тройка «тип источника, ключ источника, тип цели». Сальдо закрытых
документов (D-B61-1) — источник ``contracts.saldo`` с ключом
«<проект>:<статья>».
"""

from __future__ import annotations

from django.db import models

from .core import BppModel

__all__ = ["MigrationLink"]


class MigrationLink(BppModel):
    source_type = models.CharField(max_length=64)
    source_id = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source_type", "source_id", "target_type"],
                                    name="uq_bpp_migration_source_target"),
        ]
        indexes = [models.Index(fields=["target_type", "target_id"],
                                name="ix_bpp_migration_target")]
        verbose_name = "Связь переноса из «Договоров»"
        verbose_name_plural = "Связи переноса из «Договоров»"

    def __str__(self) -> str:
        return f"{self.source_type}:{self.source_id} → {self.target_type}:{self.target_id}"
