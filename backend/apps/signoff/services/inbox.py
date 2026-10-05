"""«Ждёт меня» по всем компаниям пользователя (БЗО, B8.1).

Директора компаний группы — в штате холдинга, а документы дочерних
согласуются в схемах дочерних: задача директора лежит там, где документ.
Очередь текущей компании (``presentation.list_inbox``) поэтому показывала бы
директору только документы холдинга. Здесь та же выборка собирается по
всем компаниям, где у человека могут быть задачи:

* текущая компания запроса;
* компании, где у него есть членство (туда он может перейти сам);
* компании ниже текущей по дереву владения — задачи на должность холдинга
  ставятся и тем, у кого членства в дочерней пока нет (членство и права
  директоров в дочерних — задача A8.1).

Только действующие компании со схемой и включённым ``signoff``. Строка
дополняется компанией, признаком «можно перейти» (членство) и признаком
«можно решить прямо отсюда» (``direct.blocker``) с причиной, если нельзя.
"""

from __future__ import annotations

from apps.companies import interface as companies
from apps.core.services import service_enabled
from apps.signoff.models import ApprovalTask
from apps.signoff.services import direct, presentation
from htqweb.fallback import fallback
from htqweb.tenancy import current_company_or_none
from htqweb.tenancy.db import use_company


def companies_for(user_id: int, current: str | None) -> list[str]:
    """Компании, в которых у пользователя могут быть задачи: текущая первой,
    затем остальные по алфавиту."""
    candidates = [*companies.user_company_slugs(user_id),
                  *(companies.descendant_slugs(current) if current else [])]
    active = set(companies.active_company_slugs())
    rest = sorted({slug for slug in candidates if slug != current and slug in active})
    ordered = ([current] if current else []) + rest
    return [slug for slug in ordered if slug == current or companies.schema_exists(slug)]


def inbox_all(user_id: int) -> list[dict]:
    """Строки ``presentation.list_inbox`` по всем компаниям пользователя —
    с ``company``, ``can_enter``, ``direct_allowed`` и ``direct_blocker``.

    Без контекста компании (голый домен, служебный вызов) — очередь
    ``public``, как у ``tasks/mine``, без компании в строке.
    """
    current = current_company_or_none()
    if current is None:
        return [{**row, "company": None, "can_enter": True, "direct_allowed": False,
                 "direct_blocker": None, "process_path": _process_path(row)}
                for row in presentation.list_inbox(user_id)]

    members = set(companies.user_company_slugs(user_id))
    below = set(companies.descendant_slugs(current))
    out: list[dict] = []
    for slug in companies_for(user_id, current):
        try:
            rows = _company_rows(slug, user_id, check_direct=slug in below)
        except Exception as exc:
            # Сбой одной компании не должен прятать очередь остальных — её
            # задачи человек увидит, когда она поправится. Нет схемы или
            # выключенный signoff отсеяны выше; здесь — настоящий сбой, и в
            # dev/тестах он падает (``expected`` не ставится).
            fallback("signoff.inbox.company_failed", None,
                     reason="очередь компании не собралась", exc=exc, company=slug)
            continue
        card = direct.company_card(slug, current=current)
        for row in rows:
            row["company"] = card
            row["can_enter"] = slug == current or slug in members
            out.append(row)
    out.sort(key=lambda row: row["created_at"], reverse=True)
    return out


def _company_rows(slug: str, user_id: int, *, check_direct: bool) -> list[dict]:
    with use_company(slug):
        if not service_enabled("signoff"):
            return []
        rows = presentation.list_inbox(user_id)
        if not rows:
            return []
        tasks = {task.pk: task for task in ApprovalTask.objects
                 .select_related("stage", "stage__process")
                 .filter(pk__in=[row["task_id"] for row in rows])}
        for row in rows:
            row["process_path"] = _process_path(row)
            reason = (direct.blocker(tasks[row["task_id"]]) if check_direct
                      else None)
            row["direct_allowed"] = check_direct and reason is None
            row["direct_blocker"] = reason if check_direct else None
        return rows


def _process_path(row: dict) -> str:
    """Где решать на адресе компании задачи: карточка документа, а без неё —
    карточка процесса с кнопками решения."""
    return row.get("subject_url") or f"/signoff/processes/{row['process_id']}"
