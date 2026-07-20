"""R0 (remediation plan) — three reflection-based meta-tests for the
platform's three load-bearing invariants.

Why this file exists (see ``docs/superpowers/plans/
2026-07-20-remediation-phases-2-3-findings.md``, ``## R0``): today each
invariant is held together by author discipline and manual cross-checking —
a route sweep is a hand-typed list of tuples, the ``require_service()`` guard
in a task and ``ServiceGatedAdminMixin`` on a ``ModelAdmin`` are conventions
nothing enforces. That is exactly how ``apps.media_files`` ended up with no
``admin.py`` at all (models silently unregistered, un-gated) without a single
test failing — only caught by manual review. With three domain apps that is
survivable; it will not be with nine. These tests turn "please remember to…"
into "CI will not let you forget":

1. Every ``@shared_task`` in a domain app's ``tasks.py`` must open with
   ``require_service("<service>")`` as its first executable statement
   (``inspect``/``ast``-verified, not string-matched).
2. Every domain ``ModelAdmin`` registered with ``django.contrib.admin.site``
   must mix in ``ServiceGatedAdminMixin`` (``ServiceStatus`` excepted — the
   anti-lockout switch, see ``apps/core/admin.py``'s module docstring).
3. Every concrete URL Django's own resolver has registered under a gated
   prefix (``PREFIX_TO_SERVICE``) 503s the instant that service is disabled
   — built from ``get_resolver()``, not a maintained list, so an added route
   under an existing gated prefix is swept automatically.

All three discover their targets reflectively (app registry / admin registry
/ URL resolver) rather than importing a hardcoded list of app names, so a
7th/8th/9th domain app is covered the day its ``tasks.py``/``admin.py``/
``urls.py`` lands, with zero edits here.

Known, documented, current gaps are carved out explicitly below (not
silently skipped) with a TODO pointing at the remediation step that closes
them — ``_KNOWN_UNREGISTERED`` for ``media_files`` (closed by R2). As each
gap closes, delete its allow-list entry; the moment nobody does, the sweep
fails again and stays honest.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import re
import textwrap
import uuid as uuid_module

import pytest
from celery.app.task import Task as CeleryTask
from django.apps import apps as django_apps
from django.contrib import admin
from django.core.cache import cache
from django.test import Client
from django.urls import get_resolver
from django.urls.resolvers import URLResolver

from apps.core.models import ServiceStatus
from htqweb.admin_gate import ServiceGatedAdminMixin
from htqweb.middleware.service_gate import PREFIX_TO_SERVICE, service_name_for_app_label

# ─────────────────────────────────────────────────────────────────────────
# Shared discovery: "domain app" = anything under apps.* except apps.core,
# the shared foundation (its tasks.py deliberately hosts an UNguarded
# reference task, `ping`, alongside the guarded `guarded_ping` example — it
# has no service of its own to gate against, so it is out of scope for all
# three tests below, exactly like it's out of scope for the per-app route
# sweeps).
# ─────────────────────────────────────────────────────────────────────────


def _domain_app_configs():
    return [
        c for c in django_apps.get_app_configs()
        if c.name.startswith("apps.") and c.label != "core"
    ]


# ═══════════════════════════════════════════════════════════════════════
# Test 1 — require_service() must be the first executable statement of
# every domain Celery task.
# ═══════════════════════════════════════════════════════════════════════


def _iter_domain_tasks():
    """Yield (app_label, service, task) for every ``@shared_task`` DEFINED
    (not merely imported) in ``apps/<domain>/tasks.py``, for every domain
    app that has a ``tasks.py`` at all.

    ``importlib.util.find_spec`` (not a bare try/import/except ImportError)
    tells apart "this app has no tasks.py" (skip — legitimately nothing to
    check, e.g. apps.users today) from "tasks.py exists but blows up on
    import" (let it raise — that is a real bug, not something to swallow
    into a silent skip).
    """
    for config in _domain_app_configs():
        tasks_module_name = f"{config.name}.tasks"
        if importlib.util.find_spec(tasks_module_name) is None:
            continue
        tasks_module = importlib.import_module(tasks_module_name)
        service = service_name_for_app_label(config.label)
        for _name, obj in inspect.getmembers(tasks_module):
            if isinstance(obj, CeleryTask) and obj.__module__ == tasks_module_name:
                yield config.label, service, obj


def _first_executable_stmt(func) -> ast.stmt | None:
    """The AST node of ``func``'s first body statement after its docstring
    (``None`` if the body is empty past the docstring)."""
    source = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(source)
    func_def = tree.body[0]
    assert isinstance(func_def, (ast.FunctionDef, ast.AsyncFunctionDef))
    body = func_def.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body[0] if body else None


def _is_require_service_call(stmt: ast.stmt | None, service: str) -> bool:
    return (
        stmt is not None
        and isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "require_service"
        and len(stmt.value.args) == 1
        and isinstance(stmt.value.args[0], ast.Constant)
        and stmt.value.args[0].value == service
    )


def test_every_domain_task_guards_disableability_first():
    violations = []
    tasks_seen = 0
    for app_label, service, task in _iter_domain_tasks():
        tasks_seen += 1
        fn = getattr(task, "run", None) or inspect.unwrap(task)
        stmt = _first_executable_stmt(fn)
        if not _is_require_service_call(stmt, service):
            got = ast.unparse(stmt) if stmt is not None else "<empty body>"
            violations.append(
                f"{app_label}.tasks.{task.name.rsplit('.', 1)[-1]}: "
                f"first statement must be require_service({service!r}), got: {got}"
            )
    # A tautology-proof empty pass would be worse than no test at all —
    # make sure discovery actually found something before trusting an
    # empty violations list.
    assert tasks_seen > 0, "discovered zero domain Celery tasks — the sweep itself is broken"
    assert violations == [], (
        "Celery tasks missing the require_service() disableability guard as "
        "their first statement:\n  " + "\n  ".join(violations)
    )


# ═══════════════════════════════════════════════════════════════════════
# Test 2 — every domain ModelAdmin must mix in ServiceGatedAdminMixin.
# ═══════════════════════════════════════════════════════════════════════

# TODO(R2): apps/media_files has no admin.py at all yet — its 3 models
# (FileMetadata, FileVariant, AuditLog) are unregistered, so there is
# nothing here for the mixin assertion to even see. Remove this entry once
# R2 lands apps/media_files/admin.py with ServiceGatedAdminMixin on all
# three; at that point this allow-list becomes empty and this test starts
# enforcing "every domain app has SOME registered, gated admin" with no
# carve-outs left.
_KNOWN_UNREGISTERED = {"media_files"}

# ServiceStatus is the operator on/off switch itself. Wrapping it in the
# gate it implements would be a lockout footgun: if `core` (or any label,
# via a fat-fingered row) were ever disabled, the ONLY admin screen able to
# flip it back would refuse to load. See apps/core/admin.py's module
# docstring — this is the ONE sanctioned exception, by identity, not by
# app_label (so a future apps.core model, should one ever appear, is not
# accidentally exempted too).
_ANTI_LOCKOUT_EXEMPT = {ServiceStatus}


def test_every_domain_model_admin_has_service_gate_mixin():
    violations = []
    labels_with_registered_admin: set[str] = set()

    for model, model_admin in admin.site._registry.items():
        # Third-party/stock apps (django.contrib.auth's Group,
        # django_celery_results, django_celery_beat, django_json_widget's
        # own demo model if any, ...) are never expected to carry our
        # platform-specific mixin — filter by module path, not by an
        # explicit deny-list, so a new third-party admin never needs an
        # edit here.
        if not model.__module__.startswith("apps."):
            continue
        if model in _ANTI_LOCKOUT_EXEMPT:
            continue

        labels_with_registered_admin.add(model._meta.app_label)
        if not isinstance(model_admin, ServiceGatedAdminMixin):
            violations.append(
                f"{model.__module__}.{model.__name__} is registered with "
                f"{type(model_admin).__name__}, missing ServiceGatedAdminMixin"
            )

    assert violations == [], (
        "Domain ModelAdmins missing ServiceGatedAdminMixin:\n  "
        + "\n  ".join(violations)
    )

    domain_labels = {c.label for c in _domain_app_configs()}
    missing_entirely = domain_labels - labels_with_registered_admin - _KNOWN_UNREGISTERED
    assert missing_entirely == set(), (
        "Domain app(s) with ZERO registered ModelAdmin and not in the "
        f"documented _KNOWN_UNREGISTERED allow-list: {sorted(missing_entirely)} "
        "— either register their models under ServiceGatedAdminMixin, or add "
        "a TODO-annotated allow-list entry if this is a known, tracked gap."
    )


# ═══════════════════════════════════════════════════════════════════════
# Test 3 — disableability sweep generated from the URL resolver, not a
# hand-maintained list.
# ═══════════════════════════════════════════════════════════════════════
#
# Method choice: every request below is a GET regardless of what methods
# the target view actually accepts. That is deliberate, not an oversight —
# ServiceGateMiddleware (htqweb/middleware/service_gate.py) is the SECOND
# middleware in MIDDLEWARE (htqweb/settings/base.py), running well before
# Django resolves the path to a view at all, and it matches purely on
# `request.path.startswith(prefix)` — the HTTP method never enters into it.
# A disabled service's routes 503 for literally any method, including ones
# the view would itself reject with 405 if the gate let it through. GET is
# therefore both safe and sufficient for every entry; this comment is the
# record of *why*, so nobody "fixes" this into a per-route method map later
# under the mistaken belief it was an oversight.

_CONVERTER_VALUES = {
    "uuid": lambda: str(uuid_module.uuid4()),
    "int": lambda: "1",
    "str": lambda: "x",
    "path": lambda: "x/y",
}
_CONVERTER_RE = re.compile(r"<(\w+):(\w+)>")

# (service, raw_route_with_placeholders) pairs genuinely hard to synthesize
# a URL for, with a reason each. Empty today — every path converter
# actually used across apps/*/urls.py (int, str, uuid, path) has a value in
# _CONVERTER_VALUES above. Kept as a documented seam for the future rather
# than deleted, per the task brief.
_SWEEP_SKIP: set[tuple[str, str]] = set()


def _concretize(route: str) -> str:
    """Substitute a valid dummy value for every ``<converter:name>`` in a
    Django route string. Raises (loudly, not silently) for a converter type
    with no entry in _CONVERTER_VALUES — better a clear KeyError pointing
    here than a route quietly dropped from coverage."""
    def repl(match: re.Match) -> str:
        converter, _name = match.group(1), match.group(2)
        return _CONVERTER_VALUES[converter]()
    return _CONVERTER_RE.sub(repl, route)


def _leaf_routes():
    """Every concrete ``(full_route, view_callback)`` leaf in the root
    URLconf, recursively resolving every ``include()``. ``full_route`` has
    no leading slash (Django route strings, e.g. ``"api/cms/v1/"``, never
    carry one — added by callers that need it)."""
    def walk(resolver, prefix: str):
        for entry in resolver.url_patterns:
            full = prefix + str(entry.pattern)
            if isinstance(entry, URLResolver):
                yield from walk(entry, full)
            else:
                yield full, entry.callback
    yield from walk(get_resolver(), "")


def _sweep_targets() -> list[tuple[str, str]]:
    """(service, concrete_path) for every URL the live resolver has
    registered under a mounted, HTTP-routed PREFIX_TO_SERVICE prefix.

    A prefix with zero matches (an app not mounted yet, e.g. hr/tasks/
    approvals/mail — see htqweb/urls.py, which only includes cms/users/
    media today) simply contributes no targets; it is not an error, since
    "actually mounted" is exactly the filter the task asks for. `/ws/...`
    prefixes are skipped outright: they're WebSocket routing (not-yet-built
    per PREFIX_TO_SERVICE's own comment), never registered in Django's
    URLconf, so the resolver walk would never find them anyway — the
    explicit skip just documents that this is expected, not a discovery bug.
    """
    all_leaves = [("/" + full, callback) for full, callback in _leaf_routes()]
    targets: list[tuple[str, str]] = []
    for prefix, service in PREFIX_TO_SERVICE.items():
        if prefix.startswith("/ws/"):
            continue
        for full, _callback in all_leaves:
            if not full.startswith(prefix):
                continue
            if (service, full) in _SWEEP_SKIP:
                continue
            targets.append((service, _concretize(full)))
    return targets


_SWEEP_TARGETS = _sweep_targets()
_SWEEP_IDS = [f"{service} {path}" for service, path in _SWEEP_TARGETS]


@pytest.mark.django_db
@pytest.mark.parametrize("service,path", _SWEEP_TARGETS, ids=_SWEEP_IDS)
def test_resolver_discovered_route_503s_when_its_service_is_disabled(service, path):
    ServiceStatus.objects.update_or_create(app_label=service, defaults={"enabled": False})
    # The autouse fixture in conftest.py only clears the cache BETWEEN
    # tests; within THIS test the 5s TTL (apps/core/services.py) could
    # still serve a stale "enabled" read straight after the write above —
    # bust the specific key immediately, same as
    # apps.core.admin.ServiceStatusAdmin.save_model does.
    cache.delete(f"svc-status:{service}")

    resp = Client().get(path)

    assert resp.status_code == 503, (
        f"{path} did not 503 with {service!r} disabled (got {resp.status_code}) "
        "— a route exists under a gated prefix that the resolver sweep found "
        "but the gate did not catch"
    )
    body = resp.json()
    assert set(body) == {"detail", "code", "service"}
    assert body["code"] == "service_disabled"
    assert body["service"] == service
    assert body["detail"]


def test_resolver_sweep_covers_users_cms_and_media():
    """Canary for the discovery mechanism itself: if this ever collects
    zero routes for one of the three currently-mounted domains, the sweep
    above would vacuously pass with nothing tested — this catches that."""
    covered = {service for service, _path in _SWEEP_TARGETS}
    for must_cover in ("users", "cms", "media"):
        assert must_cover in covered, (
            f"resolver sweep found no routes for service {must_cover!r} — "
            "discovery is broken (or the app is no longer mounted in htqweb/urls.py)"
        )
