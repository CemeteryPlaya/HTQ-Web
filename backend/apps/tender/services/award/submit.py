"""Отправка выбора на утверждение (T5.2; спека этапа 5, §3 T5.2; T-12, T-13).

Перед стартом маршрута ``tender.award``:

- выбор не пуст;
- у каждой строки есть сумма в KZT (курс на дату вскрытия) — иначе 422
  ``E-TND-10``: ФД утверждает рубли, а не «сумму в валюте без курса»;
- **бюджет (T-13, ответ ФД 20.10 — блок):** по каждой статье выбор сверх
  плана её частей должен уложиться в свободный остаток статьи
  (``bpp.budget_available``); в пределах плана проверять нечего — план уже
  в резерве ЗЗ. Иначе 422 ``E-TND-11`` с дефицитом по статьям.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.bpp import interface as bpp
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff
from apps.tender.services.core.errors import check_version
from apps.tender.services.tenders import tenders
from apps.tender.services.tenders.ctx import Ctx
from htqweb.errors import DomainError

from . import selection

ZERO = Decimal("0")


def deficits(tender, awards) -> list[dict]:
    """Дефицит по статьям: ``[{article_id, article_code, over, available}]``."""
    plans = selection.plans_by_part(tender)
    by_article: dict[str, dict] = {}
    for key, row in plans.items():
        article = str(row["part"].article_id)
        slot = by_article.setdefault(article, {"plan": ZERO, "awarded": ZERO})
        slot["plan"] += row["plan"]
        slot["awarded"] += sum((a.amount_kzt or ZERO) for a in awards if str(a.part_id) == key)
    req = tender.request
    actor = bpp.TenderActor(user_id=tender.author_id)
    out = []
    for article, slot in by_article.items():
        over = slot["awarded"] - slot["plan"]
        if over <= 0:
            continue
        figures = bpp.budget_available(str(req.project_id), article, actor=actor,
                                       role=req.initiator_role)
        if over > figures.available:
            code = (refdata.article_brief([article]).get(article) or {}).get("code", "")
            out.append({"article_id": article, "article_code": code, "over": str(over),
                        "available": str(figures.available)})
    return out


@transaction.atomic
def submit(ctx: Ctx, tender_id, *, expected_version: int | None) -> dict:
    tender = tenders.get_own(ctx, tender_id, "Отправлять на утверждение")
    if tender.status not in selection.EDITABLE:
        raise tenders.state_error("отправить выбор по тендеру", tender)
    check_version(tender, expected_version)
    awards = list(tender.awards.select_related("offer__invitation"))
    if not awards:
        raise DomainError("E-VAL-01", "Выберите поставщиков хотя бы по одной позиции.",
                          fields=[{"field": "lines", "message": "Нет выбора"}])
    no_rate = sorted({a.offer.invitation.name for a in awards if a.amount_kzt is None})
    if no_rate:
        raise DomainError(
            "E-TND-10", f"Нет курса валюты на дату вскрытия у поставщиков: {', '.join(no_rate)}"
                        f" — сумму в тенге не посчитать. Обратитесь к администратору "
                        f"справочника курсов.", details={"suppliers": no_rate})
    short = deficits(tender, awards)
    if short:
        raise DomainError(
            "E-TND-11", "Выбор дороже плана сверх свободного остатка бюджета статьи — "
                        "утвердить его нельзя. Пересмотрите выбор или попросите ФД "
                        "увеличить лимит статьи.", details={"deficits": short})
    try:
        signoff.start_process(subject_type=tender.SIGNOFF_SUBJECT_TYPE,
                              subject_id=str(tender.pk), initiator_id=tender.author_id)
    except signoff.RouteNotConfigured as exc:
        raise DomainError("E-SGN-01", "Маршрут утверждения выбора поставщиков не настроен — "
                                      "обратитесь к администратору.", status=409) from exc
    except signoff.SignoffError as exc:
        raise DomainError("E-SGN-01", str(exc), status=409) from exc
    tender.refresh_from_db()
    return selection.view_of(ctx, tender)
