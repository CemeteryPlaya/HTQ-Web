"""Контрагент из потенциального поставщика тендера (тендер T5.4, зона A;
мастер-план tender §3.4).

Передача выбора в БЗО заводит карточку контрагента по реквизитам, которые
потенциальный поставщик ввёл в портале. Совпадение страна + рег. номер —
привязка к существующей карточке (``uq_bpp_counterparty_reg``), а не дубль.
Карточка — сразу «Активен», без метки «Проверенный» (D-20): подтверждение
E-CTR-05 — штатно, при отправке документа. Заводит её закупщик своими
правами БЗО (узел ``bpp.counterparties`` create — СН и ПМ, ``access/0014``).
"""

from __future__ import annotations

from apps.bpp.models import Counterparty, CounterpartyStatus
from apps.bpp.schemas.tender import CounterpartyRef, ProspectIn, TenderActor
from apps.bpp.services.counterparties import service, validation
from htqweb.errors import DomainError

from .tender import _actor

NODE = "bpp.counterparties"


def _refused(text: str, *, field: str | None = None) -> DomainError:
    fields = [{"field": field, "message": text}] if field else None
    return DomainError("E-TND-14", text, fields=fields)


def _kind(country: str, reg_number: str) -> str:
    """Казахстанский 12-значный БИН/ИИН — юрлицо, прочее — нерезидент: точнее
    по реквизитам портала не узнать, карточку при нужде правит ФД или БУХ."""
    return "legal" if country == "KZ" and reg_number.isdigit() and len(reg_number) == 12 \
        else "nonresident"


def create_from_prospect(data: ProspectIn, *, actor: TenderActor) -> CounterpartyRef:
    data = ProspectIn.model_validate(data)
    reg_number = validation.normalize_reg_number(data.reg_number)
    country = (data.country_code or "KZ").strip().upper()
    if not reg_number:
        raise _refused(f"У поставщика «{data.name}» нет БИН/ИИН или регистрационного номера — "
                       f"без него карточку контрагента не завести. Попросите поставщика "
                       f"дополнить реквизиты.", field="reg_number")
    existing = Counterparty.objects.filter(country_code=country, reg_number=reg_number).first()
    if existing is not None:
        if existing.status != CounterpartyStatus.ACTIVE:
            raise _refused(f"Контрагент «{existing.name}» ({reg_number}) "
                           f"{existing.get_status_display().lower()} — передать ему документы "
                           f"нельзя.")
        return CounterpartyRef(id=str(existing.pk), created=False, status=existing.status)
    if not _actor(actor).can(NODE, "create"):
        raise DomainError("E-ACC-01", "Недостаточно прав, чтобы завести контрагента в БЗО.",
                          status=403)
    card = service.create({
        "name": data.name, "short_name": data.name, "kind": _kind(country, reg_number),
        "country_code": country, "reg_number": reg_number,
        "is_vat_payer": data.is_vat_payer, "contact_person": data.contact_name,
        "phone": data.phone, "email": data.email,
    }, actor_id=actor.user_id,
        audit_comment=f"из тендера {data.tender_number}" if data.tender_number else "из тендера")
    return CounterpartyRef(id=str(card.pk), created=True, status=card.status)
