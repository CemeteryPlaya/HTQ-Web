"""Shared test helpers for the tasks domain.

The other apps repeat their ``_token``/``_auth_header`` pair in each test
file. With ~15 route groups to cover that would be a dozen copies of the
same six lines, so the tasks tests share one module instead. This is not a
break with the "duplicate per service" rule in CLAUDE.md — that rule
protects independently-deployed FastAPI services, and (as the root
``conftest.py`` spells out) it does not apply inside the single Django
process.

Not named ``test_*.py``, so pytest does not collect it (``pytest.ini`` sets
``python_files = test_*.py``).

Block I, task 7: every ``apps.tasks`` handle now stands under
``api_view(module="tasks", level=...)`` (``apps.access.self_service`` lists
``"tasks": {}`` — no self-service exemptions at all, unlike ``hr``). The
gate asks ``access.permission_level(token, "tasks", company)``, and that is
unconditionally ``none`` without a COMPANY
(``apps/access/services/resolve.py::permissions_for`` — ``if company is
None: return {}``), even for a token that carries every legacy flag. So the
default caller needs both a company claim on the token AND a real, ACTIVE
``Company`` row for ``CompanyContextMiddleware`` to accept the
``X-HTQ-Company`` header, AND a role granting the ``tasks`` module some
depth (``employee-basic`` is not used here on purpose — see
``_ensure_company_and_roles`` below).
"""

from __future__ import annotations

import json

import jwt as pyjwt
from django.conf import settings
from django.test import Client

BASE = "/api/tasks/v1"

#: Slug reserved for this helper module alone. Deliberately distinct from
#: every slug used by ``test_holding_api.py``/``test_holding_summary.py``
#: (``t-api-holding``/``t-api-child``/``t-alpha``/``t-beta``) and from
#: ``two_company_schemas``/``company_row`` in the root ``conftest.py`` — an
#: ACTIVE row under this slug must never appear while a fan-out-by-company
#: test (``test_tasks_dispatch.py``) or a holding-views rebuild
#: (``test_holding_api.py``, ``test_holding_summary.py``) is running, since
#: ``apps.companies.interface.active_company_slugs()`` (which both of those
#: read) has no notion of "ignore this one" — hence why the row is created
#: lazily, from ``auth()`` itself, and not from a blanket autouse fixture:
#: those two files build their own tokens/headers locally and never call
#: this module's ``auth()``, so they never see this company at all.
COMPANY = "t-tasks-gate"


def token(**over) -> str:
    """A valid access token. Claims match ``htqweb.authn`` expectations —
    issuer ``htqweb-auth``, ``token_type='access'`` (see CLAUDE.md's JWT
    contract)."""
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


def _ensure_company_and_roles() -> None:
    """Company row + module roles for the two standard callers, on demand.

    Called from ``auth()`` — i.e. only by a test that is actually about to
    hit an HTTP endpoint through the Django test ``Client`` — rather than
    from an autouse fixture that would run for every db test in this
    package regardless of whether it touches ``tasks`` over HTTP at all.
    That distinction matters: a blanket fixture creating an ACTIVE company
    row would corrupt ``active_company_slugs()`` for any test that fans out
    over every active company or rebuilds the holding views in the SAME
    transaction (``test_tasks_dispatch.py``, ``test_holding_api.py``,
    ``test_holding_summary.py``) — none of those import this helper, so
    they never trigger this function and never see ``COMPANY`` at all.

    Roles are granted through ``apps.access.tests.helpers.assign`` — a
    synthetic role, not the real ``employee-basic`` — because several
    tests in this package use ``@pytest.mark.django_db(transaction=True)``
    (schema-backed fixtures), which TRUNCATEs the whole test database on
    teardown and would erase a role seeded by a MIGRATION; ``assign()``
    recreates its role idempotently on every call, so it survives that.

    * ``user_id=7`` (the default ``token()`` caller) gets ``"tasks"`` at
      ``"write"`` — the same overall module level ``employee-basic`` ends
      up with once its own nodes are unioned (``tasks.tasks`` EDIT +
      ``tasks.calendar``/``tasks.daily_reports`` CREATE, no
      ``can_delete`` anywhere — see ``access/migrations/
      0004_seed_employee_role.py`` and ``apps/access/depth.py::
      legacy_level``), so the huge pre-existing behavioural test suite
      keeps exercising the SAME ownership/ visibility rules it always did,
      just with the module door now actually locked for someone who holds
      no role at all.
    * ``user_id=9`` (``admin_token()``) gets ``"tasks"`` at ``"full"``
      (level ``admin``): under the new model ``is_admin`` alone opens
      nothing (the only free pass left is ``is_superuser`` — see
      ``apps.access.services.resolve.permissions_for``), so the many
      existing tests that use ``admin_token()`` to reach an
      ``admin=True``-gated write need an explicit role, the same fix
      ``apps/hr/tests/test_positions_api.py::admin_auth`` applied in task 5.
    """
    from apps.access.tests.helpers import assign
    from apps.companies.models import Company, CompanyKind

    Company.objects.get_or_create(
        slug=COMPANY, defaults={"name": "Tasks gate fixture",
                                "kind": CompanyKind.SERVICE})
    assign(COMPANY, 7, "tasks", "write")
    assign(COMPANY, 9, "tasks", "full")


def auth(tok: str | None = None) -> dict:
    _ensure_company_and_roles()
    return {"HTTP_AUTHORIZATION": f"Bearer {tok or token()}",
            "HTTP_X_HTQ_COMPANY": COMPANY}


def post_json(client: Client, path: str, body: dict, **extra):
    return client.post(path, data=json.dumps(body),
                       content_type="application/json", **extra)


def patch_json(client: Client, path: str, body: dict, **extra):
    return client.patch(path, data=json.dumps(body),
                        content_type="application/json", **extra)


def put_json(client: Client, path: str, body: dict, **extra):
    return client.put(path, data=json.dumps(body),
                      content_type="application/json", **extra)
