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

BASE = "/api/requests/v1"

COMPANY = "t-approvals-gate"


def token(**over) -> str:
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7", "company": COMPANY,
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def admin_token(**over) -> str:
    return token(user_id=9, sub="9", is_admin=True, **over)


def auth(tok: str | None = None) -> dict:
    from apps.access.tests.helpers import gate_company

    # Каждый id, на котором тесты аппки проверяют СОБСТВЕННУЮ проверку (не
    # гейт модуля), получает тот же уровень, что рядовой сотрудник —
    # согласующий 11 (``simple_workflow``) и второй согласующий 12
    # (all-mode), «посторонний» 42 (стрелки cancel/act), 77 и 5 (чужой /
    # приглашённый читатель data-table в test_reference_api.py) — иначе 403
    # даёт гейт, а не проверка, которую заявляет тест. 9 — admin_token().
    gate_company(COMPANY, {
        7: {"approvals": "write"},
        9: {"approvals": "full"},
        11: {"approvals": "write"},
        12: {"approvals": "write"},
        42: {"approvals": "write"},
        77: {"approvals": "write"},
        5: {"approvals": "write"},
    })
    return {"HTTP_AUTHORIZATION": f"Bearer {tok or token()}",
            "HTTP_X_HTQ_COMPANY": COMPANY}


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


def make_template(*, slug: str = "otpusk", publish: bool = True,
                  workflow: dict | None = None, schema: dict | None = None,
                  config: dict | None = None,
                  project=None) -> RequestFormTemplate:
    template = RequestFormTemplate.objects.create(
        name="Отпуск", slug=slug, project=project,
        config_json=config or {},
    )
    if publish:
        version = RequestFormTemplateVersion.objects.create(
            template=template, version=1,
            schema_json=schema or simple_schema(),
            workflow_json=workflow or simple_workflow(),
        )
        template.current_version_id = version.id
        template.save(update_fields=["current_version_id"])
    return template


def make_instance(template: RequestFormTemplate, *, initiator_id: int = 7,
                  status: str = RequestStatus.DRAFT,
                  values: dict | None = None) -> RequestInstance:
    return RequestInstance.objects.create(
        code=f"REQ-{template.slug}-2026-{RequestInstance.objects.count() + 1:04d}",
        template=template, template_version_id=template.current_version_id,
        initiator_id=initiator_id, status=status,
        form_values_json=values or {"amount": 100},
    )
