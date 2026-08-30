"""Кадровая правка идентичности → заявка к владельцу (спека §9).

Ключевое решение: заявка ЗАМЕНЯЕТ запись, а не сопровождает её. Если бы
значение сначала легло в копию, копия разъехалась бы с аккаунтом ровно на то
время, пока заявка ждёт подтверждения, — то есть ровно то состояние, которое
вся эта машинерия и должна устранять.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.hr.models import (
    Employee, IdentityApprover, IdentityChangeRequest, IdentityChangeRequestField,
)
from apps.hr.services import identity_sync_service
from apps.hr.services.identity_fields import FIELD_MAP, SYNCABLE, differs
from apps.users import interface as users_interface
from htqweb.fallback import fallback


class RequestNotFound(Exception):
    """404 — заявки с таким id нет."""


class RequestClosed(Exception):
    """409 — по заявке уже принято решение."""


class IncompleteDecision(Exception):
    """422 — решены не все строки заявки."""


class NotApprover(Exception):
    """403 — вызывающий не подтверждающий и не админ платформы."""


# ── создание заявки ─────────────────────────────────────────────────────────

def capture(employee: Employee, patch: dict, *, actor_id: int | None,
            source: str = IdentityChangeRequest.Source.HR_FORM,
            ) -> tuple[dict, IdentityChangeRequest | None]:
    """Вынуть из патча поля идентичности и оформить их заявкой.

    Возвращает ``(остаток_патча, заявка|None)``. Остаток — трудовые поля
    (отдел, должность, даты, статус): они целиком кадровые, владельца на
    стороне аккаунта у них нет, и применяются немедленно.

    У «скелета» без ``user_id`` владельца не существует вовсе — патч
    возвращается нетронутым и пишется напрямую (спека §3).
    """
    if not employee.user_id:
        return patch, None

    identity = {field: patch[field] for field in SYNCABLE if field in patch}
    rest = {key: value for key, value in patch.items() if key not in identity}
    if not identity:
        return rest, None

    snapshot = identity_sync_service.account_snapshot(employee.user_id) or {}
    proposals = {
        field: value for field, value in identity.items()
        if differs(field, value, snapshot.get(field))
    }
    if not proposals:
        # Просят ровно то, что уже стоит в аккаунте — беспокоить некого.
        return rest, None

    request, _ = IdentityChangeRequest.objects.get_or_create(
        employee=employee, status=IdentityChangeRequest.Status.PENDING,
        defaults={
            "user_id": employee.user_id,
            "created_by": actor_id,
            "source": source,
        },
    )
    for field, value in proposals.items():
        IdentityChangeRequestField.objects.update_or_create(
            request=request, field=field,
            defaults={
                "proposed_value": value,
                "account_value_at_request": snapshot.get(field) or "",
                # Повторная правка того же поля сбрасывает прежнее решение:
                # подтверждают конкретное значение, а не сам факт строки.
                "decision": None,
            },
        )

    notify_approver(request, "hr.identity_request" if source == IdentityChangeRequest.Source.HR_FORM
                    else "hr.identity_drift")
    return rest, request


def supersede(employee: Employee, fields: set[str], *, actor_id: int | None) -> None:
    """Снять из ожидающей заявки поля, которые кадры записали напрямую.

    Нужна праву ``hr.identity.force``. Без неё в очереди осталась бы заявка,
    предлагающая ЗНАЧЕНИЕ, которое уже перезаписано: подтвердивший её владелец
    вернул бы старое поверх нового, ничего при этом не нарушив — с его стороны
    всё выглядело бы штатно.

    Заявка без строк закрывается как ``rejected``: предложение действительно не
    будет применено. ``applied`` было бы неправдой — владелец ничего не
    подтверждал, а записанное значение может отличаться от предложенного.
    """
    request = (IdentityChangeRequest.objects
               .filter(employee=employee, status=IdentityChangeRequest.Status.PENDING)
               .first())
    if request is None:
        return

    request.fields.filter(field__in=fields).delete()
    if request.fields.exists():
        return

    request.status = IdentityChangeRequest.Status.REJECTED
    request.decided_by = actor_id
    request.decided_at = timezone.now()
    request.decision_note = (
        "Снята автоматически: кадры записали значения напрямую "
        "(право hr.identity.force)."
    )
    request.save(update_fields=["status", "decided_by", "decided_at",
                                "decision_note", "updated_at"])


# ── кто подтверждает ────────────────────────────────────────────────────────

def resolve_approver(employee: Employee) -> int | None:
    """Лестница §6.2: назначенный → руководитель отдела → никого.

    Админ платформы сюда не входит намеренно: он может решать ВСЕГДА, сверх
    этой лестницы, и подмешивать его сюда значило бы «назначить админа
    подтверждающим», чего никто не просил.
    """
    designated = (IdentityApprover.objects
                  .filter(pk=1)
                  .values_list("user_id", flat=True)
                  .first())
    if designated:
        return designated

    manager = employee.department.manager if employee.department_id else None
    return manager.user_id if manager is not None and manager.user_id else None


def may_decide(employee: Employee, *, actor_id: int, is_admin: bool) -> bool:
    return bool(is_admin) or resolve_approver(employee) == actor_id


def set_approver(user_id: int | None, *, actor_id: int) -> IdentityApprover:
    """Назначить подтверждающего (или снять назначение при ``None``)."""
    row, _ = IdentityApprover.objects.update_or_create(
        pk=1, defaults={"user_id": user_id, "updated_by": actor_id},
    )
    return row


def get_approver() -> IdentityApprover | None:
    return IdentityApprover.objects.filter(pk=1).first()


# ── уведомления ─────────────────────────────────────────────────────────────

def notify_approver(request: IdentityChangeRequest, verb: str) -> None:
    """Сообщить подтверждающему о заявке. Никогда не бросает наружу.

    Заявка уже записана в БД — она и есть задача; уведомление лишь ускоряет
    реакцию. Падение курьера не должно откатывать сохранение карточки, поэтому
    каждый канал завёрнут отдельно и помечен expected=True.
    """
    recipient = resolve_approver(request.employee)
    if recipient is None:
        fallback("hr.identity_sync.no_approver", None,
                 reason="подтверждающий не назначен и у отдела нет руководителя",
                 expected=True, request_id=request.id)
        return

    from apps.messenger import interface as messenger_interface
    from apps.tasks import interface as tasks_interface

    try:
        tasks_interface.push_notification(
            recipient_id=recipient, verb=verb,
            target_type="hr_identity_request", target_id=request.id,
        )
    except Exception as exc:  # noqa: BLE001
        fallback("hr.identity_sync.bell_failed", None,
                 reason="не удалось положить уведомление в колокольчик",
                 exc=exc, expected=True, request_id=request.id)

    try:
        messenger_interface.dispatch_notification(
            [recipient], {"type": verb, "request_id": request.id},
        )
    except Exception as exc:  # noqa: BLE001
        fallback("hr.identity_sync.toast_failed", None,
                 reason="не удалось отправить живое уведомление",
                 exc=exc, expected=True, request_id=request.id)


# ── решение ─────────────────────────────────────────────────────────────────

@transaction.atomic
def decide(request_id: int, decisions: dict, *, actor_id: int,
           is_admin: bool = False, note: str | None = None) -> IdentityChangeRequest:
    """Применить решение подтверждающего. Всё или ничего, одной транзакцией."""
    request = (IdentityChangeRequest.objects
               .select_for_update()
               .select_related("employee", "employee__department")
               .filter(pk=request_id)
               .first())
    if request is None:
        raise RequestNotFound(request_id)
    if request.status != IdentityChangeRequest.Status.PENDING:
        raise RequestClosed(request_id)
    if not may_decide(request.employee, actor_id=actor_id, is_admin=is_admin):
        raise NotApprover(request_id)

    rows = list(request.fields.all())
    allowed = {IdentityChangeRequestField.Decision.APPLY,
               IdentityChangeRequestField.Decision.REJECT}
    undecided = [row.field for row in rows if decisions.get(row.field) not in allowed]
    if undecided:
        # Частичное применение оставило бы задачу подвешенной, а её смысл в
        # том, чтобы закрыться целиком.
        raise IncompleteDecision(undecided)

    to_apply: dict[str, str] = {}
    for row in rows:
        row.decision = decisions[row.field]
        row.save(update_fields=["decision", "updated_at"])
        if row.decision == IdentityChangeRequestField.Decision.APPLY:
            to_apply[FIELD_MAP[row.field]] = row.proposed_value or ""

    if to_apply:
        users_interface.apply_profile_fields(
            user_id=request.user_id, fields=to_apply, actor_id=actor_id,
        )
        # Возвращаем применённое в копию тем же вызовом: иначе карточка до
        # ночного прохода показывала бы старое значение, и подтверждающий
        # решил бы, что применение не сработало.
        identity_sync_service.sync_employee(request.employee_id)

    request.status = (IdentityChangeRequest.Status.APPLIED if to_apply
                      else IdentityChangeRequest.Status.REJECTED)
    request.decided_by = actor_id
    request.decided_at = timezone.now()
    request.decision_note = note
    request.save(update_fields=["status", "decided_by", "decided_at",
                                "decision_note", "updated_at"])
    return request


# ── сериализация ────────────────────────────────────────────────────────────

def serialize(request: IdentityChangeRequest, *, with_fields: bool = True) -> dict:
    """Форма ответа API.

    ``account_value_now`` читается живым, а не из снимка: расхождение снимка с
    живым значением и есть тот единственный настоящий конфликт, ради которого
    в окне появляется третья колонка (спека §9).
    """
    employee = request.employee
    payload = {
        "id": request.id,
        "employee_id": employee.id,
        "employee_name": f"{employee.last_name} {employee.first_name}".strip(),
        "department_id": employee.department_id,
        "user_id": request.user_id,
        "status": request.status,
        "source": request.source,
        "created_by": request.created_by,
        "created_at": request.created_at.isoformat(),
        "decided_by": request.decided_by,
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
        "decision_note": request.decision_note,
    }
    if not with_fields:
        return payload

    snapshot = identity_sync_service.account_snapshot(request.user_id) or {}
    payload["fields"] = [
        {
            "field": row.field,
            "proposed_value": row.proposed_value or "",
            "account_value_at_request": row.account_value_at_request or "",
            "account_value_now": snapshot.get(row.field) or "",
            "is_stale": differs(row.field, row.account_value_at_request,
                                snapshot.get(row.field)),
            "decision": row.decision,
        }
        for row in request.fields.all().order_by("field")
    ]
    return payload
