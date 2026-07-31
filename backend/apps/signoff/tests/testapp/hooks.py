"""Регистрация тестовой модели в signoff — образец того, что напишет
предметная аппка (``apps/contracts/approval_hooks.py`` в фазе 3).

``CALLS`` — журнал вызовов колбэков. По нему тесты проверяют главное
свойство движка: колбэк результата вызывается РОВНО ОДИН РАЗ, даже когда
последний параллельный этап закрывают одновременно.
"""

from __future__ import annotations

from apps.signoff import interface as signoff

from .models import ProbeDoc

CALLS: list[tuple[str, int]] = []


def reset() -> None:
    CALLS.clear()


def _on_started(subject_id: int) -> None:
    CALLS.append(("started", subject_id))


def _on_approved(subject_id: int) -> None:
    CALLS.append(("approved", subject_id))
    # Доменное последствие, отдельное от approval_state: его signoff ведёт
    # сам, а вот «опубликовать документ» — дело предметной аппки.
    ProbeDoc.objects.filter(pk=subject_id).update(published=True)


def _on_rejected(subject_id: int) -> None:
    CALLS.append(("rejected", subject_id))


def _on_rework(subject_id: int) -> None:
    # Снятие с публикации — доменное последствие возврата на доработку: тот
    # же смысл, что у ``_on_approved`` наоборот. Приходит сюда документ и с
    # решения согласующего, и с ``engine.reopen`` уже согласованного, где
    # ``published`` как раз и стоит.
    CALLS.append(("rework", subject_id))
    ProbeDoc.objects.filter(pk=subject_id).update(published=False)


def _on_cancelled(subject_id: int) -> None:
    CALLS.append(("cancelled", subject_id))


def _describe(subject_id: int) -> dict | None:
    doc = ProbeDoc.objects.filter(pk=subject_id).first()
    if doc is None:
        return None
    return {"title": doc.title, "url": f"/probe/{doc.pk}"}


# ``ZONES`` играет роль справочника из БД (у contracts это таблица стран):
# ``fact_fields`` обязана быть функцией именно потому, что такой справочник
# меняется без перезапуска.
ZONES = [(1, "Первая зона"), (2, "Вторая зона"), (3, "Третья зона")]


def _facts(subject_id: int) -> dict:
    doc = ProbeDoc.objects.filter(pk=subject_id).first()
    if doc is None:
        return {}
    return {"zone": doc.zone, "amount": doc.amount, "urgent": doc.urgent}


def _fact_fields() -> list[dict]:
    return [
        {"key": "zone", "label": "Зона", "type": "choice",
         "options": [{"value": value, "label": label} for value, label in ZONES]},
        {"key": "amount", "label": "Сумма", "type": "number"},
        {"key": "urgent", "label": "Срочно", "type": "bool"},
    ]


def register() -> None:
    signoff.register_subject(
        ProbeDoc.SIGNOFF_SUBJECT_TYPE,
        label="Пробный документ",
        model=ProbeDoc,
        on_started=_on_started,
        on_approved=_on_approved,
        on_rejected=_on_rejected,
        on_rework=_on_rework,
        on_cancelled=_on_cancelled,
        describe=_describe,
        facts=_facts,
        fact_fields=_fact_fields,
    )
