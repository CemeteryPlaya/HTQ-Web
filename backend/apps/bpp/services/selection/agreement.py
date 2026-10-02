"""Выбор альтернативы по договору — итог голосования ФД и ГД (B5.1; ТЗ §12.4
п.1, 3; D-25, D-26; решение D-B51-8, замечание ревью этапа 5 B-6).

``apply_final_choice(agreement_id)`` зовёт ``agreements.on_approved``
первой строкой: процесс уже согласован (движок пометил его до колбэка, в
той же транзакции), и решающий голос — у последнего выбирающего этапа
(``signoff.final_option``). Голос за альтернативу — выбор:

1. ``lifecycle.mark_selected`` — пока договор ещё «На согласовании» (окно
   подачи открыто), прочие «Подано» → «Не выбрано»;
2. договор → «Заменён альтернативой» (а не «Действует»), KPI синхронизирован;
3. новый документ — ``documents.replace_with``, выбравший — тот, чей голос
   решил (ГД).

Голос за исходный договор (или вариантов не было) — ``False``: дальше
прежний путь «Действует». BR-093 здесь не повторяется: его проверил
``voting.check_option`` до записи того же голоса, в той же транзакции.
"""

from __future__ import annotations

from apps.bpp.models import Agreement, AgreementStatus
from apps.bpp.services.alternatives import kpi, lifecycle
from apps.signoff import interface as signoff

from . import documents

SUBJECT = Agreement.SIGNOFF_SUBJECT_TYPE


def apply_final_choice(agreement_id) -> bool:
    """``True`` — решающий голос за альтернативу, договор заменён; ``False`` —
    за исходный, договор вступает в силу обычным порядком."""
    final = signoff.final_option(SUBJECT, str(agreement_id))
    key = (final or {}).get("key") or ""
    if not key.startswith(lifecycle.OFFER_PREFIX):
        return False
    agr = Agreement.objects.select_for_update().get(pk=agreement_id)
    offer = lifecycle.mark_selected(
        key[len(lifecycle.OFFER_PREFIX):], actor_id=final["actor_id"],
        comment=f"Решающий голос согласования: {final['label']}")
    Agreement.objects.filter(pk=agr.pk).update(status=AgreementStatus.REPLACED,
                                               rework_comment="")
    agr.refresh_from_db()
    kpi.sync_for_document(lifecycle.SOURCE_AGREEMENT, agr.pk)
    offer.refresh_from_db()
    documents.replace_with(offer, agr, selector_id=final["actor_id"])
    return True
