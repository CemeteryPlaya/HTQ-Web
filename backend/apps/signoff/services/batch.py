"""Массовое решение (мастер-план БЗО, B1.3; ТЗ: «Согласовать отмеченные»,
«Оплатить отмеченные»; ответ Q-C13).

Поштучно и без общей транзакции: каждый элемент — свой вызов
``engine.act`` в своей транзакции, и отказ по одному (уже решено, не ваш,
короткий комментарий, не выбран вариант) не откатывает остальные. У
каждого элемента — свой комментарий и свой вариант голоса: массовое
решение не угадывает ни того, ни другого.
"""

from __future__ import annotations

from django.http import Http404

from apps.signoff.services import engine
from apps.signoff.services.engine import SignoffError
from apps.signoff.services.registry import UnknownSubject
from apps.signoff.services.route_service import RouteConflict

#: То, что поштучное решение переводит в отказ элемента, а не в 500 всей пачки.
_ITEM_ERRORS = (Http404, SignoffError, UnknownSubject, RouteConflict)


def decide_many(*, actor_id: int, items: list[dict]) -> list[dict]:
    """``items`` — ``[{task_id, decision, comment?, option_key?}]`` →
    ``[{task_id, ok, error?}]`` в том же порядке."""
    results: list[dict] = []
    for item in items:
        task_id = int(item["task_id"])
        try:
            engine.act(task_id=task_id, actor_id=actor_id,
                       decision=item["decision"],
                       comment=item.get("comment") or "",
                       option_key=item.get("option_key") or "")
            results.append({"task_id": task_id, "ok": True})
        except _ITEM_ERRORS as exc:
            results.append({"task_id": task_id, "ok": False, "error": str(exc)})
    return results
