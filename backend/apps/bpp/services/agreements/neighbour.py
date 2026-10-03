"""Договор глазами соседа — для привлечения партнёра ``tasks`` (хвост этапа 6, M-5).

Наружу идёт минимум: ``id, number, status, counterparty_id`` — сумм, позиций и
проекта сосед не получает. Поиск уважает права пользователя на договоры тем же
``can_view``, что реестр: «все договоры» — по узлу ``bpp.agreements.all``, СН и
ПМ — свои проекты и группы статей, автор — свои. Нет права на узел
``bpp.agreements`` (и «все» тоже) — пусто.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from django.db.models import Q

from apps.bpp.models import Agreement, AgreementStatus
from apps.bpp.services.actor import Actor

from . import agreements as service

#: Статусы, в которых договор годится для привлечения: действует либо
#: исполнен. Черновик, согласование, доработка, отклонён, расторгнут и
#: заменён — нет.
USABLE_STATUSES = (AgreementStatus.ACTIVE, AgreementStatus.FULFILLED)


def _card(agr: Agreement) -> dict:
    return {"id": str(agr.pk), "number": agr.number, "status": agr.status,
            "counterparty_id": str(agr.counterparty_id) if agr.counterparty_id else None,
            "is_annex": agr.parent_agreement_id is not None}


def brief(ids) -> dict[str, dict]:
    """``{id строкой: {id, number, status, counterparty_id, is_annex}}``; невозможные
    и несуществующие ключи в ответ не попадают."""
    keys = set()
    for raw in ids:
        try:
            keys.add(uuid.UUID(str(raw)))
        except ValueError:
            continue
    if not keys:
        return {}
    return {str(agr.pk): _card(agr) for agr in Agreement.objects.filter(pk__in=keys)}


def _actor(token, company: str | None) -> Actor:
    return Actor(SimpleNamespace(token=token, company={"slug": company} if company else None,
                                 META={}))


def visible_brief(ids, *, token, company: str | None) -> dict[str, dict]:
    """Как ``brief``, но только договоры, которые ``token`` вправе видеть
    (``can_view``, как в реестре). Невидимый отвечает так же, как
    несуществующий: по ответу нельзя узнать, что договор есть."""
    found = brief(ids)
    if not found:
        return {}
    actor = _actor(token, company)
    if not (service.sees_all(actor) or actor.can("bpp.agreements", "view")):
        return {}
    rows = {str(a.pk): a for a in Agreement.objects.filter(pk__in=list(found))}
    return {key: card for key, card in found.items() if service.can_view(actor, rows[key])}


def search(query: str | None, *, counterparty_id, token, company: str | None,
           limit: int = 20) -> list[dict]:
    """Договоры контрагента, годные для привлечения, — для выбора в чужой форме.

    Номер, номер по документу или наименование от 2 символов. Права
    пользователя — как в реестре договоров (см. докстринг модуля)."""
    try:
        counterparty = uuid.UUID(str(counterparty_id))
    except ValueError:
        return []
    actor = _actor(token, company)
    if not (service.sees_all(actor) or actor.can("bpp.agreements", "view")):
        return []
    rows = Agreement.objects.filter(counterparty_id=counterparty,
                                    status__in=USABLE_STATUSES,
                                    parent_agreement__isnull=True)
    text = (query or "").strip()
    if len(text) >= 2:
        rows = rows.filter(Q(number__icontains=text) | Q(ext_number__icontains=text)
                           | Q(name__icontains=text))
    out = []
    for agr in rows.order_by("-created_at"):
        if service.can_view(actor, agr):
            out.append({**_card(agr), "name": agr.name, "ext_number": agr.ext_number,
                        "ext_date": agr.ext_date})
            if len(out) >= limit:
                break
    return out
