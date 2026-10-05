"""Договор глазами соседа — для привлечения партнёра ``tasks`` (хвост этапа 6, M-5).

Наружу идёт минимум: ``id, number, status, counterparty_id`` — сумм, позиций и
проекта сосед не получает. Поиск уважает права пользователя на договоры по
правилу карточки ``agreements.can_view``: «все договоры» — по узлу
``bpp.agreements.all``, СН и ПМ — свои проекты и группы статей, автор — свои,
согласующий — то, что согласовывал. Нет права на узел ``bpp.agreements`` (и
«все» тоже) — пусто, даже автору и согласующему.

Правило то же, что у ``can_view``, но считается пачкой (этап 8, D-S8-3): статьи
кандидатов — одним ``refdata.article_brief``, участие в согласовании — одной
``signoff.participant_subject_ids`` и только для тех, кого не открыли автор и
проект со статьёй. Число запросов не зависит от числа договоров; если
согласование не понадобилось (ФД, автор), выключенный ``signoff`` поиску не
мешает.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from django.db.models import Q

from apps.bpp.models import Agreement, AgreementStatus
from apps.bpp.services.actor import Actor
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff

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


def _may_search(actor: Actor) -> bool:
    """Внешний гейт соседа: право на узел договоров или «все договоры».
    Автору и согласующему без роли в модуле сосед договоры не показывает."""
    return service.sees_all(actor) or actor.can("bpp.agreements", "view")


def _visible(actor: Actor, rows: list[Agreement]) -> list[Agreement]:
    """Те из ``rows`` (порядок сохраняется), что открыл бы ``service.can_view``,
    — без запроса на строку."""
    if service.sees_all(actor):
        return rows
    scoped = actor.can("bpp.agreements", "view")
    seen = {agr.pk for agr in rows if agr.author_id == actor.user_id}
    # Свои договоры ``can_view`` открывает раньше и в ``refdata`` не ходит.
    in_projects = [agr for agr in rows
                   if agr.pk not in seen and scoped and actor.sees_project(agr.project_id)]
    articles = (refdata.article_brief(sorted({str(agr.article_id) for agr in in_projects}))
                if in_projects else {})
    seen |= {agr.pk for agr in in_projects
             if actor.sees_article(articles.get(str(agr.article_id)))}
    rest = [str(agr.pk) for agr in rows if agr.pk not in seen]
    if rest:
        # Согласующий видит то, что согласует, — как в ``can_view``.
        approved = signoff.participant_subject_ids(actor.user_id, service.SUBJECT, rest)
        seen |= {agr.pk for agr in rows if str(agr.pk) in approved}
    return [agr for agr in rows if agr.pk in seen]


def visible_brief(ids, *, token, company: str | None) -> dict[str, dict]:
    """Как ``brief``, но только договоры, которые ``token`` вправе видеть
    (``can_view``, как в карточке). Невидимый отвечает так же, как
    несуществующий: по ответу нельзя узнать, что договор есть."""
    keys = set()
    for raw in ids:
        try:
            keys.add(uuid.UUID(str(raw)))
        except ValueError:
            continue
    if not keys:
        return {}
    rows = list(Agreement.objects.filter(pk__in=keys))
    if not rows:
        return {}
    actor = _actor(token, company)
    if not _may_search(actor):
        return {}
    return {str(agr.pk): _card(agr) for agr in _visible(actor, rows)}


def search(query: str | None, *, counterparty_id, token, company: str | None,
           limit: int = 20) -> list[dict]:
    """Договоры контрагента, годные для привлечения, — для выбора в чужой форме.

    Номер, номер по документу или наименование от 2 символов. Права
    пользователя — как в карточке договора (см. докстринг модуля); порядок —
    новые первыми (``-created_at``, при равенстве — ``pk``), в ответе — первые
    ``limit`` видимых.

    Участие в согласовании проверяется по всем кандидатам, которых не открыли
    автор и проект со статьёй, поэтому при выключенном ``signoff`` поиск СН и
    ПМ может ответить 503 (``ServiceDisabled``; прежний поиск — только если до
    лимита попадался договор, видимый лишь как участнику), а поиск ФД («все
    договоры») и автора, видящего всех кандидатов сам, работает."""
    try:
        counterparty = uuid.UUID(str(counterparty_id))
    except ValueError:
        return []
    actor = _actor(token, company)
    if not _may_search(actor):
        return []
    rows = Agreement.objects.filter(counterparty_id=counterparty,
                                    status__in=USABLE_STATUSES,
                                    parent_agreement__isnull=True)
    text = (query or "").strip()
    if len(text) >= 2:
        rows = rows.filter(Q(number__icontains=text) | Q(ext_number__icontains=text)
                           | Q(name__icontains=text))
    rows = rows.order_by("-created_at", "pk")
    if limit <= 0:
        return []
    # «Все договоры» — без проверок по строкам: лимит прямо в запросе.
    candidates = list(rows[:limit] if service.sees_all(actor) else rows)
    return [{**_card(agr), "name": agr.name, "ext_number": agr.ext_number,
             "ext_date": agr.ext_date}
            for agr in _visible(actor, candidates)[:limit]]
