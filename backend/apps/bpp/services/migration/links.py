"""Связи переноса «запись ``contracts`` → запись модуля» (D-B61-9).

``link`` пишет связь и сторожит, что источник не переехал в два разных
места; ``target_of`` отвечает команде «уже перенесено?»; ``targets`` отдаёт
соседу (заморозка ``contracts``, A6.2), куда переехали его записи, — с
номером документа, чтобы старая карточка показала «перенесён в ДГ-…».
"""

from __future__ import annotations

from apps.bpp.models import (
    AccountableFundsRequest,
    Agreement,
    Budget,
    Invoice,
    MigrationLink,
    PurchaseRequest,
)

#: Типы целей с номером документа — для подписи «перенесён в …».
_NUMBERED = {
    "bpp.agreement": Agreement,
    "bpp.invoice": Invoice,
    "bpp.accountable_funds_request": AccountableFundsRequest,
    "bpp.purchase_request": PurchaseRequest,
    "bpp.budget": Budget,
}


class LinkConflict(Exception):
    """Источник уже связан с другой целью того же типа — данные разошлись
    (запись цели удалили руками или перенос шёл с другой картой)."""


def target_of(source_type: str, source_id, target_type: str) -> str | None:
    return (MigrationLink.objects
            .filter(source_type=source_type, source_id=str(source_id), target_type=target_type)
            .values_list("target_id", flat=True).first())


def link(source_type: str, source_id, target_type: str, target_id) -> None:
    row, created = MigrationLink.objects.get_or_create(
        source_type=source_type, source_id=str(source_id), target_type=target_type,
        defaults={"target_id": str(target_id)})
    if not created and row.target_id != str(target_id):
        raise LinkConflict(
            f"{source_type} {source_id} уже перенесён в {target_type} {row.target_id}, "
            f"а не в {target_id}.")


def targets(source_type: str, source_ids) -> dict[str, list[dict]]:
    """``{ключ источника: [{target_type, target_id, number}]}`` — только
    перенесённые; ``number`` — у документов с номером, иначе ``None``."""
    rows = list(MigrationLink.objects
                .filter(source_type=source_type, source_id__in=[str(i) for i in source_ids])
                .order_by("created_at"))
    numbers: dict[tuple[str, str], str] = {}
    for target_type, model in _NUMBERED.items():
        ids = [row.target_id for row in rows if row.target_type == target_type]
        if ids:
            numbers.update({(target_type, str(pk)): number for pk, number in
                            model.objects.filter(pk__in=ids).values_list("pk", "number")})
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(row.source_id, []).append({
            "target_type": row.target_type, "target_id": row.target_id,
            "number": numbers.get((row.target_type, row.target_id))})
    return out
