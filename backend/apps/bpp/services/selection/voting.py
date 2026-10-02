"""Голосование по договору с альтернативами (B5.1; ТЗ §12.4 п.1, D-25, D-26;
решения D-B51-8, D-B51-9, D-B51-11).

- ``options``/``check_option``/``on_option`` — колбэки предмета
  ``bpp.agreement`` для вариантов голоса signoff. Выбирают этапы с признаком
  «Выбирает вариант» — ФД и ГД (``bpp_configure_routes``), решающий голос —
  последний из них. За альтернативу голосуют, пока она «Подано» и по
  бюджету проходит BR-093; голос записывается в «Историю изменений»
  договора — доменная запись голоса (D-26).
- ``preapproved_for`` — у нового договора по АП, выбранной голосованием,
  предсогласован этап того, кто решил (ГД); ФД проверяет новый договор своим
  этапом, ТД и ОД — обычным порядком (D-26).
- ``notify_voters`` — АП, поданное после голоса части согласующих: уже
  проголосовавшие получают уведомление (§12.4 п.1).

Модуль не импортирует сервисы договора и счёта (его зовут из них).
"""

from __future__ import annotations

import uuid

from django.db import transaction

from apps.bpp.models import Agreement, AlternativeOffer
from apps.bpp.services.alternatives import lifecycle
from apps.bpp.services.core import audit
from apps.core.services import ServiceDisabled
from apps.notifications import interface as notifications
from apps.signoff import interface as signoff
from htqweb.fallback import fallback
from htqweb.tenancy import current_company_or_none

from . import checks

SUBJECT = Agreement.SIGNOFF_SUBJECT_TYPE
AGREEMENT = lifecycle.SOURCE_AGREEMENT
PREAPPROVED_LABEL = "Согласовано при выборе альтернативы"
EVENT_VOTED_OFFER = "bpp.alternative_after_vote"


def _offer(option_key: str) -> AlternativeOffer | None:
    """АП по ключу варианта ``offer:<uuid>``; неверный ключ — ``None``."""
    if not isinstance(option_key, str) or not option_key.startswith(lifecycle.OFFER_PREFIX):
        return None
    try:
        key = uuid.UUID(option_key[len(lifecycle.OFFER_PREFIX):])
    except ValueError:
        return None
    return AlternativeOffer.objects.filter(pk=key).first()


# ── колбэки вариантов голоса (signoff.register_subject) ─────────────────

def options(subject_id) -> list[dict]:
    """Исходный договор и поданные к нему АП (``lifecycle.options_for``)."""
    return lifecycle.options_for(AGREEMENT, subject_id)


def check_option(subject_id, option_key: str) -> str | None:
    """``None`` — голос принимается; иначе причина (422 у движка): АП уже не
    «Подано» (``lifecycle.check_option``) или дороже, чем позволяет остаток
    статьи (BR-093 — на момент голоса)."""
    reason = lifecycle.check_option(AGREEMENT, subject_id, option_key)
    if reason or option_key == lifecycle.ORIGINAL:
        return reason
    offer = _offer(option_key)
    agr = Agreement.objects.filter(pk=subject_id).first()
    if offer is None or agr is None:
        return lifecycle.OPTION_GONE
    return checks.budget_reason(offer, project_id=agr.project_id, article_id=agr.article_id)


def on_option(subject_id, stage_order: int, user_id: int, option_key: str) -> None:
    """Голос — в «Историю изменений» договора (доменная запись, D-26)."""
    labels = {row["key"]: row["label"] for row in options(subject_id)}
    audit.record_for(Agreement._meta.label_lower, str(subject_id), "option_vote",
                     actor_id=user_id, changes={"stage": stage_order, "option": option_key,
                                                "label": labels.get(option_key, option_key)})


# ── новый договор по АП: предсогласование этапа решившего ───────────────

def preapproved_for(agr: Agreement) -> list[dict] | None:
    """D-26: новый договор по АП, выбранной голосованием, — этап решившего
    (ГД) предсогласован. ``None`` — договор не по такой АП или решающий голос
    отдан не через должность (этап «поимённо»: предсогласовать нечего)."""
    offer = checks.basis_offer(AGREEMENT, agr.pk)
    if offer is None or offer.source_type != AGREEMENT:
        return None
    key = f"{lifecycle.OFFER_PREFIX}{offer.pk}"
    final = signoff.final_option(SUBJECT, str(offer.source_id))
    if not final or final["key"] != key:
        return None
    process = signoff.get_process_for(SUBJECT, str(offer.source_id)) or {}
    for stage in reversed(process.get("stages", [])):
        for task in stage["tasks"]:
            if (task["user_id"] == final["actor_id"] and task.get("option_key") == key
                    and task.get("position_id")):
                return [{"position_id": task["position_id"], "actor_id": final["actor_id"],
                         "label": PREAPPROVED_LABEL}]
    return None


# ── АП после части голосов: уведомить проголосовавших ──────────────────

def notify_voters(offer: AlternativeOffer) -> None:
    """§12.4 п.1: АП подана, когда часть этапов договора уже проголосовала, —
    тем, кто голосовал, уведомление. Зовёт подача АП (``offers.submit``)."""
    if offer.source_type != AGREEMENT:
        return
    process = signoff.get_process_for(SUBJECT, str(offer.source_id))
    if not process or process.get("state") != "pending":
        return
    voters = {task["user_id"] for stage in process.get("stages", []) for task in stage["tasks"]
              if task["state"] == "approved" and task.get("option_key")}
    voters.discard(offer.author_id)
    company = current_company_or_none()
    if not voters or company is None:
        return
    agr = Agreement.objects.filter(pk=offer.source_id).first()
    number = agr.number if agr is not None else str(offer.source_id)
    try:
        with transaction.atomic():
            notifications.notify(
                recipients=sorted(voters), event=EVENT_VOTED_OFFER,
                title=f"К договору {number} после вашего голоса подана альтернатива "
                      f"{offer.number}", url=f"/bpp/agreements/{offer.source_id}",
                company_slug=company, target_type=offer._meta.label_lower,
                target_id=str(offer.pk), actor_id=offer.author_id, deliver=True)
    except ServiceDisabled as exc:
        fallback("bpp.selection.voters_notify_disabled", None, expected=True, exc=exc,
                 reason="центр уведомлений выключен — проголосовавшие не уведомлены",
                 offer=str(offer.pk))
    except Exception as exc:
        fallback("bpp.selection.voters_notify_failed", None, exc=exc,
                 reason="уведомление проголосовавшим о новой альтернативе не записано",
                 offer=str(offer.pk))
