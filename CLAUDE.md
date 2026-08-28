# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Migration history (done)

The FastAPI→Django reverse migration — built by **two parallel executors** (Поток A = `hr`/`mail`/`messenger`, Поток B = `tasks`/`approvals`; see **[PLAN.md](PLAN.md)** for the full phase-by-phase journal) — is **complete and cut over**: all 9 FastAPI microservices and `libs/` (`htqweb_auth`, `htqweb_metrics`) were deleted from the repo, and the platform now runs as **one Django backend** (`backend/`). If you see "Поток A"/"Поток B" or "PLAN.md §..." in code comments, that's just where a piece of code came from — the zone split no longer restricts anything; work across any `backend/apps/**` as directed.

- **Cross-app access is still ONLY via `apps.<x>.interface`** (enforced by `apps/core/tests/test_app_isolation.py`) — no direct imports of another app's models/services, no cross-domain FK. That invariant survived the migration unchanged.
- **NEVER create git branches yourself.** The user creates and hands off every branch. Do not run `git branch`, `git checkout -b`, `git switch -c`, or `git worktree add`, and do **not** "branch first" before committing — even on the default branch. This overrides the default Claude Code behavior. Work only on the branch you are given; if the expected branch seems missing or wrong, stop and ask.

## What this is

HTQWeb — Hi-Tech Group's internal enterprise platform. A React + Vite SPA in front of **one Django backend** (Python 3.14, Django 5.2.7). Postgres (direct connection, app-level pooling), Redis (cache + Celery broker), MinIO/S3 object storage, Mediasoup SFU for video.

For context, the platform's history is a full circle: it started as a Django monolith, was migrated (Strangler Fig) out to ~9 FastAPI microservices behind an nginx gateway, and has now been merged back into a single Django backend (the reverse migration above). MongoDB (previously HR docs + the old admin panel) is gone along with the FastAPI generation.

## Read these first (don't re-derive the layout)

These are authoritative and maintained — prefer them over scanning the tree:
- **[STRUCTURE.md](STRUCTURE.md)** — the navigation map: every directory, the Django-app anatomy, where each concern lives. Russian.
- **[API.md](API.md)** — the full nginx routing table (`/api/<domain>/v1/*`), auth/JWT contract, per-domain endpoints.
- **[backend/README.md](backend/README.md)** — Django app anatomy, `interface`/`api_view` rules, how to add a domain. Replaces the deleted `services/README.md`.
- **[docs/architecture.md](docs/architecture.md)** — architectural decisions (predates the cutover in places — e.g. it still talks about DRF ViewSets and a `backend/tasks/` layout that doesn't exist; treat it as background, not a source of truth for current layout).

Ignore/discount at the repo root: empty `nginx/`, root `node_modules/`+`package.json` (tooling only). **Ровно три compose-файла, каждый самодостаточный (`-f <файл>`, БЕЗ цепочки `-f a -f b`):** `docker-compose.yml` (ПРОД — фронт собран в статику, gunicorn, nginx/certbot под профилем `production`, БД из `.env`; sfu/webtransport стартуют всегда), `docker-compose.test-local.yml` (тестовый стек: Vite HMR, DEBUG, Postgres в контейнере на `:55432` — туда же ходит pytest), `docker-compose.test-env.yml` (тестовый стек, но БД из `.env`, миграции по умолчанию OFF). Старые `docker-compose.dev.yml`, `docker-compose.localdb.yml`, `docker-compose.test.yml`, `docker-compose.django.yml`, `RUN-DJANGO-CHECK.md` удалены. Файлы намеренно НЕ наследуют друг друга, поэтому правка общего сервиса повторяется во всех трёх — сверяйте `git diff docker-compose*.yml`. The only authoritative gateway config is `infra/nginx/default.conf`.

## Commands

Каждый compose-файл объявляет своё имя проекта, поэтому контейнеры называются по нему:
прод — `htq-web-<service>-1` (имя берётся из каталога репозитория), тестовые стеки —
`htqweb-local-<service>-1` и `htqweb-env-<service>-1`. Тома у стеков тоже раздельные.

**БД:** прод и `test-env` берут её из `.env` (по умолчанию боевая на VPS
`45.10.110.212:5432`); `test-local` поднимает свой Postgres в контейнере и
**жёстко** прописывает `DB_HOST: db` — подстановки из `.env` там нет намеренно,
иначе «локальный» стек ушёл бы на прод.

**Run the stack** (файлы самостоятельные — никаких `-f a -f b`):
```bash
# ТЕСТ, локальная БД в контейнере (обычная разработка; Vite HMR :3000)
docker compose -f docker-compose.test-local.yml up -d --build
docker compose -f docker-compose.test-local.yml up -d --build --no-deps backend-web  # один процесс

# ТЕСТ, БД из .env (миграции по умолчанию OFF)
docker compose -f docker-compose.test-env.yml up -d --build

# ПРОД
docker compose up -d --build                       # + nginx/certbot под профилем production
```
⚠️ Три стека публикуют одни и те же host-порты — одновременно поднимается только один.

Прод-стек требует флага профиля — `docker compose --profile production up -d`. Без него nginx, certbot и nginx-exporter **не стартуют** (они в профиле `production`), то есть шлюза нет: SPA не отдаётся, а `/api` доступен только через порты, которые `backend-web`/`backend-asgi` публикуют напрямую. Обычный `docker compose up -d` поднимает всё остальное.

**Конференция (SFU) поднята и в dev, и в проде.** `sfu` (mediasoup, сигналинг `:4443`, медиа `:44444/udp+tcp`) и `webtransport` (QUIC-мост `:4433/udp`) больше не под профилем `production` — стартуют вместе со стеком. Что важно знать:
- **Сигналинг требует платформенный JWT.** SFU валидирует токен на WS-upgrade тем же `JWT_SECRET`/HS256, что и Django (`sfu/src/auth.ts`); браузер передаёт его подпротоколом `['htqweb.jwt', <token>]`, WebTransport-мост — параметром `?token=`. Без токена — 401 на upgrade. Отключается только для локальной отладки: `SFU_REQUIRE_AUTH=false`.
- **`WEBRTC_ANNOUNCED_IP` обязателен.** С wildcard listenIp и пустым announced SFU падает на старте намеренно (иначе — чёрное видео). В dev подставляется `127.0.0.1` (браузер на той же машине); для проверки с другого устройства поставьте LAN-IP хоста в корневом `.env`, в проде — публичный IP.
- **Транспорт сигналинга:** фронт сначала пробует WebTransport (QUIC), при неудаче сам откатывается на WebSocket (`WebRTCManager.buildSignalingAttempts`). Адрес моста и отпечаток его самоподписанного сертификата приезжают в `GET /api/cms/v1/conference/config` (`wt_signaling_url` / `wt_certificate_hashes`).
- **Тестовым фронтам обязателен `VITE_SFU_WS_TARGET: ws://sfu:4443`.** Без него Vite шлёт `/ws/sfu` на дефолтный `127.0.0.1:4443` — то есть в САМ контейнер фронта, — и сигналинг молча не находит SFU. В обоих `docker-compose.test-*.yml` переменная задана; при заведении нового стека её легко забыть, а симптом (страница открывается, связь не устанавливается) на причину не указывает.
- Флаг сервиса в реестре включён миграцией `core/0003_enable_conference`; на боевой БД с `RUN_MIGRATIONS=0` её нужно применить руками (`manage.py migrate core`) либо флипнуть `manage.py service conference --on`.
- **Приглашения по ссылке и внешние участники.** `ConferenceInvite` (`apps.cms`, миграция `cms/0005_conference_invites`) + `/api/cms/v1/conference/invites*`. Ссылка вида `/join/<token>` ведёт на публичную страницу: сотрудника она сразу отправляет в комнату, гостю предлагает назваться и выдаёт **гостевой JWT** (`htqweb/authn/jwt.py::issue_guest_token`). Тот подписан общим `JWT_SECRET` — иначе SFU его не примет, — но `token_type="guest"` закрывает ему всё API платформы (`htqweb.http._authenticate_jwt` пускает только `access`), а claim `room_id` привязывает к ОДНОЙ комнате: `sfu/src/auth.ts::guestMayJoin` + `mayEnterRoom` в `server.ts` проверяют это на обоих входах (`join_room`, `joinRoom`). Гостевой токен намеренно не несёт `user_id` — вторая линия обороны: `TokenPayload` без него не собирается. Отправка ссылки — `POST invites/<id>/send` (почта через `django.core.mail`, уведомление через `apps.messenger.interface`, каналы независимы), встреча в календаре создаётся фронтом обычным `event_type="conference"` + `conference_room_id`.
- **Запись, история и протокол.** Аппка **`apps.conference`** (`/api/conference/v1/*`) — имя `conference` в `KNOWN_SERVICES` перестало быть «зарезервированным без аппки». Запись **автоматическая на каждой встрече** и ведётся **поучастниково**: `sfu/src/recording.ts` вешает `PlainTransport` на каждый producer, ffmpeg ремуксит поток в `.mkv` (`-c copy`, без перекодирования — CPU почти не тратится) на общий том `conference_raw`. `.mkv`, а не `.webm`: комната поддерживает и H264, который webm при `-c copy` не принимает. Из подорожечной записи **бесплатно следует протокол** — аудио каждого лежит отдельным файлом, поэтому «кто говорит» известно из имени файла и диаризация не нужна вовсе. Сведение в одно mp4 и распознавание (faster-whisper, `WHISPER_MODEL=medium`, аудио не покидает периметр) делает **отдельный контейнер `backend-media-worker`** (`backend/Dockerfile.media`, очередь `conference_media` через `CELERY_TASK_ROUTES`) — общий `backend-worker` запущен без `-Q` и этих задач не видит, а ffmpeg с ctranslate2 не утяжеляют остальные пять backend-образов. **Ретенция 25 дней** (`CONFERENCE_RETENTION_DAYS`): `purge_expired` стирает медиа из S3 и ставит `recording_state="purged"`, но история встречи, участники, события и текстовый протокол остаются НАВСЕГДА. Отдельное состояние вместо удаления строки — чтобы интерфейс отличал «не писали» от «записали и вычистили по сроку».
- **Канал SFU → Django обязателен к настройке.** `CONFERENCE_INTERNAL_TOKEN` (заголовок `X-HTQ-Internal-Token`, не JWT — у SFU нет пользователя). **Пустой секрет ЗАКРЫВАЕТ приём, а не открывает всем**, поэтому без него не будет ни истории, ни записей. Связь односторонняя и необязательная: недоступный Django не ломает звонок (всё через `sfu/src/fallback.ts`, `expected=false`). Все `internal/*`-ручки идемпотентны — сеть между контейнерами теряет ответы, и повтор не должен ни раздваивать встречу, ни запускать вторую сборку.
- **Плеер записи ходит по подписи, а не по JWT.** `<video src>` не отправляет `Authorization`, поэтому `GET /sessions/<id>/recording` объявлен `auth=None` и проверяет `?sig=&exp=` (`apps/conference/services/signing.py`, общая схема с `htqweb/storage/signed_url.py`); ссылку выдаёт карточка встречи, где права уже проверены. Отдаётся **302 на presigned-адрес**, а не байты через Django: иначе теряется `Range`, то есть перемотка по часовому видео. ⚠️ При правке этих вьюх помните, что `api_view(auth=None)` НЕ разбирает токен — `request.token` заполняется вручную в `_authorize_media`, иначе «вторая дверь» по JWT только нарисована.

**Frontend** (`cd frontend`):
```bash
npm run dev            # vite dev server :3000
npm run build          # vite build (+ bundle-size budget check in postbuild)
npm run lint           # eslint
npx tsc --noEmit -p tsconfig.json   # typecheck (use this to verify changes)
npm test               # vitest run
npx vitest run <file> -t "<name>"   # single test
npm run test:e2e       # playwright
```
Playwright: the chromium binary isn't installed; launch with `{ channel: 'msedge' }` (Edge ships on the Windows host).

**Backend tests** (`cd backend`): pytest-django against **real Postgres** (no SQLite), on a dedicated host port because neither existing route works (`:5432` is a native Windows Postgres install, `:6432`/PgBouncer is transaction-pooled and can't `CREATE DATABASE`). Bring the port up once, then run the suite:
```bash
docker compose -f docker-compose.test-local.yml up -d db   # ТОЛЬКО Postgres на :55432 (НЕ docker restart!)
cd backend
./.venv/Scripts/python.exe -m pytest -q                                   # whole suite
./.venv/Scripts/python.exe -m pytest apps/hr/tests/test_x.py::test_name   # single test
```
`DJANGO_SETTINGS_MODULE=htqweb.settings.test` and `JWT_SECRET` are both fixed by `pytest.ini`/`settings/test.py` — nothing to export by hand. Full detail (including the `max_connections=300` bump): [backend/README-tests.md](backend/README-tests.md).

⚠️ **The interpreter is `backend/.venv`, not the repo-root `.venv`.** Both exist. The root one carries Django 6.0.2 and is NOT the project environment: every command run through it dies at import with 155 `ImproperlyConfigured` collection errors, which looks like a broken test suite rather than a wrong interpreter. `backend/.venv` has the pinned Django 5.2.7. All commands in this section are relative to `backend/`, hence `./.venv/…`.

**Django management** (`cd backend`, same venv):
```bash
./.venv/Scripts/python.exe manage.py makemigrations <app>   # after model changes
./.venv/Scripts/python.exe manage.py migrate
./.venv/Scripts/python.exe manage.py service <name> --on|--off [--message "..."]   # ServiceStatus switch
./.venv/Scripts/python.exe manage.py etl_<domain> [--dry-run] [--verify] [--limit N]  # phase-10 legacy-data cutover
./.venv/Scripts/python.exe manage.py seed_tasks_demo [--purge|--wipe|--wipe-only]  # demo data, local DB only
./.venv/Scripts/python.exe manage.py mail_check [--mailbox ADDR] [--password PW] [--send-to ADDR]  # corporate-mail diagnostics
```
Mail-server credentials live in **two layers**: `MailServerConfig` (one DB row, edited at `/admin/mailboxes` → «Подключение») **over** the env vars, merged by `apps/mail/services/mail_config.py` with the rule *empty field in the DB = take it from env*. Never read `settings.IMAP_HOST` (or any other `MAILCOW_*`/`IMAP_*`/`SMTP_*`) directly from `apps/mail` — go through `mail_config.get_config()`, or UI-set values will be silently ignored.

`mail_check` is the first thing to run when corporate mail misbehaves: it prints the resolved config (provisioner mode, domain, IMAP/SMTP targets), then checks each link **in dependency order** — port reachable → IMAP connect → login → folders (including whether `MAIL_SYNC_FOLDERS` actually exist on that server, the usual `Sent` vs `Sent Items` trap) → SMTP connect → SMTP login. The first failure stops the chain so you get the one real cause instead of derived errors, and every failure carries the concrete fix. Without `--mailbox` it needs no secrets at all (config + tunnel only); `--password` is optional for an already-provisioned mailbox (the stored one is decrypted from the DB). Passwords never appear in the output. Exits non-zero on any failure, so it works in scripts.

`seed_tasks_demo` fills the whole five-level hierarchy (project → site → block → roadmap → task) plus volumes, resource requirements, dated daily reports and per-block **staff reports** (`ProjectStaffReport` — headcount by work role, deliberately seeded above/below/at the `ResourceRequirement` plan, with one stopped site so the board shows a real shortfall); it needs `seed_hr_demo` to have run first (it reads departments/employees through `apps.hr.interface`). `--purge` removes only what it seeded, `--wipe` TRUNCATEs every table of the `tasks` app and re-seeds — including restoring the five system `TaskType` rows that migration `0002` had put there.

**Reaching the dev database from the host**: `manage.py` defaults to `localhost:6432` (PgBouncer), whose credentials fail SASL from the host. Use the unpooled port instead — same server, dev database:
```bash
cd backend
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 \
  DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 \
  ./.venv/Scripts/python.exe manage.py <command>
```
(`:55432` comes up with `docker compose -f docker-compose.test-local.yml up -d db`. `PYTHONIOENCODING=utf-8` is needed or Russian output comes out mojibake on the Windows console.)

## Architecture invariants (the load-bearing ones)

- **One Django backend, domains are apps.** `backend/apps/{users,cms,media_files,hr,mail,messenger,tasks,approvals,contracts,signoff,core}`. Two of those post-date the migration and have no FastAPI ancestor: **`contracts`** (`/api/contracts/v1`, budgets/counterparties/agreements) and **`signoff`** (`/api/signoff/v1`, generic multi-stage approval over *other apps'* rows — **not** `apps.approvals`, which is a form designer approving its own `RequestInstance`s; see STRUCTURE.md §3.6). `apps.core` is the only shared foundation (JWT/service-registry primitives live in `htqweb/`, not in an app); every other app talks to a neighbour ONLY through that neighbour's `apps.<x>.interface` module — never its `models`/`services` directly (enforced by the isolation test above).
- **API layer is hand-rolled Django, not DRF.** `htqweb.http.api_view` (`methods=`, `auth="jwt"|"admin_session"|None`, optional Pydantic `body=`, `admin=True` gate) decorates views; the error envelope is always `{"detail": ...}` (401/403/404/422/500/503), matching the old FastAPI contract. Pydantic schemas (`apps/<domain>/schemas.py`) carried over from the FastAPI services essentially as-is and still do request/response validation.
- **URLs auto-mount by convention.** An app declares `API_PREFIX = "api/<domain>/v1/"` on its `AppConfig` (`apps/<domain>/apps.py`) and defines `apps/<domain>/urls.py`; `htqweb/urls.py` discovers every installed app with that attribute and mounts it — adding a domain never touches `htqweb/urls.py`. `APPEND_SLASH = False`, so `urls.py` registers both the slashed and bare spelling of a path wherever the frontend might send either.
- **Business logic lives in `apps/<domain>/services/<file>.py`.** `views.py` are thin dispatchers (parse → call service → shape response). Look in `services/`, not in views, for behavior.
- **JWT issuer is still `htqweb-auth`.** There's no separate user-service anymore — `apps.users` both issues (`htqweb/authn/jwt.py`, called from `apps.users.views`) and every app validates tokens locally via the same shared `JWT_SECRET`/HS256, in-process, no network call. Claims are unchanged: `sub, user_id, username, email, is_staff, is_superuser, is_admin, token_type, iat, exp, iss`.
- **Apps are disableable at runtime**, same mechanism as before the merge, just in-process now: `apps.core.models.ServiceStatus` (one DB row per domain, 5s-cached) + `htqweb.middleware.service_gate.ServiceGateMiddleware` (gates `/api/<prefix>/` and `/ws/.../` by URL prefix) + `apps.core.services.require_service("<name>")` (the in-process gate — first line of every `interface.py` function and every Celery task) + `htqweb.admin_gate.ServiceGatedAdminMixin` (gates that app's models in `/django-admin/`). Flip one with `manage.py service <name> --on/--off`. A disabled dependency surfaces as 503 `{"detail", "code": "service_disabled", "service"}` everywhere — HTTP edge, an in-process `interface` call turned into `ServiceDisabled`, or `django-admin` (which fails the Django-native way: `PermissionDenied`, not a JSON body).
- **Processes** (`docker-compose.yml`, all built from the same `backend/Dockerfile` image, differing only in `command`): `backend-web` (gunicorn/WSGI — all of `/api/*`, `/django-admin/`, static; the **only** process that runs `migrate` + seeds the `admin`/`admin12345` account, gated by `RUN_MIGRATIONS=1`), `backend-asgi` (uvicorn/ASGI — SSE `/api/requests/v1/stream` + WebSocket `/ws/`; messenger's Socket.IO mounts at `ws/messenger/socket.io`), `backend-worker` (Celery), `backend-beat` (Celery beat, `django-celery-beat` DB-backed scheduler), `flower` (Celery monitoring UI). Broker/result backend is Redis. Every Celery task's first line is `require_service("<app>")`.
- **nginx (`infra/nginx/default.conf`) is the gateway**: two upstreams, `backend` (WSGI, everything else) and `backend_asgi` (the SSE route + `/ws/`). In dev, Vite's proxy (`frontend/vite.config.ts`) mirrors that split — every `*ServiceTarget` variable it defines now resolves to the same `VITE_BACKEND_TARGET` (the per-service names only survive because the proxy rule table still keys off them).

## Postgres — direct connection now; PgBouncer is legacy-shaped history

- **Django talks straight to Postgres**: `DB_HOST=db`, `DB_PORT=5432` (psycopg, sync), `CONN_MAX_AGE=0` — pooling is app-level, not a shared external pooler. PgBouncer (`:6432`) is still in the compose file for host-side tooling/manual `psql`, but it is **not** in the live request path anymore.
- **History (no longer applies — here so old scars make sense if you trip over them):** the FastAPI generation put every service behind PgBouncer in transaction-pooling mode, which silently drops `search_path`, so all 8 Python services (except `user`→schema `auth`) actually lived in schema `public` with a table-name-prefix convention (`hr_*`, `task_*`, `request_*`, `cms_*`, `email_*`), and Alembic needed a fresh-thread-per-migration dance to survive the pooler. None of that applies to Django: one schema (`public`), natural table names (`<app>_<model>`), `managed=True`, plain `makemigrations`/`migrate`.
- **Tests need a real, unpooled Postgres** — `CREATE DATABASE`/`DROP DATABASE test_htqweb` cannot pass through PgBouncer's transaction pool. That's what host port `:55432` (the `db` service of `docker-compose.test-local.yml`) is for; see [backend/README-tests.md](backend/README-tests.md).

## Мультикомпанейность — схема на компанию

Компании группы изолированы **схемами Postgres**, а не столбцом `company_id`: `settings.TENANT_APPS = ("hr", "tasks", "contracts", "signoff")` живут в `co_<slug>` (дефис в slug заменяется на `_` — идентификатор Postgres дефис не допускает, `htqweb/tenancy/context.py::schema_for`), всё остальное — в `public`. Разводит их `search_path`, который на каждый запрос ставит `CompanyContextMiddleware` (`htqweb/middleware/company_context.py`) по заголовку `X-HTQ-Company` (его кладёт nginx, вытащив поддомен регуляркой — комментарий над `server_name` в `infra/nginx/default.conf` объясняет, почему она нарочно отсекает `www`, IP и голый домен второго уровня). **Модели tenant-аппок поэтому НЕ содержат поля компании — не добавляйте его**: изоляция обеспечивается СУБД, а не дисциплиной разработчика, и это ключевое, намеренное следствие выбора схем.

- **Контекст компании обязателен, а не подставляется.** `htqweb.tenancy.current_company()` поднимает `NoCompanyContext`, если контекст не установлен, — молчаливый откат на `public` дал бы «успешно отработавший» код, не нашедший ни одной строки. Сам `CompanyContextMiddleware` при этом оставляет `search_path=public`, если заголовка `X-HTQ-Company` вообще нет (общие домены вроде `users`/`cms`, переходный период до полного перевода фронта на поддомены) — падает только код, который реально спросил компанию.
- **Токен несёт claim `company`**, и `api_view` отвергает запрос кодом 403, если он не совпадает с компанией, резолвленной из поддомена, — вторая линия обороны: поддомен подделать тривиально, подпись токена — нет.
- **Два независимых рубильника.** `apps.core.models.ServiceStatus` гасит домен на всей платформе; `apps.companies.models.CompanyModule` — у одной компании. `CORE_MODULES` (`apps/core/services.py`: `users, companies, core, hr, messenger, media, cms`) — обязательное ядро, у каждой компании оно есть всегда и `CompanyModule` на него не действует. Оба слоя объединяет `apps.core.services.service_status()`, а не только `require_service()`: HTTP-гейт (`ServiceGateMiddleware`) спрашивает именно `service_status()`, и будь компанейский рубильник только внутри `require_service()`, запрос к аппке с выключенным у компании модулем прошёл бы этот гейт насквозь — вьюхи вызывают свои сервисы напрямую, а не через `interface.py`.
- **В Celery компания передаётся явно.** `@company_task` (`htqweb/tenancy/celery.py`) разворачивает именованный kwarg `company_slug` в контекст; без него — `MissingCompanyArgument`, а не молчаливый откат на `public`.
- **Миграции тенантных аппок НЕ идут при старте контейнера.** `RUN_MIGRATIONS=1` в `docker-entrypoint.sh` вызывает `manage.py migrate_shared`, а не голый `migrate`: список общих аппок вычисляется из графа миграций минус `TENANT_APPS`, потому что после `tenancy_bootstrap` голый `migrate` при `search_path=public` счёл бы `hr`/`tasks`/`contracts`/`signoff` непромигрированными и создал бы их таблицы заново — пустыми, поверх боевых данных, уже переехавших в схемы компаний. Схемы компаний доводит `manage.py migrate_companies`, отдельно, во время выкатки. Разные компании штатно стоят на разных версиях, поэтому **любое изменение схемы тенантной аппки — по expand/contract**: обратно-совместимый шаг отдельной миграцией от разрушающего.
- **Сводное чтение холдинга** — схема `holding`, `UNION ALL`-представления по всем действующим компаниям (`apps.companies.services.holding_views`). Каждая tenant-аппка **обязана** объявить `apps/<domain>/holding.py` с `HOLDING_MODELS` (пустым кортежем, если сводить нечего) — отсутствие файла или атрибута роняет сборку `ImproperlyConfigured`, чтобы аппка не выпала из сводок молча. Представления физически **блокируют contract-миграции** (Postgres не даёт удалить столбец или сменить тип, пока от него зависит вьюха), поэтому `migrate_companies` сносит их до прогона и собирает после; заведение, архивация и восстановление компании тоже пересобирают их.

⚠️ **`RUN_MIGRATIONS` в `docker-compose.yml` по умолчанию `1`** (`${RUN_MIGRATIONS:-1}`), и ни `.env`, ни `.env.example`, ни `.env.production` его не переопределяют — «миграции на проде выключены» не гарантировано репозиторием. Перед `tenancy_bootstrap` на бою флаг надо выставить явно.

⚠️ **Осиротевшая строка реестра после неудачного отката `company_create`.** Откат — три независимых шага (`drop_schema`, удаление строки `Company`, `rebuild_holding_views`), каждый через `_cleanup` (см. докстринг `apps/companies/management/commands/company_create.py`). Если `company.delete()` упадёт ПОСЛЕ того, как `drop_schema` уже успешно снёс схему, в реестре останется активная строка компании без физической схемы под ней — и следующий `rebuild_holding_views` (в том же откате или при следующем `migrate_companies`) упадёт, пытаясь собрать `UNION ALL` по несуществующей `co_<slug>`: сводки холдинга не восстановить, пока эта строка не удалена руками. Лечение — удалить осиротевшую строку `Company` (django-admin или `Company.objects.filter(slug=...).delete()`) и повторить `manage.py migrate_companies` (пересобирает представления по оставшимся действующим компаниям).

Полный дизайн: [docs/multi-company-tenancy-design.md](docs/multi-company-tenancy-design.md). Команды: `company_create`, `migrate_companies`, `migrate_shared`, `tenancy_bootstrap` (одноразовый перенос текущих боевых данных в первую компанию через `ALTER TABLE ... SET SCHEMA` — берёт `ACCESS EXCLUSIVE` на каждую таблицу, запускать только в окне обслуживания; `--grant-all`, включён по умолчанию, заводит `CompanyMembership` всем активным пользователям платформы — без него токены выходят с `company: null` и 403 на любой запрос), `company_grant` (выдать/пополнить `CompanyMembership` отдельному пользователю или всем активным, идемпотентно).

## Среды и политика fallback'ов

**Fallback** здесь — место, где вместо настоящего значения подставляется запасное и выполнение продолжается. Такие места молчаливы по своей природе: снаружи подмена выглядит как нормальная работа. Поэтому все они проходят через один примитив, а среды разведены так, чтобы у разработчика подмен не было вовсе.

Ось одна на три рантайма — `HTQ_ENV` (для фронта `VITE_HTQ_ENV`, вшивается в бандл на сборке):

| Среда | `HTQ_ENV` | `DJANGO_SETTINGS_MODULE` | Режим | Как запускается |
|---|---|---|---|---|
| Прод | `production` | `htqweb.settings.base` | `log` | `docker compose up -d` |
| Тестовая (как прод) | `staging` | `htqweb.settings.base` | `log` | `docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d` |
| Разработчик | `development` | `htqweb.settings.dev` | **`strict`** | `docker compose -f docker-compose.test-local.yml up -d` |
| pytest | — | `htqweb.settings.test` | **`strict`** | `pytest` |

- `log` — подмена происходит, **пользователю не видно ничего** (ни в теле ответа, ни в UI): строка `FALLBACK site=… reason=…` в лог + `htqweb_fallback_total{site,expected}`.
- `strict` — подмены **нет**: летит `FallbackNotAllowed` (на фронте `FallbackNotAllowedError` в оверлей Vite), `raise … from exc` сохраняет исходный traceback.
- `FALLBACK_MODE=strict|log` перебивает вывод из среды в обе стороны (включить строгий режим на стенде перед выкаткой; разово ослабить локально). `FALLBACK_LOG_LEVEL` крутит уровень отдельного логгера `htqweb.fallback`.

**Новый fallback пишется только так** — `htqweb/fallback.py`, `frontend/src/lib/fallback.ts`, `sfu/src/fallback.ts` (одинаковый API):

```python
try:
    values = module.collect()
except Exception as exc:
    fallback("core.metrics.app_collect_failed", None,
             reason="сбор метрик аппки упал", exc=exc, app=label)
    continue
```

`site` — статический литерал `<аппка>.<модуль>.<что>`: он уходит в метку метрики, данные туда подставлять нельзя. `expected=True` помечает предусмотренную деградацию (камеры нет, плана нет) — strict её не роняет, лог тише, серия в счётчике отдельная; алерт смотрит только на `expected="false"`.

**Что через него НЕ проходит** (иначе механизм утонет в шуме, и на слово FALLBACK перестанут смотреть): дефолты конфигов из env; штатные лестницы разрешения, срабатывающие на каждый вызов (`apps/hr/services/calendar_service.py::_fallback`, `image_service.detect_mime`); визуальные заглушки на фронте (`|| '—'`, `?? []` во время загрузки); `is_fallback` в `apps.signoff` (предметное понятие «запасной этап маршрута»); `AvatarFallback` из shadcn. Отдельный случай — коллектор `BusinessMetricsCollector.collect()` и `htqweb/gunicorn_conf.py`: там нельзя трогать реестр Prometheus и нет настроек Django соответственно, и в обоих файлах написано почему.

⚠️ **Celery-процессы `/metrics` не отдают** (Prometheus снимает их через Flower), поэтому подмены из задач в метрику не попадают — их закрывает Loki-правило `htqweb-fallback-worker-logs` по подстроке `FALLBACK`.

## Host / Windows environment notes

- Shell is PowerShell 5.1; a Bash tool (Git Bash) is also available. **PowerShell mangles `$`, inner quotes, and JSON** in `docker exec`/`psql` args — route anything with `$`, quotes, or JSON bodies through the Bash tool.
- From the Windows host: **`:6432`** reaches the project DB through PgBouncer (host tooling/manual queries only); **`:55432`** is the direct, unpooled Postgres the test suite uses; host **`:5432`** is a native Windows PostgreSQL install, not the container.
- `DB_NAME=htqweb`, `DB_USER=htqweb`, dev password `change-me` (root `.env`).

## Observability

Prometheus (`infra/logging/prometheus/prometheus.yml`) scrapes **13 jobs**: `django-backend` (WSGI) and `django-asgi`, `celery` (via Flower), `postgres`, `redis`, `node` + `cadvisor` (host and containers), `nginx` (production profile only), `sfu`, `minio`, `loki`, `grafana`, and itself. Retention is 30d **or** 10GB, whichever comes first (`infra/logging/prometheus/Dockerfile`). `PROMETHEUS_ENV` lands in `external_labels` on every series.

**Access is closed in prod, open in dev.** Only Grafana faces the outside, via nginx `/grafana/` with the JWT SSO it already had (superuser→Admin, staff→Editor; dashboards in the **HTQWeb** folder). Prometheus, Loki, Flower and every exporter publish **no host ports** in `docker-compose.yml` — their `ports:` live in the test stacks, so `:9090`, `:3001`, `:3100`, `:5555` work locally and nowhere else. nginx no longer proxies `/prometheus/` at all (it used to, with no auth whatsoever, and Prometheus has none of its own). `GRAFANA_ADMIN_PASSWORD` has no default — Grafana refuses to start without it.

**The backend exposes `/metrics`** (`apps/core/views.py::metrics`, registered in `apps/core/urls.py` next to `/health/`, deliberately outside `/api/` so `ServiceGateMiddleware` can't gate it). `django-prometheus` supplies HTTP/DB/cache metrics; `DATABASES.ENGINE` and `CACHES.BACKEND` are its wrapper subclasses. ⚠️ `backend-web` runs `gunicorn --workers 4`, so metrics use **multiprocess mode**: `PROMETHEUS_MULTIPROC_DIR` (tmpfs) + `htqweb/gunicorn_conf.py` (clears the dir on boot, marks dead workers on `child_exit`). Without that, a scrape hits one random worker of four.

**Business metrics** are per-app: `apps/<domain>/metrics.py` defines `collect()` over its own models, `apps/core/metrics.py` discovers and merges them (same convention as `API_PREFIX` autodiscovery — no cross-app imports, so `test_app_isolation` stays green). They're computed by Celery-beat every 60s into the cache (`apps.core.tasks.collect_business_metrics`), not on scrape, and exported under the `htqweb_*` prefix. An empty cache exports **nothing** rather than zeros — "the collector died" and "zero tasks" must not look alike.

Alerting stays in Grafana (no Alertmanager): 11 Prometheus rules + 5 Loki rules in `infra/logging/grafana-provisioning/alerting/`. Delivery is Telegram for everything, plus email as a second independent channel on `severity=critical` — secrets via `GF_TELEGRAM_*` / `GF_SMTP_*` (see `.env.example`). `scripts/generate-monitoring-traffic.sh` targets the Django backend and works as-is.
