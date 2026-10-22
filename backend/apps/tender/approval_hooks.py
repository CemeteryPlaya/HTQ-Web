"""Предмет согласования «Выбор поставщиков» ``tender.award`` (T5.2; спека этапа
5, §3 T5.2; мастер-план T-11).

Маршрут — «Проверка качества → ФД» (``tender_configure_route``). Исполнителя
первого этапа называет сам тендер (``approver_kind="subject"``, ключ
``quality_reviewer``): назначенный закупщиком пользователь с ролью
``tender-quality`` — иначе держатели должности «Технический директор» своей
компании, а если её нет — ближайшей вышестоящей (директора — в штате
холдинга, B8.1). Правок signoff не требуется.

Колбэки движка — в его транзакции:

- старт → «На утверждении»;
- утверждение → «Выбор утверждён»; приглашения победителей — «Победитель»,
  прочих подавших — «Не выбран»; событие ``award_approved`` в журнале (письма
  итога — outbox этапа 4, S5-17);
- возврат и отклонение → «Возвращён на доработку» с комментарием решения
  (S5-09); отзыв процесса → снова «Вскрыт».
"""

from __future__ import annotations

from apps.companies import interface as companies
from apps.hr import interface as hr
from apps.signoff import interface as signoff
from apps.tender.models import Award, Invitation, InvitationStatus, Tender, TenderStatus
from apps.tender.services.core import audit
from htqweb.tenancy import current_company_or_none
from htqweb.tenancy.db import use_company

SUBJECT = Tender.SIGNOFF_SUBJECT_TYPE
REVIEWER_KEY = "quality_reviewer"
TD_TITLE = "Технический директор"


def _approver_fields(scope: str = "") -> list[dict]:
    return [{"key": REVIEWER_KEY, "label": "Проверяющий качество тендера"}]


def td_holders() -> list[int]:
    """Держатели должности «Технический директор» — своей компании, иначе
    ближайшей вышестоящей."""
    found = hr.positions_by_title([TD_TITLE]).get(TD_TITLE)
    if found:
        return hr.resolve_position_users([found]).get(found, [])
    company = current_company_or_none()
    for upper in companies.ancestor_slugs(company) if company else []:
        with use_company(upper):
            found = hr.positions_by_title([TD_TITLE]).get(TD_TITLE)
            if found:
                return hr.resolve_position_users([found]).get(found, [])
    return []


def _approvers(subject_id, key: str) -> list[int]:
    if key != REVIEWER_KEY:
        return []
    tender = Tender.objects.filter(pk=subject_id).first()
    if tender is None:
        return []
    if tender.quality_reviewer_user_id:
        return [tender.quality_reviewer_user_id]
    return td_holders()


def _set_status(subject_id, status: str, *, comment: str | None = None) -> Tender:
    tender = Tender.objects.select_for_update().get(pk=subject_id)
    tender.status = status
    if comment is not None:
        tender.status_comment = comment
    tender.version += 1
    tender.save()
    return tender


def _last_comment(subject_id) -> str:
    """Комментарий того, кто вернул или отклонил — последнее непустое решение."""
    process = signoff.get_process_for(SUBJECT, str(subject_id))
    comments = [t.get("comment") for st in (process or {}).get("stages", [])
                for t in st["tasks"] if t.get("comment")]
    return comments[-1] if comments else ""


def on_started(subject_id) -> None:
    tender = _set_status(subject_id, TenderStatus.ON_APPROVAL, comment="")
    audit.record(tender, "award_submitted", actor_id=tender.author_id)


def on_approved(subject_id) -> None:
    tender = _set_status(subject_id, TenderStatus.AWARDED)
    winners = set(Award.objects.filter(tender=tender)
                  .values_list("offer__invitation_id", flat=True))
    Invitation.objects.filter(tender=tender, pk__in=winners).update(
        status=InvitationStatus.AWARDED)
    Invitation.objects.filter(tender=tender, status=InvitationStatus.SUBMITTED).exclude(
        pk__in=winners).update(status=InvitationStatus.NOT_AWARDED)
    # Письма итога победителям и не выбранным — outbox этапа 4 (S5-17).
    audit.record(tender, "award_approved", actor_id=None,
                 changes={"winners": len(winners)})


def on_returned(subject_id) -> None:
    tender = _set_status(subject_id, TenderStatus.REWORK, comment=_last_comment(subject_id))
    audit.record(tender, "award_returned", actor_id=None, comment=tender.status_comment)


def on_cancelled(subject_id) -> None:
    tender = _set_status(subject_id, TenderStatus.OPENED)
    audit.record(tender, "award_cancelled", actor_id=None)


def _describe(subject_id) -> dict | None:
    tender = Tender.objects.select_related("request").filter(pk=subject_id).first()
    if tender is None:
        return None
    return {"title": f"Выбор поставщиков по тендеру {tender.number} "
                     f"(заявка {tender.request.number})",
            "url": f"/tender/tenders/{tender.pk}"}


def _money(value) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₸"


def _summary(subject_id) -> dict | None:
    """Поставщики и суммы выбора — для «Ждёт меня» и решения из холдинга."""
    tender = Tender.objects.select_related("request").filter(pk=subject_id).first()
    if tender is None:
        return None
    totals: dict[str, object] = {}
    for award in Award.objects.filter(tender=tender).select_related("offer__invitation"):
        name = award.offer.invitation.name
        totals[name] = totals.get(name, 0) + (award.amount_kzt or 0)
    return {
        "fields": [{"label": "Тендер", "value": tender.number},
                   {"label": "Заявка", "value": tender.request.number},
                   {"label": "Комментарий выбора", "value": tender.award_comment or "—"}],
        "lines": {"columns": [{"key": "supplier", "label": "Поставщик"},
                              {"key": "amount", "label": "Сумма, KZT", "align": "right"}],
                  "rows": [{"supplier": name, "amount": _money(amount)}
                           for name, amount in totals.items()],
                  "total": {"label": "Итого", "value": _money(sum(totals.values()))}},
    }


def register() -> None:
    signoff.register_subject(
        SUBJECT, label="Выбор поставщиков (тендер)", model=Tender,
        approvers=_approvers, approver_fields=_approver_fields,
        on_started=on_started, on_approved=on_approved, on_rejected=on_returned,
        on_rework=on_returned, on_cancelled=on_cancelled,
        describe=_describe, summary=_summary)
