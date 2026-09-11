"""Бизнес-метрики движка согласований.

Собирается по расписанию через ``apps.core.metrics`` — см. докстринг там.
Обращается только к своим моделям (правило изоляции аппок).

Согласование ломается тише всех остальных доменов: объект отправлен, круг
запущен, состояние «на согласовании» — и всё выглядит нормально ровно до
того момента, когда кто-нибудь спросит «а где мой договор?». Две причины
застревания принципиально разные, и метрики их разделяют:

* ``pending_stale`` — задачи выданы, но люди не решают;
* ``routes_without_approvers`` — задачи не выданы ВООБЩЕ и не будут, потому
  что у этапа «по должности» не назначено ни одной должности. Здесь ждать
  бесполезно: движок (``services/engine.py``) в этом случае поднимает
  ``RouteUnusable``, и объект не сдвинется никогда.

``matched_by="fallback"`` сюда сознательно не попал: запасной этап — штатная
ветка «иначе» в ветвлении маршрута (``ApprovalRouteStage.is_fallback``), она
срабатывает по проекту, и метрика была бы ненулевой всегда.
"""
from __future__ import annotations

from django.db.models import Count, Min
from django.utils import timezone

from .models import (
    ApprovalProcess,
    ApprovalRouteStage,
    ApproverKind,
    ProcessState,
)

# С какого возраста «на согласовании» считается застреванием. Трое суток —
# это уже «прошли выходные и ещё день», то есть не занятость, а забыли.
STALE_PENDING_DAYS = 3


def collect() -> dict:
    now = timezone.now()
    pending = ApprovalProcess.objects.filter(state=ProcessState.PENDING)

    # ── Распределение по состояниям ────────────────────────────────────────
    by_state = [((row["state"],), row["n"]) for row in
                ApprovalProcess.objects.values("state").annotate(n=Count("id"))]

    # ── Стоят дольше трёх суток, с разбивкой по типу объекта ───────────────
    # subject_type («contracts.agreement», «contracts.invoice», …) отвечает на
    # главный вопрос дежурного: жмёт весь движок или один вид документов.
    stale = [((row["subject_type"],), row["n"]) for row in
             pending.filter(updated_at__lt=now - timezone.timedelta(days=STALE_PENDING_DAYS))
             .values("subject_type").annotate(n=Count("id"))]

    # ── Этапы, которые некому согласовать ──────────────────────────────────
    # Этап «по должности» без единой строки в roles: движок не найдёт ни
    # одного исполнителя, задачи не создадутся, объект застрянет навсегда.
    # Ошибка конфигурации, а не нагрузки, — поэтому обязана быть нулём.
    dead_end = (ApprovalRouteStage.objects
                .filter(route__is_active=True,
                        approver_kind=ApproverKind.POSITION,
                        roles__isnull=True)
                .count())

    result = {
        "signoff_processes": {
            "help": "Процессы согласования по состояниям",
            "labels": ["state"],
            "values": by_state,
        },
        "signoff_pending_stale": {
            "help": ("Процессы без движения дольше %d суток"
                     % STALE_PENDING_DAYS),
            "labels": ["subject_type"],
            "values": stale,
        },
        "signoff_routes_without_approvers": {
            "help": "Этапы маршрутов «по должности» без назначенных должностей",
            "values": [((), dead_end)],
        },
    }

    # Возраст самого старого несогласованного. Условная метрика: пустая
    # очередь и «только что отправили» нулём выглядели бы одинаково, а
    # различать их важно — ноль здесь означал бы «всё согласовано мгновенно».
    oldest = pending.aggregate(first=Min("created_at"))["first"]
    if oldest is not None:
        result["signoff_oldest_pending_seconds"] = {
            "help": "Секунд с постановки самого старого несогласованного объекта",
            "values": [((), (now - oldest).total_seconds())],
        }
    return result
