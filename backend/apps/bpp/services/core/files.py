"""Файлы документов: типы и лимиты ТЗ §21, версии, журнал скачиваний."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.bpp.models import DocumentFile, FileDownload
from apps.media_files import interface as media
from htqweb.errors import DomainError

from . import audit, scanner

PDF = "application/pdf"
JPG = "image/jpeg"
PNG = "image/png"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XML = ("application/xml", "text/xml")
TXT = "text/plain"
CSV = "text/csv"


@dataclass(frozen=True)
class FileRule:
    title: str
    mimes: tuple[str, ...]
    max_mb: int
    max_count: int


FILE_RULES: dict[str, FileRule] = {
    "request_attachment": FileRule("КП, ТЗ, спецификация", (PDF, DOCX, XLSX, JPG, PNG), 20, 20),
    "agreement": FileRule("Договор", (PDF, DOCX, JPG, PNG), 20, 1),
    "agreement_annex": FileRule("Приложение к договору", (PDF, DOCX, JPG, PNG), 20, 30),
    "invoice": FileRule("Счёт на оплату", (PDF, JPG, PNG), 10, 5),
    "act": FileRule("АВР", (PDF, JPG, PNG), 10, 10),
    "waybill": FileRule("Накладная", (PDF, JPG, PNG), 10, 10),
    "vat_invoice": FileRule("Счёт-фактура", (PDF, JPG, PNG, *XML), 10, 10),
    "bank_statement": FileRule("Выписка банка", (TXT, XLSX, CSV), 20, 1),
    "alternative_offer": FileRule("Коммерческое предложение", (PDF, DOCX, XLSX, JPG, PNG), 20, 5),
}


def _serialize(row: DocumentFile) -> dict:
    return {
        "id": str(row.id), "file_type": row.file_type, "filename": row.filename,
        "mime": row.mime, "size": row.size, "sha256": row.sha256,
        "version": row.version, "replaced": row.replaced,
        "uploaded_by": row.created_by, "uploaded_at": row.created_at.isoformat(),
    }


def _check(rule: FileRule, *, data: bytes, filename: str, mime: str) -> None:
    if mime not in rule.mimes:
        raise DomainError(
            "E-FILE-01",
            f"Формат файла «{filename}» не подходит для «{rule.title}». "
            f"Допустимы: {', '.join(sorted({m.split('/')[-1] for m in rule.mimes}))}.",
            status=415)
    if len(data) > rule.max_mb * 1024 * 1024:
        raise DomainError(
            "E-FILE-02",
            f"Файл «{filename}» больше {rule.max_mb} МБ. Уменьшите файл и загрузите снова.",
            status=413)
    scanner.scan(data, filename)


def _store(data: bytes, filename: str, mime: str, actor_id: int) -> dict:
    return media.store_file(data=data, filename=filename, mime=mime, scope="bpp_doc",
                            owner_id=actor_id, internal_authorized=True)


def _current(owner_type: str, owner_id: str, file_type: str | None = None):
    rows = DocumentFile.objects.filter(owner_type=owner_type, owner_id=owner_id,
                                       replaced=False)
    return rows.filter(file_type=file_type) if file_type else rows


@transaction.atomic
def attach(owner, file_type: str, *, data: bytes, filename: str, mime: str,
           actor_id: int) -> dict:
    rule = FILE_RULES[file_type]
    owner_type, owner_id = owner._meta.label_lower, str(owner.pk)
    if _current(owner_type, owner_id, file_type).count() >= rule.max_count:
        raise DomainError(
            "E-FILE-03",
            f"К документу уже приложено {rule.max_count} файл(ов) типа «{rule.title}» — "
            f"это предел. Замените один из них новой версией.",
            status=422)
    _check(rule, data=data, filename=filename, mime=mime)
    stored = _store(data, filename, mime, actor_id)
    row = DocumentFile.objects.create(
        owner_type=owner_type, owner_id=owner_id, file_type=file_type,
        media_file_id=str(stored["id"]), filename=filename, mime=mime,
        size=stored["size"], sha256=stored.get("sha256") or "",
        created_by=actor_id, updated_by=actor_id,
    )
    audit.record(owner, "file_attached", actor_id=actor_id,
                 changes={"file": str(row.id), "file_type": file_type, "filename": filename})
    return _serialize(row)


@transaction.atomic
def replace(file_id: str, *, data: bytes, filename: str, mime: str, actor_id: int) -> dict:
    old = DocumentFile.objects.select_for_update().get(pk=file_id, replaced=False)
    _check(FILE_RULES[old.file_type], data=data, filename=filename, mime=mime)
    stored = _store(data, filename, mime, actor_id)
    old.replaced = True
    old.save(update_fields=["replaced", "updated_at"])
    row = DocumentFile.objects.create(
        owner_type=old.owner_type, owner_id=old.owner_id, file_type=old.file_type,
        media_file_id=str(stored["id"]), filename=filename, mime=mime,
        size=stored["size"], sha256=stored.get("sha256") or "",
        version=old.version + 1, previous=old, created_by=actor_id, updated_by=actor_id,
    )
    return _serialize(row)


def list_files(owner) -> list[dict]:
    rows = _current(owner._meta.label_lower, str(owner.pk)).order_by("created_at")
    return [_serialize(row) for row in rows]


def download_url(file_id: str, *, user_id: int) -> str:
    row = DocumentFile.objects.get(pk=file_id)
    FileDownload.objects.create(file=row, user_id=user_id)
    return media.get_file_url(row.media_file_id) or ""
