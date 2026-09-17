"""Отправка заявки на согласование.

Когда-то здесь жил собственный движок графов (``workflow_json`` → узлы →
``ApprovalAction``): решения, продвижение, отзыв, recall. С переездом
согласования в ``apps.signoff`` от него остался ровно один переход —
«черновик → на согласовании»: проверить заполненную форму и запустить
процесс движка. Всё, что происходит дальше (решения, доработка, отзыв),
делает signoff, а обратно в заявку результат приходит колбэками
``apps/approvals/approval_hooks.py``, которые и двигают её ``status``.

Ошибки по-прежнему поднимаются как ``RuntimeConflict`` / ``RuntimeRejected``
/ ``Forbidden`` и переводятся вьюхой в 409 / 422 / 403 — HTTP здесь не
появляется, чтобы функции можно было звать и из команд.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.signoff import interface as signoff

from ..models import RequestActivity, RequestFormTemplateVersion, RequestInstance, RequestStatus
from .budget_line_refs import validate_budget_line_refs
from .value_validation import compute_total, validate_values

logger = logging.getLogger(__name__)


class RuntimeConflict(Exception):
    """The request is not in a state where this operation makes sense (409)."""


class RuntimeRejected(Exception):
    """The operation is well-formed but cannot be carried out (422)."""


class Forbidden(Exception):
    """The caller is not allowed to do this (403)."""


def log(instance: RequestInstance, event_type: str, actor_id: int | None,
        payload: dict | None = None) -> None:
    RequestActivity.objects.create(request=instance, event_type=event_type,
                                   actor_id=actor_id, payload=payload)


def next_code(template) -> str:
    """``REQ-<slug>-<year>-0001`` — per-template, per-year running number."""
    year = timezone.now().year
    prefix = f"REQ-{template.slug}-{year}-"
    n = RequestInstance.objects.filter(template=template,
                                       code__startswith=prefix).count() + 1
    return f"{prefix}{n:04d}"


def _load_version(version_id: int) -> RequestFormTemplateVersion:
    version = RequestFormTemplateVersion.objects.filter(pk=version_id).first()
    if version is None:
        raise RuntimeConflict("template version not found")
    return version


def submit(instance: RequestInstance, *, actor_id: int) -> dict:
    """Проверить форму и запустить согласование в signoff; вернуть КАРТОЧКУ
    ПРОЦЕССА — тот же контракт, что у ``submit`` в contracts.

    Проверки — ДО запуска, и все три «свои»: значения против схемы, ссылки на
    строки бюджета против contracts (``ServiceDisabled`` не глушится — см.
    ``budget_line_refs``), итоговая сумма. Дальше — ``signoff.start_process``:
    маршрут берётся по области шаблона (``approval_hooks._scope_of``),
    ``on_started`` переводит заявку в ``pending`` внутри транзакции движка.

    Ошибки движка (нет маршрута, уже на согласовании, маршрут неисполним) —
    409 с текстом самого движка: он называет и объект, и причину.
    """
    if instance.status not in (RequestStatus.DRAFT, RequestStatus.RETURNED):
        raise RuntimeConflict(
            f"cannot submit from status '{instance.status}'")
    version = _load_version(instance.template_version_id)
    values = instance.form_values_json or {}
    try:
        validate_values(version.schema_json, values)
        validate_budget_line_refs(version.schema_json, values)
        instance.total_amount = compute_total(version.schema_json, values)
    except ValueError as exc:
        raise RuntimeRejected(str(exc))
    instance.save(update_fields=["total_amount", "updated_at"])

    try:
        return signoff.start_process(
            subject_type=RequestInstance.SIGNOFF_SUBJECT_TYPE,
            subject_id=instance.pk, initiator_id=actor_id, enrich=True,
        )
    except signoff.SignoffError as exc:
        raise RuntimeConflict(str(exc)) from exc
