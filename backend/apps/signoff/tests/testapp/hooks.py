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


def _on_cancelled(subject_id: int) -> None:
    CALLS.append(("cancelled", subject_id))


def _describe(subject_id: int) -> dict | None:
    doc = ProbeDoc.objects.filter(pk=subject_id).first()
    if doc is None:
        return None
    return {"title": doc.title, "url": f"/probe/{doc.pk}"}


def register() -> None:
    signoff.register_subject(
        ProbeDoc.SIGNOFF_SUBJECT_TYPE,
        label="Пробный документ",
        model=ProbeDoc,
        on_started=_on_started,
        on_approved=_on_approved,
        on_rejected=_on_rejected,
        on_cancelled=_on_cancelled,
        describe=_describe,
    )
