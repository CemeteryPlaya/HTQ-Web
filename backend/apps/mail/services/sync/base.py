"""Общая форма результата sync-прогона — буквальный порт
``services/email/app/services/sync/base.py::SyncResult``.

``SyncDriver`` Protocol исходника (initial_backfill/incremental/
register_push/renew_push/unregister_push — все требуют живого HTTP/IMAP) НЕ
портируется здесь (Р2 брифа mail-messages, см. ``sync/__init__.py``) — только
форма результата, которую использует ``mapper.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SyncResult:
    """Aggregate counters returned from any sync run."""

    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    attachments_saved: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "SyncResult") -> "SyncResult":
        return SyncResult(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            skipped=self.skipped + other.skipped,
            deleted=self.deleted + other.deleted,
            attachments_saved=self.attachments_saved + other.attachments_saved,
            errors=self.errors + other.errors,
        )
