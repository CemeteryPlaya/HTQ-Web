"""Shared test helpers for the approvals domain.

Same rationale as ``apps.tasks.tests.helpers`` — one copy per app rather than
per test file. Not named ``test_*.py``, so pytest does not collect it.
"""

from __future__ import annotations

import json

import jwt as pyjwt
from django.conf import settings
from django.test import Client

from apps.approvals.models import (
    RequestFormTemplate, RequestFormTemplateVersion, RequestInstance,
    RequestStatus,
)
# Тесты из проверки изоляции исключены: маршрут заявки живёт в signoff, и
# заводить его напрямую — единственный способ не гонять HTTP ради каждого
# теста; согласующие — настоящие пользователи, потому что движок проверяет
# их активность через apps.users.interface.
from apps.signoff.models import (
    ApprovalRoute, ApprovalRouteStage, ApprovalTask, ApproverKind, Quorum,
    StageState, TaskState,
)
from apps.users.models import User, UserStatus

BASE = "/api/requests/v1"
SIGNOFF = "/api/signoff/v1"
SUBJECT = RequestInstance.SIGNOFF_SUBJECT_TYPE
APPROVER = 11


def token(**over) -> str:
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def admin_token(**over) -> str:
    return token(user_id=9, sub="9", is_admin=True, **over)


def auth(tok: str | None = None) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {tok or token()}"}


def post_json(client: Client, path: str, body: dict, **extra):
    return client.post(path, data=json.dumps(body),
                       content_type="application/json", **extra)


def patch_json(client: Client, path: str, body: dict, **extra):
    return client.patch(path, data=json.dumps(body),
                        content_type="application/json", **extra)


# ── workflow fixtures ───────────────────────────────────────────────────

def simple_workflow(approver_id: int = 11, mode: str = "any") -> dict:
    """start -> approval -> end_approved, with a reject branch."""
    return {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "a1", "type": "approval", "mode": mode,
             "assignee": {"kind": "user", "id": approver_id}},
            {"id": "ok", "type": "end_approved"},
            {"id": "no", "type": "end_rejected"},
        ],
        "edges": [
            {"from": "start", "to": "a1"},
            {"from": "a1", "to": "ok", "on": "approve"},
            {"from": "a1", "to": "no", "on": "reject"},
        ],
    }


def simple_schema() -> dict:
    return {"fields": [{"key": "amount", "type": "number", "label": "Сумма"}]}


def ensure_user(user_id: int, *, active: bool = True) -> User:
    """Учётная запись с ЗАДАННЫМ id — тесты адресуют согласующих числами
    (``APPROVER = 11``), а signoff требует, чтобы за числом стоял активный
    пользователь."""
    user, _ = User.objects.get_or_create(
        pk=user_id,
        defaults={"username": f"user{user_id}", "email": f"user{user_id}@htq.test",
                  "password": "x",
                  "status": UserStatus.ACTIVE if active else UserStatus.SUSPENDED},
    )
    return user


def route_for_template(template: RequestFormTemplate, *approver_ids: int,
                       quorum: str = Quorum.ALL, name: str = "Согласование") -> ApprovalRoute:
    """Маршрут signoff в области шаблона: один этап, согласующие поимённо."""
    ids = list(approver_ids) or [APPROVER]
    for user_id in ids:
        ensure_user(user_id)
    route = ApprovalRoute.objects.create(
        subject_type=SUBJECT, scope=f"template:{template.pk}", name=name)
    ApprovalRouteStage.objects.create(
        route=route, order=1, name=name, quorum=quorum,
        approver_kind=ApproverKind.USERS, user_ids=ids)
    return route


def make_template(*, slug: str = "otpusk", publish: bool = True,
                  workflow: dict | None = None, schema: dict | None = None,
                  config: dict | None = None,
                  project=None, route: bool = True,
                  approvers: tuple[int, ...] = (APPROVER,),
                  quorum: str = Quorum.ALL) -> RequestFormTemplate:
    """Шаблон с опубликованной версией и — по умолчанию — маршрутом signoff
    на одного согласующего ``APPROVER``. ``route=False`` — шаблон без
    маршрута (отправка даст 409 «не настроен маршрут»)."""
    template = RequestFormTemplate.objects.create(
        name="Отпуск", slug=slug, project=project,
        config_json=config or {},
    )
    if publish:
        version = RequestFormTemplateVersion.objects.create(
            template=template, version=1,
            schema_json=schema or simple_schema(),
            workflow_json=workflow or {},
        )
        template.current_version_id = version.id
        template.save(update_fields=["current_version_id"])
    if route:
        route_for_template(template, *approvers, quorum=quorum)
    return template


def pending_task(instance: RequestInstance, user_id: int) -> ApprovalTask:
    """Открытый запрос signoff к согласующему по этой заявке."""
    return ApprovalTask.objects.get(
        stage__process__subject_type=SUBJECT,
        stage__process__subject_id=instance.pk,
        stage__state=StageState.ACTIVE, user_id=user_id, state=TaskState.PENDING)


def decide(client: Client, instance: RequestInstance, user_id: int,
           decision: str = "approve", comment: str = ""):
    """Решение согласующего через HTTP signoff — так, как ходит фронтенд."""
    task = pending_task(instance, user_id)
    return post_json(client, f"{SIGNOFF}/tasks/{task.pk}/decision",
                     {"decision": decision, "comment": comment},
                     **auth(token(user_id=user_id, sub=str(user_id))))


def make_instance(template: RequestFormTemplate, *, initiator_id: int = 7,
                  status: str = RequestStatus.DRAFT,
                  values: dict | None = None) -> RequestInstance:
    return RequestInstance.objects.create(
        code=f"REQ-{template.slug}-2026-{RequestInstance.objects.count() + 1:04d}",
        template=template, template_version_id=template.current_version_id,
        initiator_id=initiator_id, status=status,
        form_values_json=values or {"amount": 100},
    )
