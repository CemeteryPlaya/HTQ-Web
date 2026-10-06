"""Модели тендерного модуля (docs/plans/2026-10-06-tender-master-plan.md, §3.2).

Тенантные: таблицы живут в схеме компании, поля компании нет и быть не
должно (CLAUDE.md, «Мультикомпанейность»). Ссылки на bpp/project/refdata —
голые UUIDField без FK: между аппками связь только через interface.
"""

from .core import AuditLog, NumberSequence, TenderModel, VersionedModel

__all__ = ["AuditLog", "NumberSequence", "TenderModel", "VersionedModel"]
