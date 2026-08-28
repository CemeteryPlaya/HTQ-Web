# HTQWeb backend

One Django backend (Python 3.14, Django 5.2.7) serving the whole HTQWeb API. It replaces the
platform's earlier FastAPI generation — nine independently-deployed microservices (`services/*`)
plus a shared `libs/htqweb_auth` — which have been deleted from this repo. This document
replaces the deleted `services/README.md` and covers the equivalent ground for the new shape:
the anatomy of one Django app, the rules that keep ~9 domains from turning back into a tangle,
how to add a new one, and how to run/test locally.

See also: [../CLAUDE.md](../CLAUDE.md) (session-level orientation), [../STRUCTURE.md](../STRUCTURE.md)
(repo-wide navigation map, Russian), [../API.md](../API.md) (HTTP contract), [README-tests.md](./README-tests.md)
(pytest-against-real-Postgres setup).

## What this is

Domains live as Django apps under `apps/`: `users`, `cms`, `media_files`, `hr`, `mail`,
`messenger`, `tasks`, `approvals`, `contracts`, `signoff`, plus `core` (shared foundation — the
service registry, ETL helpers, health checks; not a domain itself). Everything else — auth primitives, the API
decorator, object storage, middleware — lives once in the `htqweb/` project package, not
duplicated per app the way the FastAPI generation duplicated `s3_storage.py`/`request_id.py`
per service. There is exactly one codebase, one process family, one settings module tree; the
domain boundary is enforced by convention + tests, not by separate deployments anymore.

```
backend/
├── manage.py
├── requirements.txt
├── pytest.ini              # DJANGO_SETTINGS_MODULE = htqweb.settings.test
├── conftest.py              # repo-root pytest fixtures (see its docstring — don't copy it per-app)
├── Dockerfile   docker-entrypoint.sh
├── htqweb/                  # project package — shared by every app, never duplicated
│   ├── settings/
│   │   ├── base.py           # the real settings; env-driven, DB_HOST=db DB_PORT=5432 by default
│   │   ├── dev.py             # DEBUG=True, imports base
│   │   └── test.py            # pytest-django settings — direct Postgres on :55432, eager Celery
│   ├── urls.py                # root URLconf + the app-autodiscovery loop (see below)
│   ├── wsgi.py   asgi.py       # WSGI = gunicorn entrypoint; ASGI = uvicorn (SSE + messenger WS)
│   ├── http.py                 # api_view — the API decorator (see "API layer" below)
│   ├── admin_gate.py            # ServiceGatedAdminMixin — django-admin permission gate
│   ├── authn/                   # JWT issue/decode, RBAC predicate, department-level enum
│   │   ├── jwt.py  payload.py  rbac.py  levels.py
│   │   └── tests/test_jwt_contract.py
│   ├── middleware/
│   │   ├── request_id.py         # X-Request-ID propagation
│   │   ├── service_gate.py        # ServiceGateMiddleware — URL-prefix service gate
│   │   └── api_csrf_exempt.py      # exempts /api/* from Django's session-CSRF (JWT is stateless)
│   └── storage/
│       ├── s3.py                   # S3/MinIO + local-disk backend (sync; ported from cms's async original)
│       ├── signed_url.py            # HMAC signed-URL issuance/verification for private files
│       └── tests/
└── apps/
    └── <domain>/            # see "Anatomy of one app" below
```

## Anatomy of one app

```
apps/<domain>/
├── apps.py            # AppConfig; API_PREFIX = "api/<domain>/v1/" drives URL autodiscovery
├── models.py           # Django ORM, managed=True — plain tables, Django's default naming
├── schemas.py          # Pydantic request/response DTOs (ported from the FastAPI service's
│                       #   schemas/ almost verbatim — api_view knows how to serialize/validate them)
├── services/            # ⭐ business logic — one file per subsystem. views.py calls these,
│                       #   never the other way around
├── views.py              # thin HTTP dispatchers, each wrapped in @api_view(...)
├── urls.py                # path() routes, mounted automatically (see below)
├── interface.py            # ⭐ the ONLY thing a neighbour app is allowed to import from here
├── admin.py                 # django-admin ModelAdmin classes, wrapped in ServiceGatedAdminMixin
├── tasks.py                  # @shared_task Celery tasks
├── migrations/                 # plain Django migrations
├── management/commands/         # etl_<domain>.py (one-shot legacy-data cutover) + anything else
└── tests/                        # pytest-django, discovered automatically (no per-app conftest
                                  #   needed for the service-status cache — see backend/conftest.py)
```

## The rules

These aren't style preferences — each one is enforced by a test, a middleware, or both. Breaking
one doesn't just look wrong, it fails CI.

### 1. Cross-app access is only through `interface.py`

A domain app may **never** `import apps.<other>.models` or `apps.<other>.services` — only
`apps.<other>.interface`. `apps.core` is the one exception (shared foundation: the service
registry). This is checked by [`apps/core/tests/test_app_isolation.py`](apps/core/tests/test_app_isolation.py),
which scans every `.py` file under `apps/` (including `interface.py` itself — a neighbour's
`interface.py` reaching past another neighbour's `interface.py` is caught too) for
`apps.<x>.<module>` imports and fails the build if it finds a forbidden one.

Write an `interface.py` function like this:

```python
def get_user_brief(user_id: int) -> dict | None:
    require_service("users")          # 1. gate: raises ServiceDisabled if this app is off
    row = User.objects.filter(pk=user_id).values(*_BRIEF_FIELDS).first()
    return _brief_from_values(row) if row is not None else None   # 2. return plain dict, never an ORM object
```

Two conventions every `interface.py` function follows:
- **`require_service("<name>")` first.** If the callee app is disabled, the caller gets a
  `ServiceDisabled` exception, which `api_view` (or the caller's own error handling) turns into
  the same 503 envelope an external HTTP call to a disabled app would get — a neighbour's outage
  degrades the same way a direct one would, instead of surfacing as an unrelated 500.
- **Return plain `dict`/`str`/`bool`/`list`, never ORM model instances.** A neighbour must not be
  able to mutate another app's rows just because it happened to get a live object back.

### 2. API layer is `htqweb.http.api_view`, not Django REST Framework

```python
@api_view(methods=("POST",), auth="jwt", body=CreateThing, admin=True, status=201)
def create_thing(request, data: CreateThing):
    ...
    return ThingRead.model_validate(obj)   # a Pydantic model, a dict, a list, or a raw HttpResponse
```

- `methods` — allowed HTTP verbs; anything else gets `405`.
- `auth` — `"jwt"` (Bearer token, most routes), `"admin_session"` (the legacy `admin_session`
  cookie — still decoded, but its only historical consumer, sqladmin, is gone; see
  [STRUCTURE.md §10](../STRUCTURE.md)), or `None` (public route — `request.token` is set to
  `None`, not left undefined, so views don't need a hard `except AttributeError`).
  Internal S2S-style endpoints (a couple survive in `hr`/`messenger`) do their own
  bearer-token check inside the view instead of using `auth=`.
- `body` — a Pydantic model; malformed/missing fields become a `422` with the
  `{"detail": [...]}` field-error shape, not an unhandled exception.
  `admin=True` requires `auth="jwt"` or `"admin_session"` — it checks `request.token`, so pairing
  it with `auth=None` is a decoration-time `ValueError`, not a silent always-403.
- Every response is normalized to `JsonResponse` with envelope `{"detail": ...}` on error —
  `404`/`403`/`400`/`500`/`503` all go through this, matching the old FastAPI contract so the
  frontend's error parsing didn't need to change. `ServiceDisabled` (raised by a
  `require_service()` call inside the view or a service it called) becomes `503` automatically —
  a view never needs to catch it itself.

Covered by [`apps/core/tests/test_api_view.py`](apps/core/tests/test_api_view.py).

### 3. URLs mount themselves — don't touch `htqweb/urls.py`

`htqweb/urls.py` loops over every installed app; any app whose `AppConfig` sets `API_PREFIX` and
ships a `urls.py` gets `include()`-mounted at that prefix automatically:

```python
# apps/<domain>/apps.py
class HrConfig(AppConfig):
    name = "apps.hr"
    API_PREFIX = "api/hr/v1/"
```

Adding a new domain app therefore never means editing `htqweb/urls.py` — that file would
otherwise be a guaranteed merge-conflict point between however many people/agents are adding
domains at once.

### 4. `APPEND_SLASH = False` — register every spelling the frontend uses

Django will not silently redirect `/foo` to `/foo/` (that 30x drops the `Authorization` header on
some clients, and is also just an extra round-trip). Every `urls.py` in this repo registers both
the slashed and bare spelling of a path if the frontend (or a webhook sender) might send either —
grep any `apps/*/urls.py` for the pattern. When adding a route, check the frontend's actual call
site (`frontend/src/api/<domain>.ts`) rather than guessing.

### 5. Business logic lives in `services/`, not `views.py`

`views.py` parses the request (via `api_view`'s `body=`), calls one or more functions in
`services/<file>.py`, and shapes the result. If you're looking for what an endpoint *does*, start
in `services/`.

### 6. Models are `managed=True`, migrations are plain Django

No Alembic, no hand-owned migration transactions, no `search_path` juggling. `manage.py
makemigrations <app>` after a model change, `manage.py migrate` to apply. Table names are
Django's own default (`<app_label>_<model>`, e.g. `hr_department`, `mail_emailaccount`) — nothing
here is prefixed by hand the way the old PgBouncer-schema-per-service setup required (see
[STRUCTURE.md §10](../STRUCTURE.md) if you're wondering why old comments mention `hr_*`/`task_*`
prefixes as if someone chose them deliberately — that was a different DB topology).

### 7. JWT contract is unchanged from the FastAPI generation

Issuer is still `htqweb-auth` (`settings.JWT_ISSUER`), HS256, shared `JWT_SECRET`. `apps.users`
now both issues (`htqweb/authn/jwt.py::issue_token_pair`, called from `apps.users.views`) and
every app validates locally (`htqweb/authn/jwt.py::decode_token`, called from `htqweb.http`'s
authenticators) — no separate identity service, no network round-trip either way. Claims:
`sub, user_id, username, email, is_staff, is_superuser, is_admin, token_type, iat, exp, iss`.
`TokenPayload.is_elevated` (`htqweb/authn/payload.py`) is the coarse admin predicate
(`is_admin or is_staff or is_superuser`) that `api_view(admin=True)` and
`htqweb.authn.rbac.require_admin` both key off. Department-scoped seniority (separate from the
coarse admin flag) is `htqweb/authn/levels.py::DepartmentLevel`.

### 8. Every app is disableable at runtime — plumb new features through the gate, don't bypass it

Four pieces work together, all keyed by the same registry (`apps.core.models.KNOWN_SERVICES`):

| Piece | Where | Gates |
|---|---|---|
| `ServiceStatus` | `apps/core/models.py` | The switch itself — one DB row per app, `enabled`/`message`, 5s cache |
| `ServiceGateMiddleware` | `htqweb/middleware/service_gate.py` | HTTP edge — `/api/<prefix>/` and `/ws/<prefix>/` by URL, via `PREFIX_TO_SERVICE` |
| `require_service(name)` | `apps/core/services.py` | In-process — first line of every `interface.py` function and every `tasks.py` task |
| `ServiceGatedAdminMixin` | `htqweb/admin_gate.py` | `/django-admin/` — wraps a `ModelAdmin`'s permission hooks |

Flip one: `manage.py service <name> --on/--off [--message "..."]`. A disabled app answers `503`
`{"detail", "code": "service_disabled", "service"}` at the HTTP edge and via any `interface.py`
call that hits its `require_service()`; the admin instead gets Django's native `PermissionDenied`
(by design — `django-admin` should fail the Django way, not with a JSON body meant for the API).
`ServiceStatus` itself is deliberately **not** gated by this mixin (see `apps/core/admin.py`'s
docstring) — otherwise disabling `core` would lock out the only place that can re-enable
anything.

If an app's `AppConfig.label` or registry name doesn't match its `app_label` 1:1 (currently:
`media_files` app_label → `media` in the registry, `approvals` app_label → also `approvals` but
mounted at `/api/requests/`, `mail` app_label → `/api/email/`), that mapping lives in
`htqweb/middleware/service_gate.py`'s `PREFIX_TO_SERVICE`/`APP_LABEL_TO_SERVICE` — update both
together, they're kept side by side on purpose.

Covered by [`apps/core/tests/test_service_gate.py`](apps/core/tests/test_service_gate.py),
[`test_admin_gate.py`](apps/core/tests/test_admin_gate.py),
[`test_service_command.py`](apps/core/tests/test_service_command.py).

### 9. Celery tasks guard themselves, same convention as `interface.py`

```python
@shared_task
def final_purge_archived_mailboxes() -> int:
    require_service("mail")
    ...
```

Every task's first line is `require_service("<name>")` — a disabled app's periodic/queued work
shouldn't run just because nothing calls it over HTTP. Checked by
[`apps/core/tests/test_celery.py`](apps/core/tests/test_celery.py) and
[`test_invariants.py`](apps/core/tests/test_invariants.py) (reflection-based meta-tests that walk
every app rather than special-casing each one — see
[`test_parallel_scaffold.py`](apps/core/tests/test_parallel_scaffold.py) too).

### 10. Object storage: `apps.media_files` is the shared file domain — don't grow a second one

`htqweb/storage/` is the low-level S3/MinIO/local-disk abstraction (`get_storage()`,
`signed_url.py`). `apps.cms` uses it directly (its own bucket, `S3_BUCKET=htqweb-cms` — it
predates `media_files` as an app). Every other domain that needs to store a file — `hr`
(department files), `mail` (attachments, currently metadata-only pending a future phase),
`messenger` (attachments) — goes through `apps.media_files.interface.store_file()`/
`.get_file_url()`/`.delete_file()` instead of holding its own bucket/copy of the storage code.
Don't add a new per-app storage client; extend `media_files` or call its interface.

### 11. Approval is `apps.signoff` — inherit its mixin, don't build a second engine

Two apps have "approval" in the name and they are not interchangeable:

- **`apps.approvals`** (`/api/requests/v1`) is a Lark-style **form designer**. Its unit of
  approval is a `RequestInstance` holding JSON field values it owns. It cannot point at a row
  that already exists somewhere else.
- **`apps.signoff`** (`/api/signoff/v1`) approves **another app's existing rows**, addressed by
  a `(subject_type, subject_id)` pair. This is the one you want for "this budget line / this
  agreement needs three people to sign off".

Wiring a model into `signoff` is three steps, **none of them inside `signoff`**:

```python
# apps/<domain>/models.py — interface is the only importable name (rule 1)
from apps.signoff import interface as signoff

class Budget(signoff.Approvable, models.Model):
    SIGNOFF_SUBJECT_TYPE = "contracts.budget"   # must match the registry key
```
```python
# apps/<domain>/approval_hooks.py, called from AppConfig.ready()
signoff.register_subject(
    Budget.SIGNOFF_SUBJECT_TYPE, label="Бюджетная строка", model=Budget,
    on_approved=..., on_rejected=..., describe=_describe_budget,
)
```
Then `makemigrations <domain>` for the `approval_state` column the mixin contributes — it lands
in **your** table, so no cross-domain FK is created.

Three things that trip people up:

- **You hand over the model class; signoff never imports it.** That's what lets signoff maintain
  its own `approval_state` column on your table without violating rule 1. `register_subject`
  rejects a `model` that doesn't inherit `Approvable`, or whose `SIGNOFF_SUBJECT_TYPE` disagrees
  with the key you registered under.
- **Callbacks run inside the engine's transaction** (`engine._finish`), so raising from one rolls
  the approval back — deliberately: a process marked "approved" over an object that failed to
  update is a state nothing can recover from. Messenger notifications, being an external effect,
  go through `transaction.on_commit` instead.
- **`register_subject` and `Approvable` are deliberately NOT behind `require_service`.** They run
  in `ready()`, before a DB connection exists (e.g. during `migrate` on an empty database). A
  gate there would take the whole process down over a disabled service. Everything at request
  time *is* gated. Correspondingly, `signoff.has_active_route()` answers `False` rather than
  raising when signoff is off — a disabled approval module should stop *requiring* approval, not
  break the apps that adopted it.

Reference implementations: `apps/contracts/approval_hooks.py` (real), `apps/signoff/tests/testapp/`
(minimal, ~40 lines).

### 12. Tenant apps live in a company schema — decide once, per app

`settings.TENANT_APPS = ("hr", "tasks", "contracts", "signoff")` is the fixed list of apps whose
tables live in a company's own Postgres schema (`co_<slug>`, `htqweb/tenancy/context.py::schema_for`)
instead of `public`. `htqweb.middleware.company_context.CompanyContextMiddleware` picks the schema
via `search_path` per request — the model layer itself never changes. The call is made once, when
the app is created; moving an app in or out of `TENANT_APPS` later means an
`ALTER TABLE ... SET SCHEMA` migration (see `manage.py tenancy_bootstrap` for the one that moved
the original four), not a settings edit.

**Criterion:** data belongs to one legal entity of the group (headcount, projects, contracts,
approvals) → the app goes in `TENANT_APPS`. Data shared across the whole group (accounts, the
public site, chat, files, mail) → the app stays in `public`.

A `TENANT_APPS` member must:
- **carry no company column on its models.** Isolation is the schema, not a filtered field —
  adding one back would be redundant at best (the schema already isolates it) and a false sense of
  safety at worst (nothing forces every query to apply the filter).
- **pass `company_slug` to its own Celery tasks explicitly**, via `@company_task`
  (`htqweb/tenancy/celery.py`). A task has no HTTP request to inherit context from; calling one
  without `company_slug` raises `MissingCompanyArgument` instead of silently running against
  `public`.
- **declare `apps/<domain>/holding.py` with `HOLDING_MODELS`** — `HOLDING_MODELS = ()` is fine if
  nothing from the app belongs in the group-wide holding views. This is not optional: the same
  autodiscovery convention as `API_PREFIX`/`metrics.py` is enforced by
  `apps.companies.services.holding_views.holding_models()`, which raises `ImproperlyConfigured`
  when rebuilding the views if any `TENANT_APPS` entry is missing the module or the attribute — a
  silently-skipped app would drop out of the holding dashboard's numbers without a trace, which is
  worse than a startup error.

Full design: [../docs/multi-company-tenancy-design.md](../docs/multi-company-tenancy-design.md).

## Adding a new domain app

```bash
cd backend
.venv/Scripts/python.exe manage.py startapp <domain> apps/<domain>
```
Then:
0. Decide tenant vs `public` (rule 12 above) — this determines whether the new app's tables end up
   in `settings.TENANT_APPS` and everything that follows from it (no company column, `@company_task`,
   `holding.py`).
1. Add `"apps.<domain>"` to `INSTALLED_APPS` (`htqweb/settings/base.py`).
2. Set `API_PREFIX = "api/<domain>/v1/"` on its `AppConfig` (`apps/<domain>/apps.py`) — URL
   autodiscovery does the rest, don't touch `htqweb/urls.py`.
3. Register the domain name in `apps.core.models.KNOWN_SERVICES`, and in
   `htqweb.middleware.service_gate.PREFIX_TO_SERVICE` (+ `APP_LABEL_TO_SERVICE` if the app_label
   won't match the registry name or URL prefix 1:1).
4. Write `interface.py` before anything else needs to call in — every function starts with
   `require_service("<name>")` and returns plain data, never ORM objects.
5. Wrap every `ModelAdmin` in `admin.py` with `htqweb.admin_gate.ServiceGatedAdminMixin`.
6. Any `@shared_task` in `tasks.py` starts with `require_service("<name>")`.
7. `manage.py makemigrations <domain>` once there are models.

## Local run

```bash
docker compose -f docker-compose.test-local.yml up -d --build
```
Brings up `backend-web` (gunicorn WSGI in prod / `runserver` in dev, `:8000`→host `:8000`),
`backend-asgi` (uvicorn ASGI, SSE `/api/requests/v1/stream` + WS `/ws/`, `:8000`→host `:8001`),
`backend-worker`/`backend-beat` (Celery), `flower` (`:5555`), plus `db`/`redis`/`minio` and the
Vite dev server (`:3000`) which proxies to all of the above. `backend-web` is the only process
that runs `migrate` and seeds `admin`/`admin12345` (`RUN_MIGRATIONS=1`, see
`docker-entrypoint.sh`). Rebuild one process after a code change:
```bash
docker compose -f docker-compose.test-local.yml up -d --build --no-deps backend-web
```

## Tests

pytest-django against **real Postgres**, not SQLite — see [README-tests.md](./README-tests.md)
for the full story (why port `:55432`, not `:5432`/`:6432`). Short version:

```bash
docker compose -f docker-compose.test-local.yml up -d db   # once, publishes :55432
cd backend
.venv/Scripts/python.exe -m pytest -q                                    # whole suite
.venv/Scripts/python.exe -m pytest apps/hr/tests/test_x.py::test_name    # single test
```
`pytest.ini` pins `DJANGO_SETTINGS_MODULE=htqweb.settings.test`; that settings module fixes
`JWT_SECRET`, runs Celery eagerly (synchronous, no broker), and uses `LocMemCache`. The
autouse `clear_service_status_cache` fixture in the repo-root `conftest.py` resets that cache
between every test — read its docstring before adding a per-app copy, it explains why one copy
at the repo root is correct and per-app copies would be redundant.
