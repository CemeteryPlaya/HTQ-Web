"""Ручка «кто я» модуля (ТЗ §23 GetCurrentUser, план этапа 2 A, задача 5):
группы статей и роли инициатора — по одному правилу с сервисом заявки
(``services.actor.Actor``), иначе гейт заявки и подсказка «кто я» могли бы
разойтись.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.access.tests.helpers import assign
from apps.bpp.tests import stage2 as s

BASE = "/api/bpp/v1"


@pytest.mark.django_db
def test_me_supply_officer(company_context):
    slug = company_context["slug"]
    s.metal()  # статья группы "supply"
    s.grant(slug, s.SN, "bpp-sn")
    resp = Client().get(f"{BASE}/me", **s.auth(slug, s.SN))
    assert resp.status_code == 200
    assert resp.json() == {"article_groups": ["supply"], "initiator_roles": ["sn"]}


@pytest.mark.django_db
def test_me_combined_roles_see_both_groups(company_context):
    """СН, совмещающий с ПМ, видит обе группы и обе роли инициатора."""
    slug = company_context["slug"]
    s.metal()   # "supply"
    s.design()  # "pm"
    s.grant(slug, s.SN, "bpp-sn", "bpp-pm")
    resp = Client().get(f"{BASE}/me", **s.auth(slug, s.SN))
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body["article_groups"]) == ["pm", "supply"]
    assert sorted(body["initiator_roles"]) == ["pm", "sn"]


@pytest.mark.django_db
def test_me_without_initiator_roles_is_empty(company_context):
    """Доступ к модулю есть (иначе гейт `bpp:read` отбил бы запрос 403 раньше
    вьюхи), но ни право подавать заявки, ни доступ к группам статей — ни
    один из узлов роли не задевает: список должен быть пустым, а не 500."""
    slug = company_context["slug"]
    assign(slug, 41, "bpp.dashboard", "read")
    resp = Client().get(f"{BASE}/me", **s.auth(slug, 41))
    assert resp.status_code == 200
    assert resp.json() == {"article_groups": [], "initiator_roles": []}


@pytest.mark.django_db
def test_me_requires_module_access(company_context):
    """Без единой строки доступа к модулю ``bpp`` гейт отвечает 403 раньше
    вьюхи — «кто я» не открывает модуль в обход общего гейта."""
    slug = company_context["slug"]
    resp = Client().get(f"{BASE}/me", **s.auth(slug, 42))
    assert resp.status_code == 403
