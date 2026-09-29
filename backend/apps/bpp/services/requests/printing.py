"""Печать заявки на закупку с листом согласования (ТЗ §19, D-32; остаток B, B-3).

Вёрстка — общий шаблон модуля (``services/core/printing.py``, A2.2) плюс свой
блок ``body`` в ``bpp/print/purchase_request.html``: шапка заявки (проект,
статья, тип закупки, обоснование) и таблица позиций. Лист согласования —
решения последнего процесса ``signoff`` по заявке: кто, когда и с каким
комментарием; задачи, ещё ждущие решения, в лист не попадают — на бумаге
остаётся только принятое.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from django.conf import settings

from apps.bpp.models import PurchaseRequest
from apps.bpp.services.money import fmt
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff
from apps.users import interface as users

TEMPLATE = "bpp/print/purchase_request.html"
SUBJECT = PurchaseRequest.SIGNOFF_SUBJECT_TYPE

#: Решение задачи согласования человеком (``signoff.TaskState``).
DECISIONS = {"approved": "Согласовано", "rejected": "Отклонено",
             "rework": "Возвращено на доработку"}


def _date(value) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _moment(value) -> str:
    if not value:
        return ""
    return value.astimezone(ZoneInfo(settings.PLATFORM_TIME_ZONE)).strftime("%d.%m.%Y %H:%M")


def _qty(value) -> str:
    text = f"{value.normalize():f}" if value == value.to_integral() else f"{value:f}".rstrip("0")
    return text.replace(".", ",")


def signoff_stages(req: PurchaseRequest) -> list[dict]:
    process = signoff.get_process_for(SUBJECT, str(req.pk))
    if process is None:
        return []
    decided = [(stage, task) for stage in process["stages"] for task in stage["tasks"]
               if task["state"] in DECISIONS]
    names = {row["id"]: row["full_name"]
             for row in users.get_users_brief(list({t["user_id"] for _, t in decided}))}
    return [{"title": stage["name"], "actor_name": names.get(task["user_id"], ""),
             "decision": DECISIONS[task["state"]], "comment": task["comment"] or "",
             "decided_at": _moment(task["acted_at"])}
            for stage, task in sorted(decided, key=lambda pair: pair[1]["acted_at"])]


def context(req: PurchaseRequest) -> dict:
    items = list(req.items.order_by("line_no"))
    uoms = refdata.uom_brief(list({str(item.uom_id) for item in items}))
    project = projects.project_brief([str(req.project_id)]).get(str(req.project_id)) or {}
    article = (refdata.article_brief([str(req.article_id)]).get(str(req.article_id)) or {}
               if req.article_id else {})
    author = users.get_users_brief([req.author_id])
    return {
        "document_title": "Заявка на закупку",
        "number": req.number,
        "status_label": req.get_status_display(),
        "author_name": author[0]["full_name"] if author else "",
        "created_at": _date(req.created_at),
        "project": " — ".join(filter(None, (project.get("code"), project.get("name")))),
        "article": article.get("name", ""),
        "purchase_type": req.get_purchase_type_display(),
        "need_date": _date(req.need_date),
        "justification": req.justification,
        "table": {
            "columns": ["№", "Наименование", "Ед.", "Кол-во", "Цена", "Сумма",
                        "Дата потребности"],
            "rows": [[item.sys_number, item.name,
                      uoms.get(str(item.uom_id), {}).get("short_name", ""), _qty(item.qty),
                      fmt(item.price, None), fmt(item.amount, None), _date(item.need_date)]
                     for item in items],
            "total": ["", "Итого", "", "", "", fmt(req.total_amount, req.currency_code), ""],
        },
        "signoff_stages": signoff_stages(req),
    }
