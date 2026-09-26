# STRUCTURE.md — навигационная карта проекта HTQWeb

Путеводитель по репозиторию для людей и ИИ-агентов: где что лежит, по каким правилам устроены каталоги, куда смотреть в первую очередь. Цель — не сканировать весь проект. Актуализировано под завершённый cutover (единый Django-backend). Дата сверки — 2026-09-02 (раздел «Наблюдаемость» переписан полностью: он утверждал вещи, которых уже не было); 2026-09-24 — сверка с кодом после блоков A–I.2 рефакторинга структуры группы (§3.2, §3.7, §4, §6–§8).

> Дополняющие документы: [README.md](./README.md) (как поднять), [API.md](./API.md) (роутинг и контракты), [backend/README.md](./backend/README.md) (анатомия Django-аппки), [docs/architecture.md](./docs/architecture.md) (заметки по слоям — местами не в ногу с реальным деревом, см. предупреждение в CLAUDE.md).

---

## 1. Что это за проект

Внутренняя enterprise-платформа Hi-Tech Group. Прошла полный круг: изначально Django-монолит → мигрирована (Strangler Fig) в ~9 FastAPI-микросервисов → и теперь **обратно смёрстана в один Django-backend** (`backend/`, реверс-миграция завершена — журнал в [PLAN.md](./PLAN.md)). Фронтенд — React + Vite SPA, не менялся.

**Стек:**
- **Frontend:** React 18 + Vite + TypeScript, shadcn/ui (Radix+Tailwind), TanStack Query, i18next. Тесты: Vitest + Playwright.
- **Backend:** Django 5.2.7 (Python 3.14), Celery 5.6 (Redis-брокер, `django-celery-beat`/`django-celery-results`), API-слой — собственное ядро `htqweb.http.api_view` (не DRF).
- **Данные:** PostgreSQL — **одна схема `public`** для большинства аппок, обычные Django-таблицы `<app_label>_<model>` (никаких схем-на-сервис и префиксов-руками — это была PgBouncer-специфика FastAPI-эпохи, см. §7); исключение — `hr`/`tasks`/`contracts`/`signoff`, которые с введением мультикомпанейности живут в отдельной схеме `co_<slug>` на каждую компанию (см. §3.7). MongoDB **убрана вместе с FastAPI-поколением** — HR-документы, ранее лежавшие в Mongo, теперь обычные Django-модели.
- **Шлюз:** Nginx как API Gateway (два upstream'а — WSGI и ASGI, см. §6).
- **Видео:** Mediasoup SFU + WebTransport (Node/Python, не тронуты миграцией).
- **Опц.:** LibreTranslate (перевод оргдерева HR, compose-профиль `translation`).
- **Логи:** Loki/Promtail/Grafana.

---

## 2. Дерево верхнего уровня

```
HTQWeb1/
├── frontend/             # React + Vite SPA (см. §4) — без изменений
├── backend/               # ⭐ ЕДИНЫЙ Django-backend (см. §3)
│   ├── htqweb/            # Проектный пакет: settings/, urls.py, asgi.py/wsgi.py,
│   │                       #   authn/ (JWT), http.py (api_view), middleware/, storage/,
│   │                       #   tenancy/ (контекст компании и схема Postgres, см. §3.7),
│   │                       #   fallback.py (громкие подмены, см. §8)
│   ├── apps/               # Доменные Django-аппки — units изоляции (см. §3.1)
│   ├── manage.py   requirements.txt   pytest.ini   conftest.py
│   ├── Dockerfile   docker-entrypoint.sh
│   ├── README.md          # ⭐ Анатомия аппки + правила (заменяет снесённый services/README.md)
│   └── README-tests.md    # Как поднять тестовый Postgres на :55432 и гонять pytest
├── infra/
│   ├── nginx/default.conf  # ⭐ API Gateway: вся маршрутизация /api/* → backend/backend_asgi
│   ├── db/init-ltree.sql   # Инициализация ltree-расширения PG
│   ├── logging/            # Loki + Promtail + Grafana + Prometheus provisioning
│   └── certs/              # Локальные TLS (gitignored)
├── sfu/                  # Mediasoup SFU (Node.js, медиа-роутинг конференций)
├── webtransport/         # QUIC signalling proxy (Python aioquic) для SFU
├── docs/                 # Архитектура, аудиты, ngrok/tunnel-инструкции; deploy/subdomains-runbook.md —
│                         #   чеклист перевода компаний на поддомены (DNS, сертификат, порядок окна выкатки)
├── scripts/              # PS/JS/bash-утилиты (TLS, firewall, туннели, monitoring traffic)
├── tools/                # Локальные бинари туннелей (gitignored)
├── docker-compose.yml       # Прод-стек (полный)
├── docker-compose.test-local.yml  # Тест-стек: Vite HMR + Postgres в контейнере (:55432)
├── docker-compose.test-env.yml    # Тест-стек: Vite HMR, БД из .env (миграции по умолчанию OFF)
├── README.md   API.md   PLAN.md (журнал миграции, читать как историю, не как план "что впереди")
└── dev-up.sh                      # Обёртка над docker-compose.test-local.yml
```

> ⚠️ Игнорировать на верхнем уровне: пустой `nginx/` (авторитетный конфиг только `infra/nginx/default.conf`), корневые `node_modules/`/`package.json` (служебный tooling, не фронтенд).
>
> ⚠️ **Compose-файлов ровно три, и они самостоятельные** — запускаются одиночным `-f <файл>`, без цепочки `-f a -f b`, и НЕ наследуют друг друга. Следствие: правка сервиса, общего для сред (redis, minio, backend-*, grafana…), должна повторяться во всех трёх. Перед коммитом сверяйте `git diff docker-compose*.yml`. Старые `docker-compose.dev.yml`, `docker-compose.localdb.yml`, `docker-compose.test.yml`, `docker-compose.django.yml` удалены.

---

## 3. Backend — Django-аппки (`backend/apps/`)

**Правило изоляции (важно, исполняемое):** сосед обращается к аппке **только** через её `apps.<x>.interface` — прямой импорт `apps.<x>.models`/`apps.<x>.services` из другой аппки запрещён и ловится тестом [`apps/core/tests/test_app_isolation.py`](./backend/apps/core/tests/test_app_isolation.py) (сканирует все `.py`, включая сам `interface.py`). Исключение — `apps.core`: общий фундамент (реестр отключаемости), его можно импортировать откуда угодно. Источник правды по анатомии аппки — [backend/README.md](./backend/README.md).

### 3.1 Карта аппок

| Аппка (`backend/apps/`) | URL-префикс (`API_PREFIX`) | Имя в реестре `ServiceStatus` | Домен |
|---|---|---|---|
| **core** | — (примонтирована в корень `htqweb/urls.py`, свой префикс `api/core/v1/` объявляет сама) | — (сам реестр) | `/health/`, `/health/ready/`, `/api/core/v1/services/`; общий ETL-хелпер (`etl.py`) |
| **users** | `api/users/v1/` | `users` | Identity, JWT issuer+validator, профиль, регистрация, админ-юзеры, items |
| **hr** | `api/hr/v1/` | `hr` | Сотрудники, отделы, должности (`is_manager`/`external_hierarchy` — руководящая должность и участие во внешней иерархии между компаниями, `substitutes_for` — матрица замещения, `participant_position()` — ОСУ через `services/participant_service.py`), вакансии, табель, документы, аудит, оргдерево, PMO, **десять кадровых предметов согласования** (`approval_hooks.py` — объявление и регистрация из `HrConfig.ready()`, `services/approval_service.py` — отправка на согласование через `apps.signoff.interface`), сводка по группе для холдинга (`holding_models.py` — читатели `holding.hr_*`, `services/holding_service.py`, блок H). **Права** — `rbac.py` (`NodeAccess`: проверка по узлу реестра `apps.access` через старые ключи `permissions.py` и таблицу `legacy_roles.py::KEY_TO_NODE`; единственная модель прав домена с блока I); `access.py` — НЕ модель прав, а эвристика переноса (`classify_hr_level` для `interface.list_positions_hr_levels` → `access_backfill_positions`; сторож `tests/test_single_rbac_guards.py`) |
| **tasks** | `api/tasks/v1/` | `tasks` | Workflow-движок Jira+SharePoint (см. §4.2); сводка по группе для холдинга (`holding_models.py` — читатели `holding.tasks_*`, `services/holding_service.py`, блок H) |
| **approvals** | `api/requests/v1/` | `approvals` | ⭐ Lark-style конструктор форм и реестр заявок (см. §3.4); согласует их `signoff`. Префикс URL (`requests`) и app_label (`approvals`) сознательно расходятся — см. `apps/approvals/urls.py` докстринг |
| **cms** | `api/cms/v1/` | `cms` | Новости, категории/теги, contact-requests, ConferenceConfig |
| **media_files** | `api/media/v1/` | `media` | ⭐ Общее файловое хранилище — единая точка входа для аватарок, HR-документов, вложений мессенджера и почты (см. §7.1). `AppConfig.label = "media_files"`, но реестр знает его как `media` |
| **mail** | `api/email/v1/` | `mail` | Дуальная почта: Mailcow + OAuth Gmail/Outlook (см. §4.1) |
| **messenger** | `api/messenger/v1/` | `messenger` | Чат, Socket.IO (ASGI), presence, E2EE-ключи |
| **contracts** | `api/contracts/v1/` | `contracts` | Бюджеты (программа × статья расходов × администратор), реестр контрагентов, договоры с контролем остатка бюджета (см. §3.5). Единственная аппка, появившаяся уже после обратной миграции — FastAPI-предка у неё нет |
| **signoff** | `api/signoff/v1/` | `signoff` | ⭐ **Единственный движок согласования** платформы: многоэтапное согласование ЧУЖИХ строк — документов `contracts` и заявок `approvals` (см. §3.6) |
| **conference** | `api/conference/v1/` | `conference` | ⭐ История видеоконференций, записи и протокол (см. §5). Данные заводит SFU через `internal/*`, а не пользователь |
| **companies** | `api/companies/v1/` | `companies` | ⭐ Реестр компаний группы и мультикомпанейность — схема Postgres на компанию (см. §3.7). Часть `CORE_MODULES`: на уровне компании не выключается, только глобально |
| **access** | `api/access/v1/` | `access` | Роли «функция × глубина» (`services/resolve.py`), должность → роли (штатный путь) / личное назначение (исключение), `/me`. `services/hierarchy.py` считает `subordinate_companies` (кто НИЖЕ по владению, блок B); `services/inheritance.py` — обратный обход: должность, помеченная `serves_subsidiaries`, несёт свои роли из компании-предка вниз во все компании ниже по дереву (блок C, `inherited_from` в `/me`); `services/holders.py` — кто держит роль, включая держателей из компаний-предков (его же переиспользует ручка `apps.companies` `external-holders`). `self_service.py` — реестр «какие аппки под гейтом `api_view(module=)`» и «каким их ручкам гейт не положен» с причиной `self`/`open`/`scoped` (сторож `tests/test_gate.py`); `management/commands/access_backfill_positions.py` (кадровые уровни → роли должностей `hr-*`, `--dry-run`, идемпотентно) и `access_backfill_basic.py` (`employee-basic` каждому участнику компании) — перенос данных блока I, порядок выкатки в roadmap §7 |

Полный список канонических имён сервисов — `apps.core.models.KNOWN_SERVICES`. Имя `conference` долго стояло там «про запас», под SFU-стек без своей Django-аппки; теперь аппка есть (`apps.conference`, §5), и флаг гейтит уже её маршруты.

### 3.2 Анатомия одной Django-аппки

```
backend/apps/<domain>/
├── __init__.py
├── apps.py            # AppConfig; API_PREFIX = "api/<domain>/v1/" — по нему автодискавери
│                       # монтирует urls.py в htqweb/urls.py (никаких ручных include())
├── models.py           # Django ORM, managed=True, обычные таблицы <app_label>_<model>
├── schemas.py          # Pydantic DTO (request/response) — перенесены из FastAPI почти без изменений
├── services/           # ⭐ Бизнес-логика (искать тут, не в views.py), 1 файл = 1 подсистема
├── views.py             # HTTP-вьюхи — тонкие (parse → service → shape), задекорированы @api_view
├── urls.py              # path()-роуты; APPEND_SLASH=False → регистрируются ОБА написания
│                       # (со слешем и без), если фронт может дёрнуть любое
├── interface.py         # ⭐ Публичный API для ДРУГИХ аппок — единственная точка входа соседа.
│                       # Каждая функция начинается с require_service("<name>"); отдаёт только
│                       # dict/примитивы, никогда ORM-объекты
├── admin.py             # django-admin ModelAdmin, обычно обёрнутые в
│                       # htqweb.admin_gate.ServiceGatedAdminMixin (гейт по реестру)
├── tasks.py              # @shared_task (Celery); первая строка каждой — require_service("<name>")
├── migrations/           # Django-миграции (makemigrations/migrate, никакого Alembic)
├── management/commands/  # etl_<domain>.py (разовый перелив legacy-данных, фаза 10) + прочие команды
└── tests/                # pytest-django
```

**Запомнить:**
- Бизнес-логика — всегда в `services/<file>.py`. `views.py` её только вызывает.
- API-слой — `htqweb.http.api_view` (декоратор), НЕ Django REST Framework: `methods=`, `auth="jwt"|"admin_session"|None`, опц. `body=<PydanticModel>`, `admin=True` (гейт через `htqweb.authn.rbac.require_admin`), **`module="<аппка>", level="read"|"write"|"admin"`** — прикладной гейт «модуль × уровень» по ролям `apps.access` в контексте компании запроса (единственная модель прав; правило описано один раз в [API.md](./API.md) § Authorization). Ручка без `module=` в переведённой аппке допустима только с записью в `apps/access/self_service.py`. Конверт ошибок — всегда `{"detail": ...}`.
- JWT: issuer `htqweb-auth` (см. `htqweb/settings/base.py::JWT_ISSUER`) — не путать с доменом `users`, который его лишь выпускает/валидирует. Проверка — `htqweb/authn/jwt.py`, HS256, общий `JWT_SECRET`.
- Отключаемость: `apps.core.models.ServiceStatus` (строка на аппку) + `htqweb.middleware.service_gate.ServiceGateMiddleware` (гейт по URL-префиксу `/api/...`, `/ws/...`) + `apps.core.services.require_service()` (внутрипроцессный гейт — обязателен первой строкой в `interface.py` и `tasks.py`) + `htqweb.admin_gate.ServiceGatedAdminMixin` (гейт `django-admin`). Переключатель: `python manage.py service <name> --on/--off`. Поверх глобального — второй слой на уровне компании: `apps.companies.models.CompanyModule` (кроме `CORE_MODULES`), оба слоя сводит `apps.core.services.service_status()` — его спрашивают и middleware, и `require_service()` (см. §3.7, CLAUDE.md «Два независимых рубильника»).

### 3.3 Как добавить новую аппку/домен

```bash
cd backend
../.venv/Scripts/python.exe manage.py startapp <domain> apps/<domain>   # каркас Django (интерпретатор — корневой .venv)
# затем: добавить "apps.<domain>" в INSTALLED_APPS (htqweb/settings/base.py),
#        API_PREFIX = "api/<domain>/v1/" в apps/<domain>/apps.py (автодискавери сделает остальное),
#        имя сервиса — в apps.core.models.KNOWN_SERVICES + htqweb.middleware.service_gate.PREFIX_TO_SERVICE
#        (+ APP_LABEL_TO_SERVICE, если app_label ≠ имени в реестре, как у media_files/approvals/mail),
#        interface.py с require_service() в каждой функции,
#        ServiceGatedAdminMixin на все ModelAdmin в admin.py.
```
Подробный чек-лист и объяснение каждого шага — [backend/README.md](./backend/README.md).

### 3.4 Approvals — конструктор форм и реестр заявок

`apps.approvals` (URL-префикс `api/requests/v1/`, app_label `approvals`) — no-code конструктор **форм**, вдохновлён Lark Approvals, и реестр поданных по ним заявок. Самый большой перенесённый домен Потока B.

**Собственного движка согласования у неё больше нет.** Заявку (`RequestInstance`) согласует `apps.signoff` — тот же движок, что согласует договоры: модель наследует `signoff.Approvable`, регистрируется в `apps/approvals/approval_hooks.py` из `ApprovalsConfig.ready()` и получает результат колбэками, которые двигают её `status`. Маршрут живёт в signoff **в области шаблона** (`scope = template:<id>`): у отпуска и у закупа согласующие разные, хотя тип объекта один. Отсюда:

- **`status` и `approval_state` — две оси**, как у договора: первая про жизненный цикл заявки, вторая про место в согласовании (и она же запирает правку — `assert_editable`);
- **`workflow_json` больше не исполняется.** Он остаётся в старых версиях шаблонов ради истории и конвертера `manage.py migrate_workflows_to_signoff`, который переводит графы в маршруты signoff и перезапускает заявки, застигнутые «на согласовании»;
- **факты для ветвления — поля формы**, а у виджета `budget_line_ref` ещё и администратор/программа/страна бюджета (через `contracts.interface`), так что маршрут закупа ветвится «по администратору бюджета», не зная про contracts ничего.

- **Сервисы (`apps/approvals/services/`):** `form_schema.py`/`template_validation.py`/`value_validation.py`/`template_data_table.py`/`template_settings.py` (формы и справочники), `budget_line_refs.py` (виджет строки бюджета — единственная дверь в contracts), `instance_service.py`/`request_runtime.py` (черновик и отправка в signoff), `hydration.py`, `permissions.py`, `stats_rollup.py`, `audit.py`, `sse.py` (поток `/stream`, публикация — из колбэка `on_event`). Наследие старого движка: `workflow_engine.py`/`workflow_schema.py`/`condition_eval.py`/`assignee_resolver.py` — их читает только конвертер `workflow_convert.py`.
- **Роуты:** `instances/` (+ `<id>/submit|resubmit` — отдают карточку процесса signoff; решения принимаются в `/api/signoff/v1/tasks/*`), `templates/` (+ `versions`, `preview`, `activate`/`deactivate`), `projects/` (+ `members`), `stats/{overview,by-project,by-template,by-actor,heatmap}`, `reference-sources/` (Lark-Base-style справочники, + `rows/`, `access`, `my-data-tables`, `by-slug/<slug>/options`), `stream` (SSE).
- **SSE:** `/api/requests/v1/stream` обслуживается **ASGI-процессом** (`backend-asgi`) через обычную async-вьюху (`StreamingHttpResponse`), не через `asgi.py`-обёртку — см. `apps/approvals/urls.py`.
- **Frontend:** [frontend/src/features/requests/](frontend/src/features/requests/) + [frontend/src/api/requests.ts](frontend/src/api/requests.ts). Шаг «Маршрут» конструктора шаблона — тот же `RouteEditorPanel`, что и на `/signoff/routes/:id` (`TemplateRoutePanel`); карточка заявки использует общие с договорами `SubmitForApproval` и `SubjectProcesses`.

### 3.5 Contracts — бюджеты, контрагенты, договоры

`apps.contracts` (URL-префикс `api/contracts/v1/`) — учёт договоров с контролем бюджета. Отвечает на один вопрос: **сколько из выделенного бюджета уже законтрактовано и сколько осталось.** Frontend — `frontend/src/pages/contracts/*` и `frontend/src/components/contracts/*`: оболочка `ContractsShell` с разделами «Обзор», «Ждёт меня», бюджеты, контрагенты, договоры, предоплаты, оплаты по договорам, АВР, накладные, расходы без договора, подотчёт.

> ⚠️ **Аппка будет заменена.** Модуль БЗО (ТЗ — `docs/tz/TZ-budget-procurement-payments-v1.0.md`, решения — `docs/plans/2026-09-25-bpp-tz-gap-analysis.md` §0) строится **новой** аппкой `bpp`, в которую переезжает вся цепочка (план — `docs/plans/2026-09-26-bpp-master-plan.md`). После переноса открытых документов `contracts` переходит в режим только чтения. Закрытые документы остаются в ней (ответ Q-B36), поэтому удалять аппку можно только отдельным решением. Описание ниже — состояние на 25.09.2026.

Три слоя моделей (`apps/contracts/models.py`):

- **Справочники бюджета** — `Country`, `Program` (название + статья расходов в одной строке; подпись — `display_name`, «код название», код необязателен), `Administrator` (держатель бюджетных строк — **проект + страна**, без ФИО и **без денег на самой записи**; подпись «проект страна» собирает `Administrator.display_name`), `Budget` (выделенная сумма на связку администратор × программа × год, уникальную).
- **Реестр контрагентов** — `Counterparty` (БИН/ИИН, НДС — **булев признак** «с НДС / без НДС», контакты, адрес, страна, статус). В спецификации заказчика таблица называется «Реестр контрактов», но её поля — атрибуты контрагента, а не договора.
- **Контрагент ↔ партнёр.** Партнёр из `apps.tasks` (`Contractor`) — это контрагент в роли исполнителя на объектах. Ссылка живёт на стороне задач: `Contractor.counterparty_id` (необязательная, уникальная), `ContractorEngagement.agreement_id` (договор привлечения — только договор с контрагентом ЭТОГО партнёра, его номер ложится в `contract_no`). Проверки — `tasks/services/contractor_service.py` через `contracts.interface.get_counterparties_brief`/`get_agreements_brief`; у связанной пары один БИН/ИИН. Заводить можно с обеих сторон: партнёра — выбрав контрагента (пустые поля подтягиваются), контрагента — «из партнёра» (`CounterpartyFullCreate.contractor_id`, связь в той же транзакции через `tasks.interface.link_contractor_to_counterparty`). Выключенный сосед стоит подписи в ответе, а не ответа; на записи — честный 503.
- **`Agreement`** — единственная транзакционная сущность. Ссылается на ОДНУ бюджетную строку; администратор и программа читаются через неё, отдельных колонок на договоре нет (иначе было бы две версии правды о том, из какого кармана деньги).
- **Поля договора из ТЗ 9.2.** «Дата договора» = `signed_date` (обязательна в API, по умолчанию сегодня, 01.01.2020 … сегодня + 30 дней — `schemas._check_contract_date`); «Срок действия по» = `end_date` (не раньше даты договора — пара в `htqweb/date_rules.DATE_PAIRS`; после него новые оплаты/предоплаты по договору не заводятся — `Agreement.term_expired_message`, BR-036). Номер уникален не сам по себе, а тройкой «контрагент + номер + дата» (`uq_contracts_agr_cp_number_date`, BR-032; сервис проверяет заранее ради текста). **Позиции** — `AgreementItem` (`services/agreement_items.py`): из строк заявки на закуп (`approvals.interface.get_request_items`, количество ≤ остатка после других договоров, `GET requests/<id>/items`) или вручную; у стандартного договора сумма позиций = сумма договора. Таблицы позиций в форме пока нет, поэтому обязательность позиций при отправке выключена флагом `ITEMS_REQUIRED_FOR_APPROVAL`. Статусы и маршрут ФД → ТД → ОД → ГД (п. 5 ТЗ) не трогались — цепочки в проекте ещё нет.

**Ключевой инвариант: остаток бюджета не хранится.** `committed`/`remaining` считаются в `services/budget_calc.py` как `amount − SUM(договоры в COMMITTING_STATUSES)`. Хранимый баланс, который декрементируют при создании договора, расходится с реальностью при первом же редактировании суммы, удалении или расторжении — и потом нет способа узнать, какая цифра верна. Колонок под эти поля в таблице нет и заводить их не нужно.

`COMMITTING_STATUSES` (там же) — единственное место, где зафиксировано, **с какого статуса договор занимает бюджет**: сейчас всё, кроме `draft` и `terminated`. Это открытый вопрос к заказчику; меняется правкой одного множества, ни модели, ни схемы, ни вьюхи трогать не придётся.

**Согласование подключено — через `apps.signoff`, не через `apps.approvals`.** `Budget`, `Counterparty` и `Agreement` наследуют примесь `signoff.Approvable` (колонка `approval_state` в их собственных таблицах), а `apps/contracts/approval_hooks.py` из `ContractsConfig.ready()` регистрирует три типа с колбэками. Подробности механики — §3.6; здесь важны три следствия:

- **Права изменились.** Создание бюджета/контрагента/договора и отправка их на согласование — `auth="jwt"` (любой сотрудник); правка, удаление, смена статуса и весь справочный слой остались `admin=True`. Контролем служит согласование, а не админский флаг: если завести бюджет может только администратор, маршрут из трёх этапов над бюджетами нечего согласовывать. Скан договора прикладывает автор, пока договор черновик, либо администратор всегда.
- **Несогласованное не расходуется.** `agreement_service._validate_context` отбивает несогласованный бюджет как источник денег и несогласованного контрагента как сторону — **но только если для этого типа заведён активный маршрут** (`signoff.has_active_route`). Без маршрутов ничего не блокируется: все существующие строки — `draft`, и безусловная проверка сломала бы модуль в день выката. Выключенный signoff гейт снимает, а не роняет contracts.
- **У договора две оси состояния.** `status` — жизненный цикл записи, `approval_state` — место в маршруте. Связаны они в одном месте: `approval_hooks` двигает `status` по `ALLOWED_TRANSITIONS` (`draft → on_review` на отправку, `→ approved` на согласование, отказ, возврат на доработку и отзыв возвращают в `draft`). Обратите внимание: `on_review` уже занимает бюджет (`COMMITTING_STATUSES`), поэтому лимит проверяется ДО запуска процесса.
- **Отправленное на согласование не редактируется.** `assert_editable()` стоит первой строкой каждой операции правки и удаления в `services/*.py` (включая строки бюджета — их запирает родительский бюджет) и запрещает её в состояниях `pending`, `approved` и `rejected`; правятся только `draft` и `rework`. Отпирает объект единственная вещь — возврат на доработку (§3.6). Заперто и повторное `/submit`: по решённому объекту он отвечает 409. Механику держит signoff — это семантика ЕГО колонки, — но звать её обязана сама contracts: движок не имеет доступа к чужим таблицам и перехватить запись не может.

Кроме договора, в аппке есть документы расхода, каждый со своим согласованием в signoff:
- счёт без договора — `Invoice`, без номера, занимает бюджет после согласования;
- оплата по договору — `ContractPayment`;
- предоплата — `AdvancePayment`, одна на договор;
- акт выполненных работ — `CompletionAct`;
- товарная накладная — `GoodsInvoice`;
- подотчётные средства и авансовые отчёты — `AccountableFundsRequest`, `AdvanceReport`.

Проведение оплаты бухгалтером (номер проводки + файл платёжного поручения) — отдельное действие после согласования, не этап маршрута. Право на него пока проверяется ключами `Position.permissions` (`contracts.contract_payment.record_payment` и др.), а не ролями `apps.access`; гейта `api_view(module="contracts")` у аппки нет, и сторож `apps/access/tests/test_gate.py` её исключает (`_OUT_OF_SCOPE_APPS`). Разовый перенос реестра заказчика — `manage.py import_cashflow` / `import_cashflow_operations` (`services/cashflow_import.py`, `cashflow_operations_import.py`).

Отложены по-прежнему: несколько файлов на договор, финансирование из нескольких бюджетных строк, мультивалютность.

### 3.6 Signoff — универсальное согласование

`apps.signoff` (URL-префикс `api/signoff/v1/`) — движок согласования, который ничего не знает о предметных аппках. Frontend — [frontend/src/pages/signoff/](frontend/src/pages/signoff/) (инбокс, список и карточка процесса, редактор маршрутов) + [frontend/src/api/signoff.ts](frontend/src/api/signoff.ts).

**Единственный движок согласования платформы.** Согласует и документы
`contracts`, и заявки конструктора `apps.approvals` — она осталась
конструктором форм и реестром заявок, своего движка у неё больше нет
(её `RequestInstance` наследует `signoff.Approvable`, регистрируется в
`apps/approvals/approval_hooks.py` и получает результат колбэками). Единица
согласования у signoff — строка в ЧУЖОЙ таблице, адресуемая парой
`(subject_type, subject_id)`: `"contracts.budget"` + pk, `"approvals.request"`
+ pk. Ни `ContentType`, ни междоменного FK: `ContentType` дал бы обходной
путь к чужим моделям через `content_type.model_class()`.

**Область маршрута (`scope`).** Активный маршрут — один на пару
`(subject_type, scope)`. Пустая область значит «весь тип» (так живут
договоры); непустую называет сама аппка (`Subject.scope_of`) — у заявок это
`template:<id>`, по маршруту на шаблон формы. Схема фактов и ключи
«назначает объект» спрашиваются ПО области: у каждой формы свои поля.

**Четыре вида согласующих** (`ApproverKind`): `position` — HR-должности
(разворачиваются в активных сотрудников на запуске), `initiator` — тот, кто
отправил, `users` — люди, названные поимённо в маршруте, `subject` —
согласующих называет сам объект по ключу из `Subject.approver_fields`
(«администраторы проекта», «из поля формы „Руководитель“»). У этапа
заполнена настройка ровно своего вида — чужая отбивается 409 на сохранении.

**Как перевёрнута зависимость.** Движок не имеет права импортировать `apps.contracts.models`, но обязан уметь две вещи с чужим объектом: сообщить ему результат и показать его человеку. Поэтому предметная аппка сама приходит из `AppConfig.ready()` и отдаёт `signoff.register_subject(...)` три вещи: **класс модели** (signoff ведёт на нём свою колонку `approval_state`), **колбэки** доменных последствий и **`describe`** — способ построить заголовок и ссылку. Импорт идёт только в сторону `contracts → signoff.interface`.

**Модель маршрута.** `ApprovalRoute` → `ApprovalRouteStage` → `ApprovalRouteStageApprover`. Параллельность выражена одним числом: этапы с ОДИНАКОВЫМ `order` идут параллельно, с разным — последовательно. Отдельной модели графа нет намеренно — заказчику нужны «2, 3 или 5 этапов, параллельно или друг за другом», а это ровно то, что выражает целочисленный порядок (ср. `apps.approvals` с его условными переходами — на порядок дороже). Согласующие перечисляются явными user id: платформенных групп нет, `User` сознательно без `PermissionsMixin` (решение Р1 заказчика), поэтому смысл несёт **имя этапа**, а не роль. Активный маршрут на тип — ровно один (частичный уникальный индекс).

**Условные ветки** (`services/conditions.py`). Группа этапов по `order` — она же и ветвление: у этапа есть `condition`, и в процесс он попадает, только если условие сошлось на ФАКТАХ объекта. Отдельной модели ветки нет по той же причине, по которой нет модели графа. Типовой маршрут заказчика — «двое проверяют → согласует ответственный за страну администратора бюджета → один утверждает» — это три группы `order`, во второй по этапу на страну.

- **Факты даёт предметная аппка**, как и всё остальное про чужой объект: `register_subject(..., facts=…, fact_fields=…)`. `facts(subject_id)` снимает плоский словарь скаляров (`{"admin_country_id": 3}`), `fact_fields()` объявляет, что из него можно спрашивать и как показать это в редакторе (тип + справочник значений). Движок сравнивает скаляры и не знает, что такое страна, — поэтому ветвление работает для ЛЮБОГО типа, и включение его для новой модели не требует правок в signoff.
- **Формат условия** — плоский список предикатов, соединённых И: `[{"field", "op", "value"}]`, операторы `eq/in/not_in/gt/gte/lt/lte`. Вложенности и ИЛИ между полями нет намеренно: ИЛИ по одному полю — это `in`, по разным — два этапа в одной группе.
- **Пустая группа — ОТКАЗ на запуске, а не пропуск.** Завели страну, забыли ветку — и бюджет тихо прошёл бы мимо финконтроля, чего никто бы не заметил. Поэтому группа без единого прошедшего этапа роняет запуск (409 с перечислением фактов), а «для прочих — вот этот» выражается явным этапом `is_fallback`. Ту же дыру редактор маршрута показывает заранее (`coverage_gaps` в `GET /routes/{id}`).
- **Ветки считаются один раз, на запуске**, до снимка — как и всё в снимке. Ни правка маршрута, ни правка самого объекта уже идущий процесс не переигрывают. Что именно было решено, видно в `ApprovalProcess.subject_facts` и в `ApprovalProcessStage.condition`/`matched_by`.

**Этап подписи** (`approver_kind` + `requires_attachment` на этапе). Два независимых флага, вместе дающие «последним подписывает автор, приложив PDF»:

- **`approver_kind = position`** — маршрут хранит HR-должности, а не персональные аккаунты. На запуске `apps.hr.interface` разрешает их в текущих активных сотрудников с активными учётками; получившиеся `user_id` сохраняются в `ApprovalTask`, а `role_ids` — в снимке этапа. Поэтому смена сотрудника влияет на новые заявки, но не переписывает уже выданные задачи и их аудит. **`approver_kind = initiator`** — должностей в маршруте нет: согласующий вычисляется на запуске из `ApprovalProcess.initiator_id`.
- **`requires_attachment`** — этап можно СОГЛАСОВАТЬ только с уже приложенным к задаче PDF (`ApprovalTask.file_id`). Для отказа документ не нужен: того, что отказавшему полагалось бы подписать, не существует. Файл прикладывается отдельным запросом ДО решения (`services/attachments.py`, `POST /tasks/{id}/attachment`) — загрузка в S3 не должна идти внутри транзакции, держащей блокировку процесса. PDF-only задаёт политика scope `signoff_doc` в media_files (она же включает проверку magic-байтов), а не проверка в signoff. Приложить может ТОЛЬКО адресат запроса: администраторского исключения нет — загрузка за согласующего была бы подделкой подписи.
- **«Последний этап» — не сущность.** Процесс завершается, когда пройдена группа с наибольшим `order`, поэтому подпись, оказавшаяся не последней, тихо превращается в промежуточное подтверждение. Запрета на это нет (иначе после подписи нельзя было бы добавить ни одного этапа), есть предупреждение редактору — `initiator_stage_not_last` в `GET /routes/{id}`, рядом с `coverage_gaps`.

**Процесс.** `ApprovalProcess` → `ApprovalProcessStage` → `ApprovalTask` + `ApprovalEvent` (журнал). Этапы процесса — **снимок маршрута на момент запуска**: правка маршрута не трогает уже идущие согласования. Инварианты движка (`services/engine.py`):

- **Отрицательное решение закрывает круг сразу** — и отказ, и возврат на доработку на любом этапе завершают весь процесс, оставшиеся запросы гасятся как `skipped`, а не висят.
- **Решений три, и различает их судьба ОБЪЕКТА, а не механика.** `approve` ведёт круг дальше; `reject` и `rework` закрывают его одинаково, но `rejected` («документ не годится») оставляет объект ЗАПЕРТЫМ для правки, а `rework` («поправьте и пришлите снова») — открывает. Заперты и `pending`, и `approved`, и `rejected`; правятся только `draft` и `rework` (`ApprovalState.editable()`). Ключ от замка ровно один — возврат на доработку: решением согласующего, пока круг идёт, и `POST /processes/{id}/rework` (`engine.reopen`), когда решение уже принято. Второй нужен затем, что иначе «согласовано» было бы состоянием без выхода, а опечатка в согласованном договоре чинилась бы заведением рядом второго договора. Возвращать решённое вправе согласующий этого процесса или администратор — но НЕ инициатор: свою заявку он отзывает, пока её не рассмотрели, а отпирать чужое решение — не его право. Доработанный объект уходит НОВЫМ кругом: старый процесс остаётся в состоянии `rework`, а не воскресает.
- **Группа этапов проходится целиком** — следующий `order` активируется, только когда все этапы текущего согласованы.
- **Колбэк предметной аппки — внутри транзакции, уведомление — после коммита.** Состояние процесса и состояние объекта обязаны стать согласованными атомарно; рассылка в мессенджер — внешний эффект, идёт через `transaction.on_commit`.
- **Все переходы берут `SELECT … FOR UPDATE` на строку процесса.** Без этого два согласующих, одновременно закрывающих последнюю параллельную пару этапов, оба увидели бы «все согласовали» и оба дёрнули бы `on_approved`.

**Как подключить новый тип** — три шага, ни одного в самом signoff: модель наследует `signoff.Approvable` и объявляет `SIGNOFF_SUBJECT_TYPE`; миграция добавляет `approval_state`; `AppConfig.ready()` зовёт свой `approval_hooks.register()`. Четвёртый шаг — уже в самой аппке: `assert_editable()` первой строкой каждой операции правки и удаления, иначе замок для её объектов просто не сработает. Ветвление — четвёртый, необязательный: добавить в тот же вызов `facts`/`fact_fields`. Образец — `apps/contracts/approval_hooks.py`, минимальный — `apps/signoff/tests/testapp/`.

Одна ловушка при переносе на новый тип: **ключи фактов называются по смыслу, а не по типу**. У договора стран две — администратора бюджета и контрагента, — и они регулярно разные; общий ключ `country_id` означал бы, что настраивающий маршрут выберет одну из них наугад и не узнает об этом. Отсюда `admin_country_id` / `counterparty_country_id`. Обратная сторона того же правила — `program_id` у договора идёт БЕЗ приставки: программа у него ровно одна (договор → строка бюджета → программа), и уточнять там нечего.

Что сейчас объявлено в `apps/contracts/approval_hooks.py`: бюджет — `admin_country_id`, `period_year`, `currency`, `amount`; контрагент — `counterparty_country_id`, `vat`; договор — `admin_country_id`, `counterparty_country_id`, `program_id`, `amount`, `currency`, `contract_type` (подпись «Тип оплаты»: стандартный / открытый — так заказчик зовёт тип договора), `payment_type` (подпись «Порядок оплаты (по авансу)»: предоплата / постоплата / поэтапно; форма его не спрашивает — `agreement_service.payment_type_from_advance` выводит из аванса, и только когда аванс реально меняют, иначе договоры из импорта теряли бы свой тип). Ветвить бюджет по программе нельзя и не будет: бюджет — контейнер из N строк, то есть N программ, а `conditions.normalize_facts` принимает только скаляры. Это упёрлось бы в новый тип факта-списка и операторы вида `contains` в самом signoff, а не в правку contracts.

⚠️ **Справочник под choice-полем обязан быть непустым.** `conditions.validate_fields` роняет ВЕСЬ список полей типа, если у любого `choice` пустые `options`, а `SubjectsView._fields` глушит это в `[]`. Практический эффект: на свежей установке без заведённых стран И программ редактор маршрута для «Договора» не покажет ни одного условия — включая те, чьи справочники заполнены. Данные это чинят сами (ни бюджет, ни договор не завести без страны и программы), но при настройке маршрутов ДО ввода данных выглядит как сломанный редактор.

### 3.7 Companies — мультикомпанейность (реестр компаний + схема Postgres на компанию)

Полный дизайн и «почему» — [docs/multi-company-tenancy-design.md](docs/multi-company-tenancy-design.md) и CLAUDE.md §«Мультикомпанейность». Здесь — только карта каталогов, двух новых на платформе.

```
backend/htqweb/tenancy/       # Контекст компании и перевод соединения в её схему — часть фундамента
│                              #   htqweb, не Django-аппка и не гейтится ServiceStatus/require_service
├── __init__.py                 # ре-экспорт: current_company, current_company_or_none,
│                                #   set_company/reset_company, schema_for, NoCompanyContext, HOLDING_SCHEMA,
│                                #   holding_active (признак use_holding() для читателей сводок, блок H —
│                                #   b53cda8, 17.09.2026)
├── context.py                   # contextvars-хранилище slug'а (не threading.local — под ASGI
│                                #   поток обслуживает много корутин) + schema_for("co_" + slug)
├── db.py                         # apply_search_path()/use_company()/use_holding() — SET search_path
│                                #   на соединении БД, безопасно при CONN_MAX_AGE=0
├── celery.py                     # @company_task — разворачивает kwarg company_slug в контекст задачи;
│                                #   без него MissingCompanyArgument, а не молчаливый public
└── tests/                        # контекст, БД, celery, middleware, claim company в JWT

backend/apps/companies/        # Реестр компаний (схема public) — API_PREFIX=api/companies/v1/
├── models.py                    # Company (дерево владения; subdomain — короткий адрес), CompanyServiceLink (граф ТМЗ),
│                                #   CompanyMembership, CompanyModule (рубильник на уровне компании),
│                                #   CompanySchemaVersion (факт/цель миграций по компании)
├── schemas.py                    # Pydantic DTO контракта api/companies/v1 (CompanyRead, CompanyTreeNode,
│                                #   MyCompany, …) — правка формы только вслед за планом; фронт
│                                #   (src/types/companies.ts) собран по той же таблице
├── views.py                       # HTTP-слой me/companies/tree/companies/<slug>/{archive,restore,
│                                #   modules,memberships,external-holders}: чтение и правка реестра — api_view(module=
│                                #   "companies"); архив/восстановление/отзыв членства — admin=True +
│                                #   is_superuser. Заведения компании здесь нет (см. company_create)
├── urls.py                        # path() для views.py; companies/tree стоит ВЫШЕ companies/<slug>,
│                                #   иначе <slug:slug> матчит и слово tree
├── interface.py                  # get_company, resolve_host_label (метка хоста → компания: псевдоним,
│                                #   затем слаг компании без псевдонима), public_url (адрес компании для
│                                #   ссылок наружу), active_company_slugs, user_company_slugs,
│                                #   default_company_slug, module_enabled — точка входа соседей
├── admin.py                       # django-admin, под ServiceGatedAdminMixin
├── metrics.py                      # collect() — автодискавери apps/core/metrics.py
├── services/
│   ├── schema_service.py             # CREATE/DROP SCHEMA co_<slug>
│   ├── migration_service.py           # migrate_company() — прогон по схеме одной компании,
│   │                                   #   advisory-lock, BackwardsMigrationRefused/SchemaMissing
│   ├── lifecycle.py                    # жизненный цикл компании (заведение/правка/архив/восстановление/банкротство) —
│   │                                   #   единственная точка оркестрации для management-команд И HTTP-вьюх;
│   │                                   #   гейт LastActiveCompany (архив — только чтение: без последней действующей компании платформе негде писать)
│   ├── module_service.py                # модули ОДНОЙ компании (CompanyModule) — компанейский слой
│   │                                    #   рубильника поверх KNOWN_SERVICES/CORE_MODULES из apps.core
│   ├── membership_service.py            # grant_membership() — единственная точка выдачи CompanyMembership
│   │                                    #   (команды, HTTP, django-admin); вместе с членством выдаёт
│   │                                    #   базовую роль employee-basic (access.interface.ensure_basic_role)
│   └── holding_views.py                # drop_holding_views()/rebuild_holding_views() — сводные
│                                        #   UNION ALL представления схемы holding
└── management/commands/
    ├── company_create.py                # завести компанию: реестр + схема + миграции + сводки
    ├── company_grant.py                   # выдать/пополнить CompanyMembership пользователю
    │                                     #   или всем активным, идемпотентно
    ├── company_archive.py                 # архивировать компанию: status + пересборка сводок
    │                                     #   холдинга одной операцией, идемпотентно
    ├── company_restore.py                 # вернуть компанию из архива — симметрично company_archive;
    │                                     #   снимает преемника (выданные ему членства не отзываются)
    ├── company_bankrupt.py                # банкротство с преемником: членства участников → преемник,
    │                                     #   компания → архив, successor; --dry-run — сводка без изменений
    ├── migrate_companies.py              # довести схемы компаний до текущей версии (снос/сборка
    │                                     #   сводок холдинга вокруг прогона)
    ├── migrate_shared.py                  # migrate только нетенантных аппок — этим стартует
    │                                      #   контейнер вместо голого migrate (RUN_MIGRATIONS=1)
    ├── seed_group_demo.py                 # стенд группы: четыре компании (холдинг + три ДО) — реестр,
    │                                      #   схемы, оргструктуры, учётки, членства, задачи HTQ; только
    │                                      #   локальная БД (псевдонимов не ставит — стенд живёт по слагу)
    ├── tenancy_bootstrap.py                # разовый перенос hr/tasks/contracts/signoff из public
    │                                       #   в схему первой компании (ALTER TABLE ... SET SCHEMA)
    └── tenancy_status.py                    # слепок раскладки тенантных таблиц по схемам, ТОЛЬКО чтение —
                                             #   information_schema + pg_stat_user_tables (--exact — настоящий
                                             #   count(*)); --json для diff'а до/после боевой выкатки
```

---

## 4. Frontend (`frontend/`)

React 18 + Vite + TypeScript. shadcn/ui (Radix + Tailwind), TanStack Query, i18next. Тесты: Vitest + Playwright. **Не затронут миграцией бэкенда** — тот же код, тот же роутинг по `/api/<domain>/v1/*` (пути не изменились, изменился только сервер, который на них отвечает).

```
frontend/src/
├── main.tsx   App.tsx   index.css   i18n.js
├── app/
│   ├── routing/        # ⭐ routeDefinitions.ts, lazyPages.ts, prefetch.ts
│   ├── navigation/     # navItems.ts; hrNavAccess.ts — одна таблица «пункт кадрового меню → предикат
│   │                   #   по /me» для HRLayout и ProfileSidebar
│   └── components/
├── pages/              # ⭐ Точки входа роутов (Index, Login, Admin*, HR*, Calendar, Email/, hr/, public/, requests/)
│   ├── CompanyPicker.tsx  # /companies/choose — выбор компании на голом домене после входа (одна — сразу
│   │                   #   редирект на её поддомен); RequireAuth ведёт сюда любой защищённый маршрут без компании
│   ├── Email/          # OAuth callback, inbox, compose modal, settings panel
│   ├── hr/             # HR-страницы (Departments, Employees, Vacancies, Tasks, Roadmap, …)
│   ├── holding/        # GroupSummary.tsx — «Сводка группы» (/holding): ручки hr/v1/holding/headcount
│   │                   #   и tasks/v1/holding/projects, только на поддомене холдинга (блок H —
│   │                   #   43c8816, 17.09.2026)
│   └── companies/      # CompanyRegistry.tsx — «Компании группы»: дерево владения, карточка
│                       #   (правка/архив/восстановление), вкладки «Модули»/«Участники»
├── features/
│   ├── messenger/      # MessengerPage + api/ + hooks/ + types.ts (feature-sliced)
│   └── requests/       # ⭐ RequestsLayout + pages/ + components/ + hooks.ts + types.ts
├── components/
│   ├── ui/             # shadcn primitives (50+ компонентов)
│   ├── hr/ tasks/ calendar/ profile/   # Доменные компоненты
│   ├── companies/      # CompanySwitcher (шапка), CompanyFormDialog (правка), CompanyModulesPanel,
│   │                   #   CompanyMembersPanel — карточка компании в реестре
│   └── *.tsx           # Лендинг-секции, Header/Footer, RequireAuth и т.д.
├── api/                # ⭐ HTTP-клиенты по домену:
│                       #   client.ts (base axios+JWT), endpoints.ts (карта префиксов),
│                       #   users.ts, hr.ts, tasks.ts, requests.ts, cms.ts, media.ts,
│                       #   calendar.ts, email.ts, fileManager.ts, search.ts (глобальный fan-out поиск),
│                       #   companies.ts (реестр компаний — apps.companies), access.ts (/me, роли),
│                       #   holding.ts (сводка группы)
├── services/           # emailService.ts (тонкие обёртки над api/)
├── hooks/              # useActiveProfile, usePermissions (права из /api/access/v1/me —
│                       #   единственный источник), useHRLevel (ТОЛЬКО для pages/contracts/*,
│                       #   тонкая обёртка над usePermissions; сторож __tests__/useHRLevelImporters),
│                       #   use-mobile, use-toast, useMyCompanies (переключатель компании), …
├── lib/
│   ├── auth/           # profileStorage.ts, roles.ts (RBAC хелперы), permissions.ts (depthFor — глубина по узлу),
│   │                   #   companySwitch.ts (метка хоста ↔ компания, переход на поддомен `subdomain ?? slug`;
│   │                   #   refresh-cookie на родительском домене), sessionRestore.ts (на новом поддомене —
│   │                   #   один обмен refresh-cookie на access-токен вместо второго входа, зовёт RequireAuth)
│   ├── transport/      # IMediaTransport + WebRTCAdapter
│   ├── webrtc/         # ⭐ MediaEngine, WebRTCManager, SignalingClient (WS+WebTransport), SdpMunger, BitrateController
│   ├── telemetry.ts    # Frontend → backend client-errors
│   └── utils.ts        # cn() и общие хелперы
├── data/               # Статика лендинга (contacts.ts, projects.ts, services.ts)
├── types/              # Глобальные TS-типы
└── test/               # Vitest setup
```

**Где что искать:**
- Новый роут — `app/routing/routeDefinitions.ts` + лениво в `lazyPages.ts` + страница в `pages/`.
- Новый API-клиент — `api/<domain>.ts`, базовый axios + JWT-интерсептор в `api/client.ts`, префиксы — в `api/endpoints.ts`.
- Глобальный поиск (`api/search.ts`) — fan-out: параллельно дёргает list-эндпойнты доменов и мёржит (упавший источник, напр. 403/503-disabled, молча игнорится).
- Доменная фича крупнее одной страницы — `features/<name>/` (как `messenger`, `requests`).
- UI-примитив — `components/ui/` (shadcn). Доменный — `components/<domain>/`.
- Локали — не в `src/`, а в `frontend/public/locales/{en,ru}/translation.json` (валидатор `check-i18n.mjs`, `update_i18n.py`).

**Известный хвост:** несколько мест во фронтенде (`pages/AdminUsers.tsx`, `components/profile/ProfileSidebar.tsx`, `components/admin/UserEditDialog.tsx`, `App.tsx`) всё ещё ссылаются на `/sqladmin` — этой панели больше нет (см. §3.1, §6, [API.md](./API.md)). Не бэкенд-докой чинится — фронтенд-код вне скоупа этого файла, но имей в виду при отладке "битой" ссылки на админку.

---

## 4.1 Email (`apps.mail`) — дуальная архитектура (corp + personal)

С одной страницы [/email](frontend/src/pages/Email/EmailPage.tsx) пользователь работает с **корпоративным ящиком** и подключёнными **личными** Gmail / Outlook — переключение через account-selector в сайдбаре. Код — [backend/apps/mail/](./backend/apps/mail/), перенесён из `services/email` практически 1:1 по контракту.

Корпоративным сервером может быть **Mailcow** (REST API) или **любой сервер с IMAP/SMTP** — разница вынесена в настройку `MAIL_PROVISIONER`, см. «Провижининг ящиков» ниже. Управление ящиками — [/admin/mailboxes](frontend/src/pages/AdminMailboxes.tsx) (создание, сброс пароля, архив/удаление, сверка с сервером, алиасы).

**Pivot-таблица:** одна `mail_emailaccount` строка на mailbox (Django-имя таблицы; логически — та же `email_accounts`). CHECK-consistency с провайдером сохранена в `apps/mail/models.py`:
```
EmailAccount(id, user_id, type=corporate|personal, provider=mailcow|google|microsoft,
             address, is_default, is_active,
             mailbox → ProvisionedMailbox (1:1, corporate),
             oauth_token → OAuthToken (1:1, personal),
             sync_state JSONB, last_sync_at, watch_expires_at)
```

**Sync** ([apps/mail/services/sync/](backend/apps/mail/services/sync/)):
- `gmail.py` — `users.history.list` + `messages.list`/`get`; push через `users.watch` → Pub/Sub. **Драйвер не портирован** — перенесён только маппер payload'ов
- `microsoft.py` — `/me/messages/delta` + persisted `@odata.deltaLink`; push через Graph subscriptions. **Тоже только маппер**
- `mailcow_imap.py` — разбор RFC 5322 (`parse_eml`), без сети
- `imap_sync.py` — **рабочий двусторонний драйвер** корпоративных ящиков (`mailcow` и `imap`): тянет письма по папкам из `MAIL_SYNC_FOLDERS`, курсор UID лежит в `EmailAccount.sync_state` и обязательно сверяется по `UIDVALIDITY` (сервер пересобрал папку → курсор сбрасывается, иначе папка молча выпала бы из синхронизации), и толкает обратно `\Seen` для прочитанного в платформе (`MAIL_SYNC_PUSH_FLAGS`). `message_id` = `<папка>:<uidvalidity>:<uid>` — он обязан быть и стабильным (уникальный индекс), и обратимым в UID (иначе флаги некуда толкать)
- Живое соединение — [apps/mail/services/imap_client.py](backend/apps/mail/services/imap_client.py) (stdlib `imaplib`, синхронно, без новых зависимостей); единственный сетевой seam — `_open_connection`
- Запускается из `incremental_sync_account`, который каждые 60 с ставит `imap_poll_fallback`. Для не-Mailcow сервера этот опрос — ЕДИНСТВЕННЫЙ источник новых писем (webhook'ов у него нет). `manage.py run_imap_idle` остаётся заглушкой: IDLE сократил бы задержку до секунд, но почта работает и без него
- UPSERT с `(account_id, message_id)` UNIQUE → идемпотентно
- `pg_try_advisory_lock` сериализует concurrent runs (`_try_advisory_lock` в `apps/mail/tasks.py`)

**Провижининг ящиков** ([apps/mail/services/provisioning/](backend/apps/mail/services/provisioning/)) — подключаемый слой, выбирается настройкой `MAIL_PROVISIONER` (`auto`|`mailcow`|`imap`|`none`), а не веткой в коде:
- `mailcow.py` — REST API: ящик реально создаётся/правится/выключается/удаляется, домен отдаёт полный список ящиков
- `imap.py` — сервер без админ-API. В IMAP **нет команды «создать ящик»** (`CREATE` заводит папку ВНУТРИ существующего), поэтому «создание на сайте» здесь = проверить учётку живым логином и привязать существующий ящик. Занятый адрес → 409, а не тихое переименование в `i.ivanov2`: адрес обязан совпасть с реальным ящиком
- `noop.py` — почтовый сервер не подключён: только строка в БД (историческое поведение, дефолт для ненастроенного окружения)

`mailbox_service` всегда выполняет локальный переход, а отказ сервера кладёт в `ProvisionedMailbox.last_error` (+ `status="error"` для create/reset-password) — админка ящиков показывает это в таблице. Пароль ящика хранится зашифрованным в `encrypted_smtp_app_password`; им пользуются и синхронизация, и отправка.

**Сверка** ([apps/mail/services/reconcile_service.py](backend/apps/mail/services/reconcile_service.py)) — `GET/POST /api/email/v1/mailboxes/reconcile/` + ежечасная задача (миграция `0007`). Сравнивает обе стороны: `only_local` / `only_remote` / `mismatched`. Режим `listing` (Mailcow отдаёт список) видит обе стороны; режим `probe` (голый IMAP) проверяет только известные платформе ящики поштучным логином и честно помечает это в отчёте — про ящики, заведённые на сервере мимо платформы, узнать неоткуда. По умолчанию сверка ничего не меняет; направление (`pull`/`push`/`both`) выбирает админ.

**Доступ к закрытому почтовому серверу** — профиль `mail-tunnel` ([infra/mail-tunnel/](infra/mail-tunnel/)): autossh пробрасывает IMAP и SMTP, `IMAP_HOST`/`SMTP_HOST` смотрят на туннель. Проверка ключа хоста включена (по каналу идут почтовые пароли). Настройка — в `.env.example`.

**Настройки подключения** ([apps/mail/services/mail_config.py](backend/apps/mail/services/mail_config.py)) — единственная точка, откуда домен берёт реквизиты. Строка `MailServerConfig` (синглтон, правится на вкладке «Подключение» в `/admin/mailboxes`) ложится **поверх** env по правилу «пустое поле = берём из окружения». Отсюда три следствия: окружение, где UI не трогали, работает как раньше; env остаётся способом первичной раскатки; очистка поля в форме возвращает значение из env. Булевы в БД nullable намеренно — иначе `imap_ssl=false` не смог бы перекрыть `IMAP_SSL=true`. Кэшируется ТОЛЬКО чтение строки (5 с): закэшируй мы смерженный результат, `override_settings` перестал бы действовать. Секрет Mailcow хранится зашифрованным и наружу не читается.

**Диагностика** ([apps/mail/services/connection_check.py](backend/apps/mail/services/connection_check.py)) — одна логика на двоих: `manage.py mail_check` и кнопка «Проверить» в интерфейсе. Проверяет цепочку по порядку зависимости (настройки → порт → IMAP → вход → папки → SMTP) и останавливается на первом провале, чтобы не сыпать производными ошибками; к каждому провалу приложена конкретная починка, а не констатация. Без адреса ящика секретов не требует. Пароли в отчёт не попадают — он уезжает и в браузер, и в тикеты.

**Три способа подключить почту** (`EmailAccount` разрешает ровно один источник учётки, это проверяет `ck_email_accounts_type_consistency`):

| Способ | Учётка | Кто заводит |
|---|---|---|
| `corporate` | `ProvisionedMailbox` | админ платформы либо сам сотрудник (см. ниже) |
| `personal` + OAuth | `OAuthToken` | пользователь, Gmail/Outlook |
| `personal` + IMAP | `ImapAccountSettings` | пользователь, ЛЮБОЙ сервер |

Третья ветка добавлена к исходному контракту ([imap_account_service.py](backend/apps/mail/services/imap_account_service.py)): раньше personal-аккаунт мог быть только OAuth-овым, и подключить почту вне Google/Microsoft было нечем. Пользователь вводит хост и порт сам, как в почтовом клиенте; форма предзаполняется по домену (известные провайдеры — точными значениями, остальные — догадкой `imap.<домен>`, помеченной как догадка, чтобы её не приняли за факт). Учётка проверяется живым входом ДО записи в БД. Синхронизация и отправка для такого аккаунта идут на ЕГО сервер, а не на корпоративный (`imap_sync.imap_client_for`, `corporate_smtp.account_smtp_target`) — иначе при совпадении логинов попали бы в чужой ящик.

**Самоподключение** ([apps/mail/services/self_service.py](backend/apps/mail/services/self_service.py), `POST /api/email/v1/accounts/connect-corporate/`) — единственная точка домена, где НЕпривилегированный пользователь заводит `ProvisionedMailbox`, поэтому ограничения явные: режим включает админ (`allow_self_service`, по умолчанию выключен), домен адреса обязан совпасть с корпоративным, ящик, уже привязанный к другому сотруднику, — 409 (знание пароля от общего ящика не должно уводить чужую привязку), а учётка проверяется живым входом ДО записи в БД. Блок на странице профиля сам скрывается, когда режим выключен.

**Push-приёмники** ([apps/mail/webhooks.py](backend/apps/mail/webhooks.py)) — `POST /api/email/v1/webhooks/{gmail,microsoft,mailcow}`, public, БЕЗ rate-limit на nginx-уровне (см. §6). Auth: Gmail Bearer JWT (google-auth) + fallback token; Graph initial `validationToken` echo.

**Send** ([apps/mail/services/sender/](backend/apps/mail/services/sender/)) — стратегия по `provider`: Gmail API `messages.send` (base64url MIME), Graph `/me/sendMail` (JSON), Mailcow SMTP 587 STARTTLS (`mailcow_smtp.py`), произвольный корпоративный сервер (`corporate_smtp.py`, провайдер `imap`: хост/порт/TLS из `SMTP_*` с откатом на `IMAP_HOST`). `POST /api/email/v1/send` ставит `folder='outbox'` + `deliver_email.delay(...)` (Celery-таск, `apps/mail/tasks.py`, вместо Dramatiq-актора).

**Вложения писем — НЕ полноценно подключены** (не регрессия миграции, так было и в FastAPI-исходнике): `EmailAttachment` остаётся metadata-only, ни один из `emails.py`-роутов не принимает байты. `apps/mail/services/attachment_service.py::store_attachment` — подготовленный сеам на будущее, хранит через `apps.media_files.interface` (scope `generic`), а не через собственный бакет.

**Архивация ящиков:** `apps.mail.interface.archive_user_mailboxes(user_id)` — приостанавливает personal-аккаунты + архивирует corporate mailbox (`archived_at=now()`); `final_purge_archived_mailboxes` — периодика **Celery beat** (cron 03:15, зарегистрирована миграцией `apps/mail/migrations/0004_mail_periodic_tasks.py`, а не APScheduler) hard-delete'ит после `MAILBOX_PURGE_AFTER_DAYS` (default 30). Раньше это была Redis pub/sub подписка на `user.deactivated` от user-service — в монолите это прямой вызов `interface`.

**Шифрование:** OAuth-токены — AES-256-GCM в `apps/mail/services/crypto.py` (буквальный порт `services/email/app/services/crypto.py`).

---

## 4.2 Task workflow (`apps.tasks`) — Jira + SharePoint модель

`apps.tasks` — не «трекер для разработчиков», а универсальный движок процессов: Jira (key, FSM, types, links, labels, versions) + SharePoint (supervisor с делегатами, мульти-исполнители, watchers, progress %, inline-quick-edit на Kanban-карточке). Код — [backend/apps/tasks/](./backend/apps/tasks/), перенесён из `services/task`.

**Роли на задаче** (модель не изменилась при переносе):
```
Task
  ├── reporter_id       — кто создал
  ├── supervisor_id     — руководитель (может делегировать)
  ├── assignee_id       — primary-исполнитель (denormalized из TaskAssignee)
  └── progress_percent  — 0..100
TaskAssignee(task_id, user_id, role)   # M:M, role = primary|collaborator
TaskDelegate(task_id, user_id, granted_by, granted_at)
TaskWatcher(task_id, user_id)
```

**FSM-статусы (7):** `backlog → todo → in_progress → in_review → blocked → done → cancelled` (с обратными переходами; `TRANSITIONS` в [apps/tasks/models.py](backend/apps/tasks/models.py) — скопирован дословно из `services/task/app/models/task.py`).

**Endpoints управления ролями** (см. [apps/tasks/urls.py](backend/apps/tasks/urls.py) — пути не изменились):
```
PATCH  /api/tasks/v1/tasks/{id}/supervisor/    body: {user_id|null}
PATCH  /api/tasks/v1/tasks/{id}/assignees/     body: [{user_id, role}]
POST   /api/tasks/v1/tasks/{id}/delegates/     body: {user_id}   (только supervisor)
DELETE /api/tasks/v1/tasks/{id}/delegates/{user_id}/
POST   /api/tasks/v1/tasks/{id}/watch/  •  DELETE …/watch/
PATCH  /api/tasks/v1/tasks/{id}/progress/      body: {percent}
```

**Иерархия работ — пять уровней:**
```
Проект (Project)
└── Площадка (Site, через ProjectSite M2M)
    └── Блок (SiteBlock) ── плановые объёмы (SiteBlockVolume): «250 валов на блок 1»
        │                   факт по ЛЮДЯМ: ProjectStaffReport (численность за день)
        └── Роудмап (Roadmap) ── план: сроки + ResourceRequirement
            └── Задача (Task) ── план: TaskVolume; факт: DailyReport
                └── Подзадача (Task.parent)

Партнёр (Contractor) навешивается на проект / площадку / роудмап / задачу
и НАСЛЕДУЕТСЯ вниз (contractor_service.effective_contractors).
Партнёр ≈ контрагент из «Договоров» (Contractor.counterparty_id), привлечение —
по договору (ContractorEngagement.agreement_id), см. §3.5.
```
```
Project(id, name, status, color, start_date, end_date, owner_id, department_id,
        use_production_calendar)          # False = календарные дни, стройка идёт 7/7
Roadmap(id, project_id, site_block_id, name, status, planned_start_date,
        planned_end_date, planned_working_days)   # площадки колонкой НЕТ — джойн site_block__site
SiteBlock(id, site_id, name, code, order, status=planned|active|suspended|done, start_date, end_date)
DailyReport(id, task_id, volume_type_id, author_id, work_date, quantity,
            headcount, comment, current_revision, is_deleted)
DailyReportRevision(id, report_id, revision_no, <снимок полей>, edited_by_id, edited_at)
ProjectStaffReport(id, project_id, site_block_id, author_id, work_date,
                   comment, current_revision, is_deleted)   # численность по блоку
ProjectStaffReportLine(id, report_id, work_role_id, headcount)  # «монтажник — 12»
ProjectStaffReportRevision(id, report_id, revision_no, work_date, comment,
                           total_headcount, lines(JSON), edited_by_id, edited_at)
Task.project_id    → Project(id)   ON DELETE SET NULL   # NULL = standalone
Task.roadmap_id    → Roadmap(id)   ON DELETE SET NULL   # ЗАДАЁТ проект, площадку и блок задачи
Task.site_block_id → SiteBlock(id) ON DELETE SET NULL
```

Три вещи, которые определяют всё остальное:

1. **Выполнение считается по объёмам в штуках**, а не по статусам задач; на статусы код
   падает обратно только когда объёмов нет (согласование, приёмка).
2. **Факт живёт только в `DailyReport`** — с датой ВЫПОЛНЕНИЯ работ (`work_date`, не
   `created_at`), автором и историей правок. Колонки `completed_quantity` больше нет:
   она была числом без даты, и по ней нельзя было ни построить S-кривую, ни спросить
   «сколько было сделано на 5 июня». Каждая правка отчёта пишет новую
   `DailyReportRevision` — полный снимок, по образцу `approvals.RequestFormTemplateVersion`.
3. **План хранится, факт всегда пересчитывается.** Копия факта разошлась бы с отчётами
   при первом же их изменении.

Роудмап-дерево ([HRRoadmap.tsx](frontend/src/pages/hr/HRRoadmap.tsx)) рендерит все пять
уровней; карточка пакета с «по дням» и лентой отчётов —
[HRRoadmapDetail.tsx](frontend/src/pages/hr/HRRoadmapDetail.tsx); дашборд план/факта с
S-кривой — [HRProjectPlanFact.tsx](frontend/src/pages/hr/HRProjectPlanFact.tsx).
```
GET/POST/PATCH/DELETE /api/tasks/v1/projects/[{id}/]   •   GET …/projects/{id}/tasks/
GET/POST/PATCH/DELETE /api/tasks/v1/roadmaps/[{id}/]   •   GET …/roadmaps/{id}/{tasks,metrics}
GET/POST …/sites/{id}/blocks   •   GET/PATCH/DELETE …/blocks/{id}   •   PUT …/blocks/{id}/volumes
GET …/blocks/{id}/progress     •   GET/PUT …/tasks/{id}/volumes          # объёмы = ПЛАН
GET/POST …/tasks/{id}/daily-reports  •  GET/PATCH/DELETE …/daily-reports/{id}   # факт
GET …/daily-reports/{id}/revisions   •  GET …/roadmaps/{id}/daily-reports
GET …/staff-reports/projects  •  GET …/projects/{id}/staff-board[?date=]   # ЧИСЛЕННОСТЬ
GET/POST …/projects/{id}/staff-reports  •  GET/PATCH/DELETE …/staff-reports/{id}
GET …/staff-reports/{id}/revisions
GET /api/tasks/v1/plan-fact/{project,roadmap}/{id}[?date=]   # SPI, прогноз, отставание, S-кривая
GET /api/tasks/v1/equipment-usage?…                          # что занято на дату D + история
GET/POST/PATCH/DELETE /api/tasks/v1/resource-requirements/[{id}/]   # план количеством
GET/POST/DELETE       /api/tasks/v1/assignments/[{id}]              # факт именами
GET/POST/PATCH/DELETE /api/tasks/v1/{task-types,equipment-categories,work-roles,volume-types}/[{id}/]
```

**Сервисы** ([apps/tasks/services/](backend/apps/tasks/services/)): `task_service.py`, `task_content_service.py`, `task_response.py`, `project_service.py`, `roadmap_service.py` (план/факт пакета), `block_service.py` (блоки + прогресс по штукам), `daily_report_service.py` (факт + ревизии), `staff_report_service.py` (численность персонала по блокам: факт + ревизии со снимком строк, свёртки плана и сверка с `DailyReport.headcount`), `plan_fact_service.py` (SPI, прогноз, каскад, S-кривая), `resource_service.py` (потребности и назначения), `equipment_usage_service.py` (техника на дату D), `contractor_service.py` (в т.ч. наследование партнёра), `site_service.py`, `sequence_service.py` (Jira-style ключи), `calendar_service.py` (в т.ч. рабочие/календарные дни), `production_calendar.py` (казахстанские праздники), `gantt_service.py`, `link_service.py`, `notification_service.py`, `reference_service.py`, `hydration.py`.

Вторая очередь сверялась со спецификацией модуля (`docs/SPEC-projects-module.md`, в репозитории её больше нет). Расхождения с ней были намеренными и сохраняются в коде: `Subcontractor`, `ProjectObject` и `EquipmentEngagement` из её §3.1 НЕ заводились — их роль играют уже существующие `Contractor`, `Site`+`SiteBlock` и `ResourceRequirement(kind=equipment)`. Ссылки вида «SPEC §N» в докстрингах указывают на тот же документ и остаются как объяснение, откуда взято решение.

**Kanban** ([KanbanBoard.tsx](frontend/src/components/tasks/KanbanBoard.tsx)) — без изменений на фронте.

---

## 5. Видео/конференции

| Компонент | Где | Что делает |
|---|---|---|
| **SFU** | [sfu/src/server.ts](./sfu/src/server.ts), [sfu/src/room.ts](./sfu/src/room.ts) | Mediasoup SFU, медиа-роутинг. Кодеки: `media-codecs.config.json`. Не тронут миграцией. |
| **WebTransport proxy** | [webtransport/server.py](./webtransport/server.py) | QUIC-сигнализация (aioquic) для SFU: принимает WebTransport-сессию на `:4433/udp` (в обход nginx) и перекладывает те же JSON-строки в WebSocket SFU, пробрасывая `?token=`. Сертификат — [webtransport/generate_cert.py](./webtransport/generate_cert.py): ECDSA P-256 на 13 дней + DER SHA-256 в `certs/cert.sha256` (иначе браузер самоподписанный QUIC-эндпоинт не примет). |
| **Frontend WebRTC** | [frontend/src/lib/webrtc/](./frontend/src/lib/webrtc/) | `MediaEngine`, `WebRTCManager`, `SignalingClient`(WS)/`WebTransportSignalingClient`, `SdpMunger`, `BitrateController`. |
| **UI** | [frontend/src/pages/ConferencePage.tsx](./frontend/src/pages/ConferencePage.tsx) | Страница конференции. |
| **Конфиг конференции** | `apps.cms.services.conference_service` ([backend/apps/cms/services/conference_service.py](backend/apps/cms/services/conference_service.py)), `GET /api/cms/v1/conference/config` | ICE/SFU-конфиг из `htqweb/settings/base.py` (`CONFERENCE_SFU_URL`/`_PATH`/`ICE_SERVERS` + `CONFERENCE_WT_*`) — порт `services/cms/app/data/conference.yaml`. `CONFERENCE_SFU_URL` пуст по умолчанию: фронт берёт сигналинг с того же origin (`/ws/sfu/`). Плюс `enabled` (сервис `conference` в реестре — включён миграцией `core/0003_enable_conference`) и адрес QUIC-моста с отпечатками его сертификата. |
| **Аутентификация сигналинга** | [sfu/src/auth.ts](./sfu/src/auth.ts) | Проверка платформенного JWT (HS256, тот же `JWT_SECRET`, что у Django) на WS-upgrade: подпротокол `htqweb.jwt`, `Authorization: Bearer` или `?token=`. Без токена — 401. Выключается только `SIGNALING_REQUIRE_AUTH=false`. |
| **Запись, история, протокол** | [apps/conference/](backend/apps/conference/), `/api/conference/v1/*` | ⭐ Аппка появилась под задачу «история + запись + протокол» (имя `conference` было зарезервировано в `KNOWN_SERVICES` под SFU-стек — теперь у него есть своя Django-аппка, и `ServiceGateMiddleware` гейтит её собственным флагом). Модели: `ConferenceSession` (кто собрал, когда, сколько длилась), `ConferenceParticipant`, `ConferenceRecording`, `ConferenceTranscriptSegment`, `ConferenceEvent`. Приглашения (`ConferenceInvite`) остались в `cms` — название встречи аппка берёт через `apps.cms.interface.get_conference_room_title`. |
| **Захват записи** | [sfu/src/recording.ts](./sfu/src/recording.ts), [sfu/src/recording-api.ts](./sfu/src/recording-api.ts) | Запись **поучастниковая**: на каждый producer вешается `PlainTransport`, RTP уходит на localhost, ffmpeg ремуксит его в `.mkv` (`-c copy` — без перекодирования, CPU почти не тратится). `.mkv`, а не `.webm`, потому что комната поддерживает и H264, а webm его при `-c copy` не примет. Факты о встрече уходят в Django по `/api/conference/v1/internal/*` (общий секрет `CONFERENCE_INTERNAL_TOKEN`, не JWT — у SFU нет пользователя). Связь необязательная: недоступный Django не ломает звонок, деградация через `sfu/src/fallback.ts`. |
| **Сборка и расшифровка** | [apps/conference/tasks.py](backend/apps/conference/tasks.py), `services/compose_service.py`, `services/transcript_service.py` | Отдельный контейнер `backend-media-worker` (образ `backend/Dockerfile.media` с ffmpeg и faster-whisper), очередь `conference_media` (`CELERY_TASK_ROUTES`). Сводит дорожки в одно mp4 (`xstack` сеткой, до `CONFERENCE_MAX_TILES` плиток, `amix` для звука) и распознаёт речь. **Диаризации нет и не нужно:** аудио каждого лежит отдельным файлом, поэтому «кто говорит» известно из того, чей это файл. |
| **Ретенция** | `apps.conference.tasks.purge_expired`, миграция `conference/0002_conference_periodic_tasks` | Через `CONFERENCE_RETENTION_DAYS` (25) медиа удаляется из хранилища безвозвратно, состояние встречи → `purged`. История и текстовый протокол остаются навсегда. Отдельное состояние, а не удалённая строка, чтобы интерфейс отличал «не писали» от «записали и вычистили по сроку». |
| **UI истории** | [frontend/src/pages/conference/](./frontend/src/pages/conference/) | `/conference/history` — список, `/conference/history/:sessionId` — карточка: плеер + протокол с кликабельными тайм-кодами. Видео играет по **подписанной** ссылке (`?sig=&exp=`, `services/signing.py`): `<video>` не отправляет `Authorization`, а скачивание blob'ом убило бы Range, то есть перемотку. |

Открыть стенд наружу (Cloudflare для сигналинга + bore для медиа): [docs/TUNNEL_SETUP.md](./docs/TUNNEL_SETUP.md), оркестратор — [scripts/start-public-test.ps1](./scripts/start-public-test.ps1). Старый [scripts/start-sfu-tunnel.ps1](./scripts/start-sfu-tunnel.ps1) остался для SFU, запущенного на хосте без Docker.

---

## 6. Маршрутизация: «куда улетает запрос»

**Источник правды:** [infra/nginx/default.conf](./infra/nginx/default.conf) (upstream-блоки `backend`/`backend_asgi` + `location` longest-match). Прод-only — в dev маршрутизацию делает Vite (`frontend/vite.config.ts`, один `VITE_BACKEND_TARGET` для WSGI-трафика + `VITE_MESSENGER_WS_TARGET` для ASGI/WS; исторические per-service `*ServiceTarget`-переменные в конфиге все указывают на один и тот же таргет).

```
/api/requests/v1/stream  → backend_asgi   (SSE, БЕЗ буферизации/с таймаутом 3600s — location = /api/requests/v1/stream)
/ws/                     → backend_asgi   (Socket.IO мессенджера, ws/messenger/socket.io)
/api/hr/v1/public/       → backend        (публичные HR-эндпойнты, строгий rate-limit, БЕЗ auth)
/api/email/v1/webhooks/  → backend        (БЕЗ rate-limit — Gmail Pub/Sub + Graph + Mailcow push)
/api/media/v1/files/     → backend        (upload — жёсткий лимит, буфер выключен)
/api/media/              → backend        (+ edge-кэш публичных вариантов, proxy_cache media_cache)
/api/                    → backend        (все остальные домены — users/hr/tasks/requests/cms/mail/messenger/
                                            contracts/signoff/conference/companies/access)
/ws/sfu/                 → sfu:4443       (WebRTC-сигналинг, не Django)
/django-admin/           → backend
/static/                 → backend        (collectstatic)
/grafana/  /prometheus/  → grafana / prometheus (наблюдаемость, см. §8)
/                        → frontend (Vite-сборка через nginx)
```
> `/sqladmin/*` и `/mongo-admin` **убраны** — старой sqladmin/AdminJS-панели больше нет, база администрируется через `/django-admin/` (см. §3.1, §10).

**Компания запроса — по хосту, а не по пути.** Регулярка `server_name` в `infra/nginx/default.conf` вынимает первую метку поддомена (`htq.htq.group` → `htq`; `www`, IP и голый домен не матчатся) и жёстко ставит её в `X-HTQ-Company` на всех `location`, проксирующих в Django; в dev то же делает прокси Vite (`frontend/vite.config.ts`, `companyFromHost`). `CompanyContextMiddleware` переводит метку в компанию через `apps.companies.interface.resolve_host_label` — сначала псевдоним `Company.subdomain` (`htq`, `hts`, `keg`, `group`), затем слаг, но только у компании без псевдонима; неизвестная компания — 404; архивная — режим «только чтение» (`htqweb/tenancy/archive.py`, [спека](docs/plans/2026-09-25-archive-read-only-spec.md)): любой метод кроме `GET`/`HEAD`/`OPTIONS` — 403 `company_archived` всем, включая суперпользователя (кроме выдачи и обновления токена), чтение — только суперпользователю, остальным 404; анонимные ручки на архиве закрыты только у тенантных аппок, подписанные файлы, вложения и аватары общих аппок отвечают. Дальше везде слаг: схема `co_<slug>`, claim `company` токена. Голый домен компании не несёт (`search_path=public`) — вход, регистрация, выбор компании `/companies/choose`. Правила целиком — CLAUDE.md «Мультикомпанейность», выкатка — [docs/deploy/subdomains-runbook.md](docs/deploy/subdomains-runbook.md).

При добавлении эндпойнта: роутер в `backend/apps/<domain>/views.py` → зарегистрировать в `backend/apps/<domain>/urls.py` (оба написания — со слешем и без, `APPEND_SLASH=False`) → nginx трогать НЕ нужно (уже проксирует весь `/api/`, кроме уже выделенных под особые лимиты location'ов выше). Полный контракт — в [API.md](./API.md).

---

## 7. БД, миграции, фоновые задачи

- **PostgreSQL** — Django ходит **напрямую** (`DB_HOST=db DB_PORT=5432`, `psycopg`, синхронно, `CONN_MAX_AGE=0` — пул на уровне приложения, не внешнего пулера). PgBouncer (`:6432`) остаётся в compose для хостовых утилит/ручного `psql`, но в путь живого запроса больше не входит.
- **Схема:** одна `public` — кроме `hr`/`tasks`/`contracts`/`signoff`, которые живут в схеме компании `co_<slug>` (см. §3.7). Имена таблиц — **стандартные Django** `<app_label>_<model>` (например `hr_department`, `tasks_task`, `mail_emailaccount`, `users_user`) — никакого ручного префиксования: раньше (`hr_*`, `task_*`, `request_*`…) это было вынужденной адаптацией под то, что PgBouncer в transaction-режиме сбрасывал `search_path`; в Django-монолите такой проблемы нет (см. §10 — как было).
- **MongoDB — убрана.** HR-документы, раньше лежавшие в `htqweb_docs`, теперь обычные Django-модели/файлы через `apps.media_files`.
- **Миграции:** обычные Django `makemigrations`, `managed=True`. Никакого Alembic, никакого ручного управления транзакцией миграции. Применяются двумя командами: `manage.py migrate_shared` — общие аппки (её зовёт старт контейнера при `RUN_MIGRATIONS=1`), `manage.py migrate_companies` — схемы компаний `co_<slug>`, отдельным шагом выкатки. Голый `migrate` после `tenancy_bootstrap` пересоздал бы таблицы тенантных аппок в `public` пустыми (см. §3.7, CLAUDE.md «Мультикомпанейность»).
- **Фоновые задачи:** Celery (Redis-брокер `redis://redis:6379/2` — задаётся `x-django-env` в `docker-compose.yml` и одинаков в проде и dev-оверлее, который эту переменную не переопределяет; `/9` — это лишь запасной дефолт в `htqweb/settings/base.py` на случай запуска `manage.py` вне docker-compose. Результаты — `django-celery-results`, периодика — `django-celery-beat` DatabaseScheduler). Объявление — `apps/<domain>/tasks.py`, `@shared_task`, обязательная первая строка `require_service("<name>")` (метатест-конвенция потоков). Мониторинг — Flower (`:5555`). Отдельные `<svc>-worker`/`<svc>-scheduler`-контейнеры на домен — история; теперь один `backend-worker` + один `backend-beat` на всю платформу.
- **Идентификация:** `apps.users` сам выпускает и валидирует JWT, `iss=htqweb-auth` (см. `htqweb/settings/base.py::JWT_ISSUER`) — имя issuer'а не изменилось с FastAPI-эпохи, хотя отдельного `user-service` больше нет.
- **ETL (фаза 10, разовая операция при cutover):** `apps/<domain>/management/commands/etl_<domain>.py` (hr/mail/messenger/task/requests(`etl_requests`)/media) + общий хелпер [`apps/core/etl.py`](backend/apps/core/etl.py) — read-only курсор в legacy-Postgres (порт `:55432`) + детерминированный per-row hash для сверки count+hash между legacy-схемой и новыми Django-таблицами. `--dry-run`/`--verify`/`--limit`/`--source-dsn` флаги у каждой команды.

### 7.1 Объектное хранилище (S3 / MinIO)

> Манифест поменялся с миграцией: раньше было «1 микросервис = 1 бакет»; теперь файловый ввод-вывод **консолидирован** — большинство доменов (hr, mail, messenger) пишут через `apps.media_files.interface` (`store_file`/`get_file_url`/`delete_file`), а не держат свой собственный `s3_storage.py`-клон. Исключение — `cms`, у которого остался свой бакет и прямой доступ к `htqweb.storage` (пилотная аппка, появилась раньше `media_files`).

В тестовых стеках — контейнер **MinIO** (консоль `:9001`), в обоих файлах `docker-compose.test-*.yml`. При первом запуске `minio-bootstrap` создаёт бакеты (в т.ч. исторические `htqweb-messenger`/`htqweb-mail-attachments`/`htqweb-conferences`, которые сейчас ничем не заполняются — см. ниже). В проде — настоящий S3, сменой `S3_ENDPOINT` без правок кода.

| Бакет (env, `htqweb/settings/base.py`) | Кто пишет | Для чего |
|---|---|---|
| `S3_BUCKET` = `htqweb-cms` | `apps.cms` напрямую (`htqweb.storage.get_storage()`) | Новости: `content.md`, `metadata.json`, обложки, аттачменты |
| `MEDIA_S3_BUCKET` = `htqweb-media` | `apps.media_files` (и через него — `apps.hr`/`apps.mail`/`apps.messenger`/аватарки `apps.users` — все вызовы идут через `apps.media_files.interface`) | Общее файловое хранилище платформы: аватарки, HR-документы/файлы отделов, вложения мессенджера, (заготовка) вложения писем |

URL-флоу приватных файлов: API возвращает стабильный signed URL (`?sig=&exp=`) → endpoint валидирует подпись+ACL → **302** на свежий presigned S3 URL (`htqweb/storage/signed_url.py`). Работает в `<img src>` без JWT.

---

## 8. Observability и dev-инструменты

| Что | Где |
|---|---|
| Структурные логи | `backend-web`/`backend-asgi`/`backend-worker` → stdout → Promtail → Loki |
| Конфиги стека логов/метрик | [infra/logging/](./infra/logging/) (Prometheus, Loki, Promtail, Grafana) |
| Health checks | `GET /health/`, `/health/ready/`, `GET /api/core/v1/services/` (реестр отключаемости) — [apps/core/views.py](backend/apps/core/views.py) |
| Request tracing | `X-Request-ID` через `htqweb/middleware/request_id.py` |
| Метрики backend'а | `GET /metrics` на `backend-web` и `backend-asgi` — [apps/core/views.py](backend/apps/core/views.py)`::metrics`, `django-prometheus`. ⚠️ `backend-web` = `gunicorn --workers 4`, поэтому мультипроцессный режим: `PROMETHEUS_MULTIPROC_DIR` + [htqweb/gunicorn_conf.py](backend/htqweb/gunicorn_conf.py) |
| Метрики Celery | `/metrics` самого Flower; события задач включает `CELERY_WORKER_SEND_TASK_EVENTS` в [settings/base.py](backend/htqweb/settings/base.py) — настройкой, а НЕ флагом `-E` у воркера (флаг пришлось бы повторять в трёх compose-файлах, и забытая копия ломается молча). Длина очередей — от redis-exporter: `REDIS_EXPORTER_CHECK_KEYS=2=celery,2=conference_media`. ⚠️ БД **2**, а не 9: `CELERY_BROKER_URL` в compose перекрывает дефолт из settings, и со «9» экспортер сканировал бы пустую базу |
| Метрики хоста и контейнеров | `node-exporter` + `cadvisor` (диск, память, OOM, рестарты) |
| Метрики шлюза и SFU | nginx `stub_status` → `nginx-exporter` (профиль `production`); SFU — [sfu/src/metrics.ts](sfu/src/metrics.ts) |
| Бизнес-метрики | `apps/<домен>/metrics.py` (свои модели) + автодискавери в [apps/core/metrics.py](backend/apps/core/metrics.py); считает Celery-beat раз в 60 с в кэш, префикс `htqweb_*`. Есть у **всех тринадцати** доменов, включая `access` и `companies`. ⚠️ Но у четырёх тенантных аппок (`hr`, `tasks`, `contracts`, `signoff`) сборщик их пропускает (`_metric_modules()` отсекает `settings.TENANT_APPS` до импорта — `collect()` без контекста компании вызывать нечем): их метрики не экспортируются, панели по ним пусты, шесть правил алертинга на них не срабатывают (`noDataState: OK`) — открытый пункт [followups п. 3](docs/multi-company-tenancy-followups.md). `require_service` в них намеренно НЕТ: наблюдаемость обязана работать как раз тогда, когда домен выключили. В именах метрик нельзя цифры — регексп сторожа `htqweb_[a-z_]+` |
| Подмены значений (fallback) | Один примитив на три рантайма: [htqweb/fallback.py](backend/htqweb/fallback.py), [frontend/src/lib/fallback.ts](frontend/src/lib/fallback.ts), [sfu/src/fallback.ts](sfu/src/fallback.ts). На проде и стейдже — строка `FALLBACK …` + `htqweb_fallback_total`/`sfu_fallback_total`, пользователю не видно; у разработчика (`HTQ_ENV=development`) подмен нет вовсе — летит исключение. Среды разводит `HTQ_ENV`/`VITE_HTQ_ENV`, точечно — `FALLBACK_MODE`. Правила и список того, что через примитив НЕ проходит, — в CLAUDE.md §«Среды и политика fallback'ов» |
| Тестовая среда (staging) | [docker-compose.staging.yml](./docker-compose.staging.yml) — прод-настройки и прод-поведение, отличается только меткой среды (`HTQ_ENV=staging`, `SERVICE_ENV`, `PROMETHEUS_ENV`), исходники не смонтированы |
| Всего джобов Prometheus | **13** ([prometheus.yml](infra/logging/prometheus/prometheus.yml)); хранение 30 дней **или** 10 ГБ. Джоб `nginx` поднят на `dns_sd`, а не на статическом таргете: экспортер живёт в профиле `production`, и вне его имя не резолвится — у джоба ноль таргетов вместо вечного `up==0` |
| Дашборды | **10** в [infra/logging/grafana-dashboards/](./infra/logging/grafana-dashboards/), папка **HTQWeb**. `backend/apps/core/tests/test_metrics_are_observed.py` роняет сборку, если метрика считается, но её не рисует ни одна панель и не проверяет ни одно правило — и наоборот, если панель ссылается на несуществующее имя |
| Алерты | **40 правил** в [alerting/rules.yml](infra/logging/grafana-provisioning/alerting/rules.yml): 28 Prometheus, 7 Loki, 5 в группе `htqweb-business`. В шапке файла записано, что сознательно НЕ покрыто и почему — читать перед добавлением правила |
| Доставка алертов | **Два разных чата Telegram** ([contact_points.yml](infra/logging/grafana-provisioning/alerting/contact_points.yml)): инциденты звонят, бизнес-события приходят молча и им РАЗРЕШЕНО висеть неделями. Разводит их лейбл `channel=business`, а не severity (severity — срочность, channel — адресат). `critical` дополнительно на почту. Тексты — в [templates.yml](infra/logging/grafana-provisioning/alerting/templates.yml), свой шаблон на чат |
| Утренняя сводка | `apps.core.tasks.send_daily_digest` — 09:00 Asia/Almaty, Пн–Пт (миграция `core/0005`). Единственный самописный путь в Telegram, и он не конкурирует с алертингом: сводка про СРАВНЕНИЕ со вчера, а у правил Grafana нет памяти о вчера. Читает готовый снимок из кэша — запросов к БД не делает |
| Доступ | Наружу смотрит Grafana: через `/grafana/` (JWT SSO) и порт `3001`, оставленный намеренно как запасной вход при лежащем шлюзе. Всё остальное в проде привязано к `127.0.0.1` (Prometheus 9090, Loki 3100, Flower 5555, консоль MinIO 9001, Redis 6379) либо не публикует порт вовсе (`postgres-exporter`, `redis-exporter`) — ходить через `ssh -L`. В тестовых стеках публикуется всё, как раньше, но Grafana там на **3002**, а не 3001: на машинах разработчиков 3001 бывает занят соседним проектом, и тогда контейнер молча не стартует, а Prometheus получает вечный DOWN-таргет. ⚠️ Раньше здесь было написано, что порты «вынесены в `docker-compose.dev.yml`» — такого файла нет, а порты в проде публиковались на `0.0.0.0` без всякой авторизации |
| Проверка конфигов | `./scripts/check-monitoring-config.sh` — promtool, три compose-файла, JSON дашбордов и старт настоящей Grafana с настоящим провижинингом. Последнее ловит класс поломок, который иначе виден только на проде: Grafana 10.4 валидирует контакт-пойнты на старте и при пустом токене падает ЦЕЛИКОМ, унося дашборды |
| CI | [.github/workflows/](./.github/workflows/) — быстрые проверки на каждый push (~10 мин), полный прогон бэкенда на PR в `main` и по ночам (~50 мин). Известный долг вынесен поимённо в `backend/ci-known-failures.txt`, `frontend/ci-known-failures.txt` и `frontend/eslint.ci.config.js` |
| Аудиты/анализы | [docs/audit-2026-04-28/](./docs/audit-2026-04-28/), [docs/dependency-audit-2026-04-28.md](./docs/dependency-audit-2026-04-28.md) — из FastAPI-эпохи, не обновлялись под Django. (Ссылка на `docs/static-analysis-2026-04-28.md` убрана: такого файла нет.) |
| План/журнал миграции | [PLAN.md](./PLAN.md) — теперь это журнал ЗАВЕРШЁННОЙ миграции, не план на будущее |

---

## 9. Где правильно что-то делать (шпаргалка)

| Задача | Куда смотреть |
|---|---|
| Поменять/добавить роут API | `backend/apps/<domain>/views.py` + `urls.py` (оба написания пути — со слешем и без) |
| Изменить бизнес-логику | `backend/apps/<domain>/services/<file>.py` |
| Новая ORM-таблица | `backend/apps/<domain>/models.py` + `manage.py makemigrations <domain>` |
| DTO запроса/ответа | `backend/apps/<domain>/schemas.py` (Pydantic) |
| Дать соседней аппке доступ к своим данным | `backend/apps/<domain>/interface.py` — новая функция, начинается с `require_service("<name>")`, отдаёт только dict/примитивы |
| Auth/JWT примитив | `backend/htqweb/authn/` (issue/decode — `jwt.py`; уровни/роли — `levels.py`/`rbac.py`) |
| Права на ручку | `api_view(module="<аппка>", level=…)` в `views.py`; ручка без гейта — только с записью и причиной в `backend/apps/access/self_service.py` (сторож `apps/access/tests/test_gate.py`) |
| Проверка тоньше уровня модуля (конкретное действие) | `backend/apps/hr/rbac.py::NodeAccess.has(<старый ключ>)` — по узлу реестра через `legacy_roles.KEY_TO_NODE`; свой узел объявлять в `apps/<domain>/access_functions.py` и — ОБЯЗАТЕЛЬНО — явной строкой в системных ролях (`access/migrations/0008` как образец), иначе под-узел унаследует глубину предка |
| Выдать роль должности из кода/сида | `apps.access.interface.ensure_position_role(company_slug, position_id, role_code, scope_kind)` — идемпотентно, не трогает остальные роли должности |
| Фоновая задача | `backend/apps/<domain>/tasks.py` (`@shared_task`, первая строка `require_service`) |
| Периодика (cron) | Django-миграция данных для `django_celery_beat.PeriodicTask` — см. `apps/mail/migrations/0004_mail_periodic_tasks.py` как образец |
| Включить/выключить домен | `manage.py service <name> --on/--off` (см. `apps/core/management/commands/service.py`) |
| Django-admin страница | `backend/apps/<domain>/admin.py` — `ModelAdmin`, обёрнутый в `htqweb.admin_gate.ServiceGatedAdminMixin` |
| Новый фронтенд-роут/страница | `frontend/src/app/routing/routeDefinitions.ts` + `pages/<Name>.tsx` |
| HTTP-вызов из фронтенда | `frontend/src/api/<domain>.ts` (axios через `client.ts`, префиксы в `endpoints.ts`) — без изменений |
| Доменная UI-фича | `frontend/src/features/<name>/` (масштаб > одной страницы) |
| Локализация | `frontend/public/locales/{en,ru}/translation.json` (валидатор `check-i18n.mjs`) |
| Конференц-логика на клиенте | `frontend/src/lib/webrtc/` |
| SFU/медиа | `sfu/src/` |
| Загрузить/отдать файл (из бэкенда) | `apps.media_files.interface.store_file()`/`.get_file_url()` (соседи); `htqweb.storage.get_storage()` напрямую — только `apps.cms` |
| Шлюз/маршрутизация | `infra/nginx/default.conf` (прод) / `frontend/vite.config.ts` (dev) |
| Compose / порты / переменные | `docker-compose.yml` (прод), `docker-compose.test-local.yml` (локальная БД), `docker-compose.test-env.yml` (БД из .env) |
| Перелить legacy-данные (cutover) | `manage.py etl_<domain>` — см. `apps/core/etl.py` за общими хелперами |
| Праздники РК (производственный календарь) | `apps/core/kz_holidays.py` — **единственный** источник для `apps.tasks` и `apps.hr`. Фиксированные даты + правило переноса с выходного считаются на любой год; плавающий Курбан-айт и разовые решения правительства — в `KZ_YEAR_OVERRIDES` (одна строка на год). Таблицы `tasks_productionday`/`hr_calendarday` — только ручные переопределения ПОВЕРХ этого |

---

## 10. Известные «ловушки»

- **Модель прав ОДНА, и она требует компанию.** С блока I «Единая модель прав» (`docs/plans/2026-09-17-block-i-single-rbac.md`) кадровый домен не угадывает уровень по названию должности и не читает `Position.permissions` — права считаются по ролям `apps.access` (`PositionRole`/`RoleAssignment`, `services/resolve.py`) и ТОЛЬКО в контексте компании: без `X-HTQ-Company` уровень `none` у всех, кроме суперпользователя, и гейт `api_view(module=)` отвечает 403. `apps/hr/access.py` — не модель прав, а эвристика переноса; `Position.permissions` — мёртвая колонка, жива ради `hr.interface.user_has_permission` для `contracts` (roadmap §6.6). Новый под-узел реестра заводится сразу с явными строками в системных ролях: сторож `test_hr_level_roles_exact.py` сверяет только старые ключи и молчаливое наследование глубины предка не поймает.

- **`/sqladmin/`, `/mongo-admin` больше не существуют.** Несколько мест во фронтенде всё ещё на них ссылаются (см. §4) — это не 503 «сервис выключен», это честный 404/дохлая ссылка, потому что маршрута нет вовсе ни в nginx, ни во Vite-proxy. Админка — `/django-admin/`.
- **`POST /api/users/v1/admin-session/login`/`/logout` — код существует, но реального потребителя больше нет.** Эти эндпойнты ставили `admin_session`-cookie для входа в sqladmin; сам sqladmin снесён, а `django-admin` использует свою обычную Django session-аутентификацию (не эту JWT-cookie). Не удивляться, что "рабочий" эндпойнт никуда не ведёт.
- **Схема ≠ schema-per-service — эта проблема ИСЧЕЗЛА, а не "решена префиксами".** В FastAPI-эпоху PgBouncer (transaction-режим) сбрасывал `search_path`, что вынуждало держать все сервисы в `public` с ручными префиксами таблиц. В Django-монолите Postgres — прямое подключение, префиксы — стандартные Django `<app_label>_<model>`, руками ничего не мэнеджится. Если видишь код/комментарий про «schema-per-service» — это history, не текущая реальность.
- **JWT issuer — `htqweb-auth`**, как и раньше (не `users`, не `django`). `apps.users` выпускает и валидирует сам, без отдельного identity-сервиса.
- **Три compose-файла не наследуют друг друга.** Привычка `-f docker-compose.yml -f <оверлей>` больше не работает: каждый файл самодостаточен и запускается одиночным `-f`. Обратная сторона — общие сервисы продублированы трижды, и правку надо разносить руками (`git diff docker-compose*.yml`). `docker-compose.test-local.yml` жёстко пинит `DB_HOST: db`, `test-env` берёт БД из `.env` и по умолчанию НЕ мигрирует её.
- **`docs/architecture.md` не в ногу с реальным деревом** — упоминает DRF ViewSets и `backend/tasks/viewsets/`, чего в репозитории нет (реальность: `htqweb.http.api_view`, `backend/apps/tasks/`). Похоже на неадаптированный шаблон; не источник истины по структуре, см. §1/CLAUDE.md.
- **`scripts/generate-monitoring-traffic.sh`** бьёт по текущему `backend-web` (порт задаётся 4-м аргументом, по умолчанию `:8000`; `80` — через nginx). Часть ручек в списке намеренно отдаёт 404/401 — они питают панели ошибок.
- **`apps.media_files` — общая точка отказа для файлов** трёх доменов (hr/mail/messenger) плюс аватарок users. Если он выключен через `ServiceStatus` (`manage.py service media --off`), у соседей это всплывёт как `ServiceDisabled`/503, а не как их собственная ошибка — смотреть на `service` в JSON-конверте, прежде чем искать баг в вызывающей аппке.
- **Изоляция аппок — всё ещё исполняемое правило, не конвенция на доверии.** `apps/core/tests/test_app_isolation.py` гоняется в обычном test run'е (`pytest`, `cd backend`) — а не отдельным линтом, который можно забыть запустить.
- **`/metrics` — вне `/api/` намеренно.** Лежит в корне рядом с `/health/`, потому что `ServiceGateMiddleware` гейтит только `/api/<домен>/` и `/ws/`: выключенный через `ServiceStatus` домен не должен уносить с собой наблюдаемость всего процесса (проверяется тестом в `apps/core/tests/test_metrics.py`).
- **Пустые бизнес-панели ≠ нули.** `apps/core/metrics.py` при пустом кэше не экспортирует метрику вовсе, а не отдаёт 0: «сборщик (Celery-beat) умер» и «задач ноль» обязаны выглядеть по-разному.
