"""Вход в раздел без данных (узел ``bpp.entry``, access/0025; решение 06.10).

``hr-lead`` ведёт проектную структуру (``project.structure``), а экран
«Проектов» живёт в разделе ``/bpp``, гейт которого — ``bpp:read``. Узел-пропуск
даёт этот уровень и НИЧЕГО больше: держатель системной роли ``hr-lead`` —
участник проектов с бюджетами, заявками и счетами (структура делает его
участником) — открывает раздел, а реестры модуля для него пусты."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.access.models import RolePermission
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.bpp.tests.test_overview import _world
from apps.project.models import Project
from apps.project.services import projects

pytestmark = pytest.mark.django_db
BASE = "/api/bpp/v1"
HR_LEAD = 971

REGISTRIES = ("budgets", "requests", "agreements", "invoices", "accountable", "plan",
              "counterparties", "alternatives/feed", "alternatives/offers", "bank/imports",
              "bank/accounts", "bank/templates", "kpi/records", "kpi/report",
              "dashboard/payments", "settings")


def _empty(body) -> bool:
    if isinstance(body, list):
        return body == []
    if isinstance(body, dict):
        if "total" in body:
            return body["total"] == 0 and not body.get("items")
        if "items" in body:
            return body["items"] == []
    return False


def test_hr_lead_holds_the_entry_node_only():
    rows = {r.node: set(r.flags) for r in RolePermission.objects.filter(role__code="hr-lead")
            if r.node == "bpp" or r.node.startswith("bpp.")}
    assert rows == {"bpp.entry": {"view"}}


def test_entry_opens_the_section_but_no_document(company_context):
    slug = company_context["slug"]
    _world(slug)
    s.grant(slug, HR_LEAD, "hr-lead")
    for project in Project.objects.all():
        projects.add_member(project, HR_LEAD, actor_id=1)

    client = Client()
    overview = client.get(f"{BASE}/overview", **s.auth(slug, HR_LEAD))
    assert overview.status_code == 200, overview.content
    assert not {"budgets", "requests", "invoices", "agreements", "plan", "accountable",
                "bank", "dashboard", "alternatives", "kpi", "admin"} & set(overview.json())

    leaks = []
    for path in REGISTRIES:
        response = client.get(f"{BASE}/{path}", **s.auth(slug, HR_LEAD))
        if response.status_code == 200 and not _empty(response.json()):
            leaks.append((path, response.json()))
    assert leaks == []
