"""Контакты контрагентов для приглашений (T2.2; план этапов 0–2, §4.3).

Справочник модуля, а не документ: правит любой держатель узла
``tender.prospects`` по своему признаку (создать / править / удалить).
Контрагент — карточка БЗО, читается только через ``bpp.interface``. Адрес
хранится в нижнем регистре: приглашение сравнивает адреса точно.
"""

from __future__ import annotations

import re
import uuid

from django.db import IntegrityError, transaction

from apps.bpp import interface as bpp
from apps.tender.models import SupplierContact
from apps.tender.services.core import audit
from apps.tender.services.tenders.ctx import Ctx, bad
from htqweb.errors import DomainError

NODE = "tender.prospects"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NAME_MAX, PHONE_MAX, EMAIL_MAX = 255, 64, 254


def email(value: str | None, field_name: str = "email") -> str:
    """Почта: без пробелов по краям, нижним регистром, вида ``a@b.c``."""
    clean = (value or "").strip().lower()
    if not clean or len(clean) > EMAIL_MAX or not _EMAIL.match(clean):
        raise bad(field_name, "укажите адрес электронной почты вида name@company.kz")
    return clean


def _key(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def out(row: SupplierContact) -> dict:
    return {"id": str(row.pk), "counterparty_id": str(row.counterparty_id),
            "email": row.email, "name": row.name, "phone": row.phone,
            "is_primary": row.is_primary, "is_active": row.is_active}


def list_contacts(ctx: Ctx, counterparty_id: str | None) -> list[dict]:
    ctx.require(NODE, "view", "Недостаточно прав на контакты поставщиков.")
    rows = SupplierContact.objects.all()
    if counterparty_id:
        key = _key(counterparty_id)
        if key is None:
            raise bad("counterparty_id", "неверный ключ контрагента")
        rows = rows.filter(counterparty_id=key)
    return [out(row) for row in rows.order_by("-is_primary", "name", "email")]


def _get(contact_id) -> SupplierContact:
    key = _key(contact_id)
    row = SupplierContact.objects.select_for_update().filter(pk=key).first() if key else None
    if row is None:
        raise DomainError("E-NOT-FOUND", "Контакт не найден.", status=404)
    return row


def _save(row: SupplierContact) -> None:
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError:
        raise bad("email", "такой адрес у этого контрагента уже есть") from None
    if row.is_primary:
        # Основной контакт у контрагента один.
        (SupplierContact.objects.filter(counterparty_id=row.counterparty_id, is_primary=True)
         .exclude(pk=row.pk).update(is_primary=False))


def _fill(row: SupplierContact, data: dict) -> None:
    if "email" in data:
        row.email = email(data["email"])
    if data.get("name") is not None:
        row.name = data["name"].strip()[:NAME_MAX]
    if data.get("phone") is not None:
        row.phone = data["phone"].strip()[:PHONE_MAX]
    for flag in ("is_primary", "is_active"):
        if data.get(flag) is not None:
            setattr(row, flag, bool(data[flag]))


@transaction.atomic
def create(ctx: Ctx, data: dict) -> dict:
    ctx.require(NODE, "create", "Недостаточно прав, чтобы заводить контакты поставщиков.")
    key = _key(data.get("counterparty_id"))
    if key is None or str(key) not in bpp.counterparty_brief([str(key)]):
        raise bad("counterparty_id", "контрагент не найден")
    row = SupplierContact(counterparty_id=key, created_by=ctx.user_id, updated_by=ctx.user_id)
    _fill(row, {**data, "email": data.get("email")})
    _save(row)
    audit.record(row, "created", actor_id=ctx.user_id, changes=out(row))
    return out(row)


@transaction.atomic
def update(ctx: Ctx, contact_id, data: dict) -> dict:
    ctx.require(NODE, "edit", "Недостаточно прав, чтобы править контакты поставщиков.")
    row = _get(contact_id)
    before = out(row)
    _fill(row, data)
    row.updated_by = ctx.user_id
    _save(row)
    audit.record(row, "updated", actor_id=ctx.user_id,
                 changes={"before": before, "after": out(row)})
    return out(row)


@transaction.atomic
def delete(ctx: Ctx, contact_id) -> None:
    """Приглашения хранят копию адреса — удаление контакта их не задевает."""
    ctx.require(NODE, "delete", "Недостаточно прав, чтобы удалять контакты поставщиков.")
    row = _get(contact_id)
    audit.record(row, "deleted", actor_id=ctx.user_id, changes=out(row))
    row.delete()
