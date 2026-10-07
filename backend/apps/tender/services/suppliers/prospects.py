"""Потенциальные поставщики — ещё не контрагенты БЗО (T2.2; план этапов 0–2,
§4.3).

Справочник модуля: читает и правит держатель узла ``tender.prospects`` по
своему признаку. Карточку контрагента БЗО из потенциального поставщика
заводит выбор победителя (этап 5) — тогда заполнится ``counterparty_id``;
здесь он только читается.
"""

from __future__ import annotations

import re
import uuid

from django.db import transaction
from django.db.models import Q

from apps.tender.models import SupplierProspect
from apps.tender.services.core import audit
from apps.tender.services.core.errors import check_version
from apps.tender.services.tenders.ctx import Ctx, bad
from htqweb.errors import DomainError

from .contacts import email as clean_email

NODE = "tender.prospects"
NAME_MIN, NAME_MAX, REG_MAX = 2, 500, 30
_COUNTRY = re.compile(r"^[A-Z]{2}$")
LIST_LIMIT = 200


def out(row: SupplierProspect) -> dict:
    return {"id": str(row.pk), "name": row.name, "email": row.email,
            "reg_number": row.reg_number, "country_code": row.country_code,
            "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
            "version": row.version}


def _key(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def get(ctx: Ctx, prospect_id, *, lock: bool = False) -> SupplierProspect:
    ctx.require(NODE, "view", "Недостаточно прав на потенциальных поставщиков.")
    key = _key(prospect_id)
    rows = SupplierProspect.objects.select_for_update() if lock else SupplierProspect.objects
    row = rows.filter(pk=key).first() if key else None
    if row is None:
        raise DomainError("E-NOT-FOUND", "Потенциальный поставщик не найден.", status=404)
    return row


def search(ctx: Ctx, query: str) -> list[dict]:
    ctx.require(NODE, "view", "Недостаточно прав на потенциальных поставщиков.")
    rows = SupplierProspect.objects.all()
    if query:
        rows = rows.filter(Q(name__icontains=query) | Q(email__icontains=query)
                           | Q(reg_number__icontains=query))
    return [out(row) for row in rows.order_by("name")[:LIST_LIMIT]]


def _fill(row: SupplierProspect, data: dict) -> None:
    if "name" in data:
        name = (data["name"] or "").strip()
        if not NAME_MIN <= len(name) <= NAME_MAX:
            raise bad("name", f"наименование — от {NAME_MIN} до {NAME_MAX} символов")
        row.name = name
    if "email" in data:
        row.email = clean_email(data["email"])
    if data.get("reg_number") is not None:
        reg = data["reg_number"].strip()
        if len(reg) > REG_MAX:
            raise bad("reg_number", f"регистрационный номер — до {REG_MAX} символов")
        row.reg_number = reg
    if data.get("country_code") is not None:
        code = data["country_code"].strip().upper()
        if not _COUNTRY.match(code):
            raise bad("country_code", "страна — двухбуквенный код ISO 3166")
        row.country_code = code


@transaction.atomic
def create(ctx: Ctx, data: dict) -> SupplierProspect:
    ctx.require(NODE, "create", "Недостаточно прав, чтобы заводить потенциальных поставщиков.")
    row = SupplierProspect(created_by=ctx.user_id, updated_by=ctx.user_id)
    _fill(row, {"name": data.get("name"), "email": data.get("email"),
                "reg_number": data.get("reg_number"),
                "country_code": data.get("country_code") or "KZ"})
    row.save()
    audit.record(row, "created", actor_id=ctx.user_id, changes=out(row))
    return row


@transaction.atomic
def update(ctx: Ctx, prospect_id, *, expected_version: int | None, data: dict
           ) -> SupplierProspect:
    ctx.require(NODE, "edit", "Недостаточно прав, чтобы править потенциальных поставщиков.")
    row = get(ctx, prospect_id, lock=True)
    check_version(row, expected_version)
    before = out(row)
    _fill(row, data)
    row.version += 1
    row.updated_by = ctx.user_id
    row.save()
    audit.record(row, "updated", actor_id=ctx.user_id,
                 changes={"before": before, "after": out(row)})
    return row
