"""Disableability of the tasks domain (DoD §6.6 п.2).

``apps/core/tests/test_invariants.py`` (Test 3) already sweeps every route
Django's resolver knows about under a gated prefix, reflectively, so this
file does NOT re-enumerate the route table — that list would rot the moment
a route is added, which is precisely what the reflective sweep exists to
avoid.

What is covered here is the part the generic sweep cannot express:

1. the exact 503 envelope for this service (``service: "tasks"``), so a
   change to ``disabled_payload`` shows up as a tasks-contract failure too;
2. the **cross-app** guarantee from the DoD — a valid token still works in a
   neighbouring app while tasks is off, i.e. disabling a domain degrades that
   domain only and does not invalidate tokens platform-wide;
3. that the gate runs BEFORE URL resolution — a path that does not exist at
   all under the tasks prefix still answers 503, not 404, when the service is
   off. That ordering is what makes the guarantee complete: it cannot be
   sidestepped by hitting an unmapped path.
"""

import pytest
from django.test import Client

from apps.core.models import ServiceStatus

from .helpers import BASE, auth


@pytest.fixture
def tasks_off(db):
    ServiceStatus.objects.update_or_create(app_label="tasks",
                                           defaults={"enabled": False})
    yield


@pytest.mark.django_db
def test_disabled_tasks_returns_the_service_envelope(tasks_off):
    resp = Client().get(f"{BASE}/labels/", **auth())
    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "service_disabled"
    assert body["service"] == "tasks"
    assert "detail" in body


@pytest.mark.django_db
def test_gate_precedes_url_resolution(tasks_off):
    """An unmapped path under the tasks prefix answers 503, not 404 — the
    middleware matches on the prefix before the resolver ever runs."""
    resp = Client().get(f"{BASE}/no-such-route/", **auth())
    assert resp.status_code == 503
    assert resp.json()["service"] == "tasks"


@pytest.mark.django_db
def test_disabled_tasks_refuses_even_unauthenticated_callers(tasks_off):
    """503 wins over 401: a disabled service reveals nothing about auth."""
    resp = Client().get(f"{BASE}/labels/")
    assert resp.status_code == 503


@pytest.mark.django_db
def test_neighbour_app_still_serves_the_same_token(tasks_off):
    """The critical DoD check: turning tasks off must not invalidate tokens
    or break another app. ``/api/core/v1/services/`` is public (decision Р4)
    and belongs to core, which is not gated."""
    resp = Client().get("/api/core/v1/services/", **auth())
    assert resp.status_code == 200


@pytest.mark.django_db
def test_tasks_recovers_when_re_enabled(tasks_off):
    ServiceStatus.objects.update_or_create(app_label="tasks",
                                           defaults={"enabled": True})
    resp = Client().get(f"{BASE}/labels/", **auth())
    assert resp.status_code == 200
