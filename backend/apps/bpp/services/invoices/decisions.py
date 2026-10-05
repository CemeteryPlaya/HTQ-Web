"""Решение ФД по счёту — одноэтапный маршрут ``signoff`` (D-12; ТЗ §10.4).

- «Оплатить» (``approve``) — в одной транзакции: блокировка строки бюджета →
  проверка «на текущий момент» (§26.2) → плановая дата оплаты → решение
  ``signoff``. Этап ФД несёт ``requirement_key="bpp:budget"``, поэтому та же
  проверка стоит и на «Согласовать» из общего инбокса.
- «Не оплачивать» (``reject``) и «Вернуть» (``rework``) — комментарий ≥ 10
  символов (BR-060).
- Массовое решение — каждый счёт в своей транзакции, ответ — успехи и отказы
  с причинами (§10.5). Повтор с тем же ключом (AC-013) отдаёт ручка по
  ``Idempotency-Key``, а движок второй раз ту же задачу не закроет.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.bpp.models import Invoice, InvoiceStatus
from apps.bpp.services.actor import Actor
from apps.bpp.services.alternatives import kpi
from apps.bpp.services.core import audit
from apps.signoff import interface as signoff
from htqweb.errors import DomainError

from . import invoices as service

DECISIONS = {"pay": "approve", "not_payable": "reject", "return": "rework"}


def _task_of(inv: Invoice, user_id: int) -> int:
    process = signoff.get_process_for(service.SUBJECT, str(inv.pk))
    for stage in (process or {}).get("stages", []):
        for task in stage["tasks"]:
            if task["user_id"] == user_id and task["state"] == "pending":
                return task["id"]
    raise DomainError("E-ACC-01", f"Решение по счёту {inv.number} ждёт не вас. Если это "
                                  f"ошибка, обратитесь к администратору.", status=403)


@transaction.atomic
def decide(actor: Actor, invoice_id, *, decision: str, planned_pay_date: date | None = None,
           comment: str = "") -> Invoice:
    if not actor.can("bpp.invoices.decision", "edit"):
        raise service._deny("Решение по счёту принимает финансовый директор.")
    if decision not in DECISIONS:
        raise DomainError("E-VAL-01", "Неизвестное решение.",
                          fields=[{"field": "decision", "message": "pay, not_payable, return"}])
    inv = service.lock(invoice_id)
    service.require_status(inv, (InvoiceStatus.UNDER_REVIEW,), "принять решение по")
    if decision != "pay":
        comment = service.comment_of(comment)
    else:
        today = timezone.localdate()
        if planned_pay_date and planned_pay_date < today:
            raise DomainError("E-VAL-01", "Плановая дата оплаты — не раньше сегодняшней.",
                              fields=[{"field": "planned_pay_date", "message": "≥ сегодня"}])
        service.check_budget(inv, include_self=True)
        inv.planned_pay_date = planned_pay_date or inv.due_date
        inv.save(update_fields=["planned_pay_date"])
    task_id = _task_of(inv, actor.user_id)
    result = signoff.decide_many(actor_id=actor.user_id, items=[
        {"task_id": task_id, "decision": DECISIONS[decision], "comment": comment}])[0]
    if not result.get("ok"):
        raise DomainError("E-SGN-01", result.get("error") or "Решение не принято.", status=409)
    inv.refresh_from_db()
    service.touch(inv, actor.user_id)
    audit.record(inv, f"fd_{decision}", actor_id=actor.user_id, comment=comment,
                 changes={"planned_pay_date": inv.planned_pay_date.isoformat()
                          if inv.planned_pay_date else None})
    kpi.sync_for_document("invoice", inv.pk)  # «Не к оплате» аннулирует KPI (A5.2)
    return inv


def decide_batch(actor: Actor, invoice_ids: list[str], *, decision: str,
                 comment: str = "", planned_pay_date: date | None = None) -> dict:
    """«Оплатить отмеченные» / «Не оплачивать отмеченные» (ТЗ §10.5): каждый
    счёт отдельно, в своей транзакции; ответ — ``{ok: [id], failed: [{id,
    reason}]}``."""
    ok, failed = [], []
    for invoice_id in invoice_ids:
        try:
            decide(actor, invoice_id, decision=decision, comment=comment,
                   planned_pay_date=planned_pay_date)
            ok.append(str(invoice_id))
        except DomainError as exc:
            failed.append({"id": str(invoice_id), "reason": exc.message})
    return {"ok": ok, "failed": failed}
