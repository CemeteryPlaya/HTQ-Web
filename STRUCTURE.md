# STRUCTURE.md — навигационная карта проекта HTQWeb

Путеводитель по репозиторию для людей и ИИ-агентов: где что лежит, по каким правилам устроены каталоги, куда смотреть в первую очередь. Цель — не сканировать весь проект. Актуализировано под завершённый cutover (единый Django-backend). Дата сверки — 2026-07-22.

> Дополняющие документы: [README.md](./README.md) (как поднять), [API.md](./API.md) (роутинг и контракты), [backend/README.md](./backend/README.md) (анатомия Django-аппки), [docs/architecture.md](./docs/architecture.md) (заметки по слоям — местами не в ногу с реальным деревом, см. предупреждение в CLAUDE.md).

---

## 1. Что это за проект

Внутренняя enterprise-платформа Hi-Tech Group. Прошла полный круг: изначально Django-монолит → мигрирована (Strangler Fig) в ~9 FastAPI-микросервисов → и теперь **обратно смёрстана в один Django-backend** (`backend/`, реверс-миграция завершена — журнал в [PLAN.md](./PLAN.md)). Фронтенд — React + Vite SPA, не менялся.

**Стек:**
- **Frontend:** React 18 + Vite + TypeScript, shadcn/ui (Radix+Tailwind), TanStack Query, i18next. Тесты: Vitest + Playwright.
- **Backend:** Django 5.2.7 (Python 3.14), Celery 5.6 (Redis-брокер, `django-celery-beat`/`django-celery-results`), API-слой — собственное ядро `htqweb.http.api_view` (не DRF).
- **Данные:** PostgreSQL — **одна схема `public`**, обычные Django-таблицы `<app_label>_<model>` (никаких схем-на-сервис и префиксов-руками — это была PgBouncer-специфика FastAPI-эпохи, см. §7). MongoDB **убрана вместе с FastAPI-поколением** — HR-документы, ранее лежавшие в Mongo, теперь обычные Django-модели.
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
│   │                       #   authn/ (JWT), http.py (api_view), middleware/, storage/
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
├── docs/                 # Архитектура, аудиты, ngrok/tunnel-инструкции
├── scripts/              # PS/JS/bash-утилиты (TLS, firewall, туннели, monitoring traffic)
├── tools/                # Локальные бинари туннелей (gitignored)
├── docker-compose.yml       # Прод-стек (полный)
├── docker-compose.dev.yml   # Dev-overlay (Vite HMR, MinIO, DEBUG-настройки Django)
├── docker-compose.test.yml  # Test-overlay: публикует db на :55432 для pytest-django
├── README.md   API.md   PLAN.md (журнал миграции, читать как историю, не как план "что впереди")
└── docker-compose.django.yml, RUN-DJANGO-CHECK.md   # ⚠️ мёртвый снапшот промежуточного
                                                        #   proof-of-concept'а (только users/cms/
                                                        #   media/hr были перенесены) — вытеснен
                                                        #   docker-compose.yml, не обновлять
```

> ⚠️ Игнорировать на верхнем уровне: пустой `nginx/` (авторитетный конфиг только `infra/nginx/default.conf`), корневые `node_modules/`/`package.json` (служебный tooling, не фронтенд). `docker-compose.django.yml` и `RUN-DJANGO-CHECK.md` описывают промежуточное состояние миграции (до того, как `tasks`/`requests`/`mail`/`messenger` были перенесены) — оставлены как артефакт, реальный прод-стек — `docker-compose.yml`.

---

## 3. Backend — Django-аппки (`backend/apps/`)

**Правило изоляции (важно, исполняемое):** сосед обращается к аппке **только** через её `apps.<x>.interface` — прямой импорт `apps.<x>.models`/`apps.<x>.services` из другой аппки запрещён и ловится тестом [`apps/core/tests/test_app_isolation.py`](./backend/apps/core/tests/test_app_isolation.py) (сканирует все `.py`, включая сам `interface.py`). Исключение — `apps.core`: общий фундамент (реестр отключаемости), его можно импортировать откуда угодно. Источник правды по анатомии аппки — [backend/README.md](./backend/README.md).

### 3.1 Карта аппок

| Аппка (`backend/apps/`) | URL-префикс (`API_PREFIX`) | Имя в реестре `ServiceStatus` | Домен |
|---|---|---|---|
| **core** | — (примонтирована в корень `htqweb/urls.py`, свой префикс `api/core/v1/` объявляет сама) | — (сам реестр) | `/health/`, `/health/ready/`, `/api/core/v1/services/`; общий ETL-хелпер (`etl.py`) |
| **users** | `api/users/v1/` | `users` | Identity, JWT issuer+validator, профиль, регистрация, админ-юзеры, items |
| **hr** | `api/hr/v1/` | `hr` | Сотрудники, отделы, должности, вакансии, табель, документы, аудит, оргдерево, PMO |
| **tasks** | `api/tasks/v1/` | `tasks` | Workflow-движок Jira+SharePoint (см. §4.2) |
| **approvals** | `api/requests/v1/` | `approvals` | ⭐ Lark-style конструктор форм + workflow согласований (см. §3.4). Префикс URL (`requests`) и app_label (`approvals`) сознательно расходятся — см. `apps/approvals/urls.py` докстринг |
| **cms** | `api/cms/v1/` | `cms` | Новости, категории/теги, contact-requests, ConferenceConfig |
| **media_files** | `api/media/v1/` | `media` | ⭐ Общее файловое хранилище — единая точка входа для аватарок, HR-документов, вложений мессенджера и почты (см. §7.1). `AppConfig.label = "media_files"`, но реестр знает его как `media` |
| **mail** | `api/email/v1/` | `mail` | Дуальная почта: Mailcow + OAuth Gmail/Outlook (см. §4.1) |
| **messenger** | `api/messenger/v1/` | `messenger` | Чат, Socket.IO (ASGI), presence, E2EE-ключи |
| **contracts** | `api/contracts/v1/` | `contracts` | Бюджеты (программа × статья расходов × администратор), реестр контрагентов, договоры с контролем остатка бюджета (см. §3.5). Единственная аппка, появившаяся уже после обратной миграции — FastAPI-предка у неё нет |
| **signoff** | `api/signoff/v1/` | `signoff` | ⭐ Универсальное многоэтапное согласование ЧУЖИХ объектов (см. §3.6). **Не путать с `approvals`**: та согласует собственные `RequestInstance` из своего конструктора форм, эта — строки в таблицах предметных аппок |

Полный список канонических имён сервисов — `apps.core.models.KNOWN_SERVICES` (включает ещё `conference`, зарезервированное под SFU-стек, у которого нет своей Django-аппки).

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
- API-слой — `htqweb.http.api_view` (декоратор), НЕ Django REST Framework: `methods=`, `auth="jwt"|"admin_session"|None`, опц. `body=<PydanticModel>`, `admin=True` (гейт через `htqweb.authn.rbac.require_admin`). Конверт ошибок — всегда `{"detail": ...}`.
- JWT: issuer `htqweb-auth` (см. `htqweb/settings/base.py::JWT_ISSUER`) — не путать с доменом `users`, который его лишь выпускает/валидирует. Проверка — `htqweb/authn/jwt.py`, HS256, общий `JWT_SECRET`.
- Отключаемость: `apps.core.models.ServiceStatus` (строка на аппку) + `htqweb.middleware.service_gate.ServiceGateMiddleware` (гейт по URL-префиксу `/api/...`, `/ws/...`) + `apps.core.services.require_service()` (внутрипроцессный гейт — обязателен первой строкой в `interface.py` и `tasks.py`) + `htqweb.admin_gate.ServiceGatedAdminMixin` (гейт `django-admin`). Переключатель: `python manage.py service <name> --on/--off`.

### 3.3 Как добавить новую аппку/домен

```bash
cd backend
.venv/Scripts/python.exe manage.py startapp <domain> apps/<domain>   # каркас Django
# затем: добавить "apps.<domain>" в INSTALLED_APPS (htqweb/settings/base.py),
#        API_PREFIX = "api/<domain>/v1/" в apps/<domain>/apps.py (автодискавери сделает остальное),
#        имя сервиса — в apps.core.models.KNOWN_SERVICES + htqweb.middleware.service_gate.PREFIX_TO_SERVICE
#        (+ APP_LABEL_TO_SERVICE, если app_label ≠ имени в реестре, как у media_files/approvals/mail),
#        interface.py с require_service() в каждой функции,
#        ServiceGatedAdminMixin на все ModelAdmin в admin.py.
```
Подробный чек-лист и объяснение каждого шага — [backend/README.md](./backend/README.md).

### 3.4 Approvals — Lark-style approval-движок

`apps.approvals` (URL-префикс `api/requests/v1/`, app_label `approvals`) — конструктор **форм + цепочек согласования** (no-code), вдохновлён Lark Approvals. Самый большой перенесённый домен Потока B.

- **Сервисы (`apps/approvals/services/`):** `workflow_engine.py` + `workflow_schema.py` (исполнение цепочки), `form_schema.py`/`template_validation.py`/`value_validation.py`/`template_data_table.py`/`template_settings.py` (формы и справочники), `condition_eval.py` (ветвления), `assignee_resolver.py` (кто согласует), `dispatch.py` (рассылка уведомлений), `instance_service.py`/`request_runtime.py`, `hydration.py`, `permissions.py`, `stats_rollup.py`, `audit.py`, `sse.py` (поток `/stream`).
- **Роуты:** `instances/` (+ `batch-approve`, `<id>/submit|resubmit|approve|reject|request-changes|cancel|recall`), `templates/` (+ `versions`, `preview`, `activate`/`deactivate`), `projects/` (+ `members`), `stats/{overview,by-project,by-template,by-actor,heatmap}`, `reference-sources/` (Lark-Base-style справочники, + `rows/`, `access`, `my-data-tables`, `by-slug/<slug>/options`), `stream` (SSE).
- **SSE:** `/api/requests/v1/stream` обслуживается **ASGI-процессом** (`backend-asgi`) через обычную async-вьюху (`StreamingHttpResponse`), не через `asgi.py`-обёртку — см. `apps/approvals/urls.py`.
- **Frontend:** [frontend/src/features/requests/](frontend/src/features/requests/) + [frontend/src/api/requests.ts](frontend/src/api/requests.ts) — без изменений.

### 3.5 Contracts — бюджеты, контрагенты, договоры

`apps.contracts` (URL-префикс `api/contracts/v1/`) — учёт договоров с контролем бюджета. Отвечает на один вопрос: **сколько из выделенного бюджета уже законтрактовано и сколько осталось.** Frontend'а пока нет — только API и django-admin.

Три слоя моделей (`apps/contracts/models.py`):

- **Справочники бюджета** — `Country`, `Program` (название + статья расходов в одной строке; подпись — `display_name`, «код название», код необязателен), `Administrator` (держатель бюджетных строк — **проект + страна**, без ФИО и **без денег на самой записи**; подпись «проект страна» собирает `Administrator.display_name`), `Budget` (выделенная сумма на связку администратор × программа × год, уникальную).
- **Реестр контрагентов** — `Counterparty` (БИН/ИИН, НДС — **булев признак** «с НДС / без НДС», контакты, адрес, страна, статус). В спецификации заказчика таблица называется «Реестр контрактов», но её поля — атрибуты контрагента, а не договора.
- **`Agreement`** — единственная транзакционная сущность. Ссылается на ОДНУ бюджетную строку; администратор и программа читаются через неё, отдельных колонок на договоре нет (иначе было бы две версии правды о том, из какого кармана деньги).

**Ключевой инвариант: остаток бюджета не хранится.** `committed`/`remaining` считаются в `services/budget_calc.py` как `amount − SUM(договоры в COMMITTING_STATUSES)`. Хранимый баланс, который декрементируют при создании договора, расходится с реальностью при первом же редактировании суммы, удалении или расторжении — и потом нет способа узнать, какая цифра верна. Колонок под эти поля в таблице нет и заводить их не нужно.

`COMMITTING_STATUSES` (там же) — единственное место, где зафиксировано, **с какого статуса договор занимает бюджет**: сейчас всё, кроме `draft` и `terminated`. Это открытый вопрос к заказчику; меняется правкой одного множества, ни модели, ни схемы, ни вьюхи трогать не придётся.

**Согласование подключено — через `apps.signoff`, не через `apps.approvals`.** `Budget`, `Counterparty` и `Agreement` наследуют примесь `signoff.Approvable` (колонка `approval_state` в их собственных таблицах), а `apps/contracts/approval_hooks.py` из `ContractsConfig.ready()` регистрирует три типа с колбэками. Подробности механики — §3.6; здесь важны три следствия:

- **Права изменились.** Создание бюджета/контрагента/договора и отправка их на согласование — `auth="jwt"` (любой сотрудник); правка, удаление, смена статуса и весь справочный слой остались `admin=True`. Контролем служит согласование, а не админский флаг: если завести бюджет может только администратор, маршрут из трёх этапов над бюджетами нечего согласовывать. Скан договора прикладывает автор, пока договор черновик, либо администратор всегда.
- **Несогласованное не расходуется.** `agreement_service._validate_context` отбивает несогласованный бюджет как источник денег и несогласованного контрагента как сторону — **но только если для этого типа заведён активный маршрут** (`signoff.has_active_route`). Без маршрутов ничего не блокируется: все существующие строки — `draft`, и безусловная проверка сломала бы модуль в день выката. Выключенный signoff гейт снимает, а не роняет contracts.
- **У договора две оси состояния.** `status` — жизненный цикл записи, `approval_state` — место в маршруте. Связаны они в одном месте: `approval_hooks` двигает `status` по `ALLOWED_TRANSITIONS` (`draft → on_review` на отправку, `→ approved` на согласование, отказ и отзыв возвращают в `draft`). Обратите внимание: `on_review` уже занимает бюджет (`COMMITTING_STATUSES`), поэтому лимит проверяется ДО запуска процесса.

Отложены по-прежнему: учёт фактических платежей/актов, несколько файлов на договор, финансирование из нескольких бюджетных строк, мультивалютность.

### 3.6 Signoff — универсальное согласование

`apps.signoff` (URL-префикс `api/signoff/v1/`) — движок согласования, который ничего не знает о предметных аппках. Frontend — [frontend/src/pages/signoff/](frontend/src/pages/signoff/) (инбокс, список и карточка процесса, редактор маршрутов) + [frontend/src/api/signoff.ts](frontend/src/api/signoff.ts).

**Чем отличается от `apps.approvals`.** У `approvals` единица согласования — `RequestInstance`, строка с JSON-значениями формы, которую она же и спроектировала; указать ею на существующий `Budget` невозможно. `signoff` согласует строку в ЧУЖОЙ таблице, адресуя её парой `(subject_type, subject_id)` — `"contracts.budget"` + pk. Ни `ContentType`, ни междоменного FK: `ContentType` дал бы обходной путь к чужим моделям через `content_type.model_class()`.

**Как перевёрнута зависимость.** Движок не имеет права импортировать `apps.contracts.models`, но обязан уметь две вещи с чужим объектом: сообщить ему результат и показать его человеку. Поэтому предметная аппка сама приходит из `AppConfig.ready()` и отдаёт `signoff.register_subject(...)` три вещи: **класс модели** (signoff ведёт на нём свою колонку `approval_state`), **колбэки** доменных последствий и **`describe`** — способ построить заголовок и ссылку. Импорт идёт только в сторону `contracts → signoff.interface`.

**Модель маршрута.** `ApprovalRoute` → `ApprovalRouteStage` → `ApprovalRouteStageApprover`. Параллельность выражена одним числом: этапы с ОДИНАКОВЫМ `order` идут параллельно, с разным — последовательно. Отдельной модели графа нет намеренно — заказчику нужны «2, 3 или 5 этапов, параллельно или друг за другом», а это ровно то, что выражает целочисленный порядок (ср. `apps.approvals` с его условными переходами — на порядок дороже). Согласующие перечисляются явными user id: платформенных групп нет, `User` сознательно без `PermissionsMixin` (решение Р1 заказчика), поэтому смысл несёт **имя этапа**, а не роль. Активный маршрут на тип — ровно один (частичный уникальный индекс).

**Условные ветки** (`services/conditions.py`). Группа этапов по `order` — она же и ветвление: у этапа есть `condition`, и в процесс он попадает, только если условие сошлось на ФАКТАХ объекта. Отдельной модели ветки нет по той же причине, по которой нет модели графа. Типовой маршрут заказчика — «двое проверяют → согласует ответственный за страну администратора бюджета → один утверждает» — это три группы `order`, во второй по этапу на страну.

- **Факты даёт предметная аппка**, как и всё остальное про чужой объект: `register_subject(..., facts=…, fact_fields=…)`. `facts(subject_id)` снимает плоский словарь скаляров (`{"admin_country_id": 3}`), `fact_fields()` объявляет, что из него можно спрашивать и как показать это в редакторе (тип + справочник значений). Движок сравнивает скаляры и не знает, что такое страна, — поэтому ветвление работает для ЛЮБОГО типа, и включение его для новой модели не требует правок в signoff.
- **Формат условия** — плоский список предикатов, соединённых И: `[{"field", "op", "value"}]`, операторы `eq/in/not_in/gt/gte/lt/lte`. Вложенности и ИЛИ между полями нет намеренно: ИЛИ по одному полю — это `in`, по разным — два этапа в одной группе.
- **Пустая группа — ОТКАЗ на запуске, а не пропуск.** Завели страну, забыли ветку — и бюджет тихо прошёл бы мимо финконтроля, чего никто бы не заметил. Поэтому группа без единого прошедшего этапа роняет запуск (409 с перечислением фактов), а «для прочих — вот этот» выражается явным этапом `is_fallback`. Ту же дыру редактор маршрута показывает заранее (`coverage_gaps` в `GET /routes/{id}`).
- **Ветки считаются один раз, на запуске**, до снимка — как и всё в снимке. Ни правка маршрута, ни правка самого объекта уже идущий процесс не переигрывают. Что именно было решено, видно в `ApprovalProcess.subject_facts` и в `ApprovalProcessStage.condition`/`matched_by`.

**Этап подписи** (`approver_kind` + `requires_attachment` на этапе). Два независимых флага, вместе дающие «последним подписывает автор, приложив PDF»:

- **`approver_kind = initiator`** — согласующего в маршруте нет, он вычисляется на запуске из `ApprovalProcess.initiator_id`. Именно инициатор, а не «автор документа»: `Agreement.created_by` лежит за границей аппки, а в contracts эти двое совпадают по бизнес-процессу. Названных поимённо согласующих у такого этапа быть не может (409/422), кворум для него бессмыслен — задача ровно одна. Это НЕ роль и не группа: вычисляется один конкретный пользователь из данных самого процесса, ровно как разбирается ветвление.
- **`requires_attachment`** — этап можно СОГЛАСОВАТЬ только с уже приложенным к задаче PDF (`ApprovalTask.file_id`). Для отказа документ не нужен: того, что отказавшему полагалось бы подписать, не существует. Файл прикладывается отдельным запросом ДО решения (`services/attachments.py`, `POST /tasks/{id}/attachment`) — загрузка в S3 не должна идти внутри транзакции, держащей блокировку процесса. PDF-only задаёт политика scope `signoff_doc` в media_files (она же включает проверку magic-байтов), а не проверка в signoff. Приложить может ТОЛЬКО адресат запроса: администраторского исключения нет — загрузка за согласующего была бы подделкой подписи.
- **«Последний этап» — не сущность.** Процесс завершается, когда пройдена группа с наибольшим `order`, поэтому подпись, оказавшаяся не последней, тихо превращается в промежуточное подтверждение. Запрета на это нет (иначе после подписи нельзя было бы добавить ни одного этапа), есть предупреждение редактору — `initiator_stage_not_last` в `GET /routes/{id}`, рядом с `coverage_gaps`.

**Процесс.** `ApprovalProcess` → `ApprovalProcessStage` → `ApprovalTask` + `ApprovalEvent` (журнал). Этапы процесса — **снимок маршрута на момент запуска**: правка маршрута не трогает уже идущие согласования. Инварианты движка (`services/engine.py`):

- **Отказ решает сразу** — любой отказ на любом этапе отклоняет весь процесс, оставшиеся запросы гасятся как `skipped`, а не висят.
- **Группа этапов проходится целиком** — следующий `order` активируется, только когда все этапы текущего согласованы.
- **Колбэк предметной аппки — внутри транзакции, уведомление — после коммита.** Состояние процесса и состояние объекта обязаны стать согласованными атомарно; рассылка в мессенджер — внешний эффект, идёт через `transaction.on_commit`.
- **Все переходы берут `SELECT … FOR UPDATE` на строку процесса.** Без этого два согласующих, одновременно закрывающих последнюю параллельную пару этапов, оба увидели бы «все согласовали» и оба дёрнули бы `on_approved`.

**Как подключить новый тип** — три шага, ни одного в самом signoff: модель наследует `signoff.Approvable` и объявляет `SIGNOFF_SUBJECT_TYPE`; миграция добавляет `approval_state`; `AppConfig.ready()` зовёт свой `approval_hooks.register()`. Ветвление — четвёртый, необязательный: добавить в тот же вызов `facts`/`fact_fields`. Образец — `apps/contracts/approval_hooks.py`, минимальный — `apps/signoff/tests/testapp/`.

Одна ловушка при переносе на новый тип: **ключи фактов называются по смыслу, а не по типу**. У договора стран две — администратора бюджета и контрагента, — и они регулярно разные; общий ключ `country_id` означал бы, что настраивающий маршрут выберет одну из них наугад и не узнает об этом. Отсюда `admin_country_id` / `counterparty_country_id`. Обратная сторона того же правила — `program_id` у договора идёт БЕЗ приставки: программа у него ровно одна (договор → строка бюджета → программа), и уточнять там нечего.

Что сейчас объявлено в `apps/contracts/approval_hooks.py`: бюджет — `admin_country_id`, `period_year`, `currency`, `amount`; контрагент — `counterparty_country_id`, `vat`; договор — `admin_country_id`, `counterparty_country_id`, `program_id`, `amount`, `currency`, `payment_type`. Ветвить бюджет по программе нельзя и не будет: бюджет — контейнер из N строк, то есть N программ, а `conditions.normalize_facts` принимает только скаляры. Это упёрлось бы в новый тип факта-списка и операторы вида `contains` в самом signoff, а не в правку contracts.

⚠️ **Справочник под choice-полем обязан быть непустым.** `conditions.validate_fields` роняет ВЕСЬ список полей типа, если у любого `choice` пустые `options`, а `SubjectsView._fields` глушит это в `[]`. Практический эффект: на свежей установке без заведённых стран И программ редактор маршрута для «Договора» не покажет ни одного условия — включая те, чьи справочники заполнены. Данные это чинят сами (ни бюджет, ни договор не завести без страны и программы), но при настройке маршрутов ДО ввода данных выглядит как сломанный редактор.

---

## 4. Frontend (`frontend/`)

React 18 + Vite + TypeScript. shadcn/ui (Radix + Tailwind), TanStack Query, i18next. Тесты: Vitest + Playwright. **Не затронут миграцией бэкенда** — тот же код, тот же роутинг по `/api/<domain>/v1/*` (пути не изменились, изменился только сервер, который на них отвечает).

```
frontend/src/
├── main.tsx   App.tsx   index.css   i18n.js
├── app/
│   ├── routing/        # ⭐ routeDefinitions.ts, lazyPages.ts, prefetch.ts
│   └── components/
├── pages/              # ⭐ Точки входа роутов (Index, Login, Admin*, HR*, Calendar, Email/, hr/, public/, requests/)
│   ├── Email/          # OAuth callback, inbox, compose modal, settings panel
│   └── hr/             # HR-страницы (Departments, Employees, Vacancies, Tasks, Roadmap, …)
├── features/
│   ├── messenger/      # MessengerPage + api/ + hooks/ + types.ts (feature-sliced)
│   └── requests/       # ⭐ RequestsLayout + pages/ + components/ + hooks.ts + types.ts
├── components/
│   ├── ui/             # shadcn primitives (50+ компонентов)
│   ├── hr/ tasks/ calendar/ profile/   # Доменные компоненты
│   └── *.tsx           # Лендинг-секции, Header/Footer, RequireAuth и т.д.
├── api/                # ⭐ HTTP-клиенты по домену:
│                       #   client.ts (base axios+JWT), endpoints.ts (карта префиксов),
│                       #   users.ts, hr.ts, tasks.ts, requests.ts, cms.ts, media.ts,
│                       #   calendar.ts, email.ts, fileManager.ts, search.ts (глобальный fan-out поиск)
├── services/           # emailService.ts (тонкие обёртки над api/)
├── hooks/              # useActiveProfile, useHRLevel, use-mobile, use-toast, …
├── lib/
│   ├── auth/           # profileStorage.ts, roles.ts (RBAC хелперы)
│   ├── transport/      # IMediaTransport + WebRTCAdapter
│   ├── webrtc/         # ⭐ MediaEngine, WebRTCManager, SignalingClient (WS+WebTransport), SdpMunger, BitrateController
│   ├── telemetry.ts    # Frontend → backend client-errors
│   └── utils.ts        # cn() и общие хелперы
├── data/               # Статика лендинга (contacts.ts, projects.ts, services.ts)
├── locales/            # ru/kz/en JSON (см. check-i18n.mjs / update_i18n.py)
├── types/              # Глобальные TS-типы
└── test/               # Vitest setup
```

**Где что искать:**
- Новый роут — `app/routing/routeDefinitions.ts` + лениво в `lazyPages.ts` + страница в `pages/`.
- Новый API-клиент — `api/<domain>.ts`, базовый axios + JWT-интерсептор в `api/client.ts`, префиксы — в `api/endpoints.ts`.
- Глобальный поиск (`api/search.ts`) — fan-out: параллельно дёргает list-эндпойнты доменов и мёржит (упавший источник, напр. 403/503-disabled, молча игнорится).
- Доменная фича крупнее одной страницы — `features/<name>/` (как `messenger`, `requests`).
- UI-примитив — `components/ui/` (shadcn). Доменный — `components/<domain>/`.

**Известный хвост:** несколько мест во фронтенде (`pages/AdminUsers.tsx`, `components/profile/ProfileSidebar.tsx`, `components/admin/UserEditDialog.tsx`, `App.tsx`) всё ещё ссылаются на `/sqladmin` — этой панели больше нет (см. §3.1, §6, [API.md](./API.md)). Не бэкенд-докой чинится — фронтенд-код вне скоупа этого файла, но имей в виду при отладке "битой" ссылки на админку.

---

## 4.1 Email (`apps.mail`) — дуальная архитектура (corp + personal)

С одной страницы [/email](frontend/src/pages/Email/EmailPage.tsx) пользователь работает с **корпоративным ящиком** (Mailcow) и подключёнными **личными** Gmail / Outlook — переключение через account-selector в сайдбаре. Код — [backend/apps/mail/](./backend/apps/mail/), перенесён из `services/email` практически 1:1 по контракту.

**Pivot-таблица:** одна `mail_emailaccount` строка на mailbox (Django-имя таблицы; логически — та же `email_accounts`). CHECK-consistency с провайдером сохранена в `apps/mail/models.py`:
```
EmailAccount(id, user_id, type=corporate|personal, provider=mailcow|google|microsoft,
             address, is_default, is_active,
             mailbox → ProvisionedMailbox (1:1, corporate),
             oauth_token → OAuthToken (1:1, personal),
             sync_state JSONB, last_sync_at, watch_expires_at)
```

**Sync** ([apps/mail/services/sync/](backend/apps/mail/services/sync/)):
- `gmail.py` — `users.history.list` + `messages.list`/`get`; push через `users.watch` → Pub/Sub
- `microsoft.py` — `/me/messages/delta` + persisted `@odata.deltaLink`; push через Graph subscriptions
- `mailcow_imap.py` — IMAP backfill; live-push через `python manage.py run_imap_idle` (замена отдельного `email-imap-idle`-контейнера FastAPI-эпохи)
- UPSERT с `(account_id, message_id)` UNIQUE → идемпотентно
- `pg_try_advisory_lock` сериализует concurrent runs (`_try_advisory_lock` в `apps/mail/tasks.py`)

**Push-приёмники** ([apps/mail/webhooks.py](backend/apps/mail/webhooks.py)) — `POST /api/email/v1/webhooks/{gmail,microsoft,mailcow}`, public, БЕЗ rate-limit на nginx-уровне (см. §6). Auth: Gmail Bearer JWT (google-auth) + fallback token; Graph initial `validationToken` echo.

**Send** ([apps/mail/services/sender/](backend/apps/mail/services/sender/)) — стратегия по `provider`: Gmail API `messages.send` (base64url MIME), Graph `/me/sendMail` (JSON), Mailcow SMTP 587 STARTTLS. `POST /api/email/v1/send` ставит `folder='outbox'` + `deliver_email.delay(...)` (Celery-таск, `apps/mail/tasks.py`, вместо Dramatiq-актора).

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

**Projects + TaskType registry:**
```
Project(id, name, status=active|completed|archived, color, start_date, end_date, owner_id, department_id)
TaskType(id, slug UNIQUE, name, color, icon, is_system)   # user-extensible, 5 системных строк
Task.project_id   → Project(id)   ON DELETE SET NULL   # NULL = standalone
Task.task_type_id → TaskType(id) ON DELETE SET NULL
```
Роудмап ([HRRoadmap.tsx](frontend/src/pages/hr/HRRoadmap.tsx)) рендерит проекты → дерево задач по `parent_id`.
```
GET/POST/PATCH/DELETE /api/tasks/v1/projects/[{id}/]   •   GET …/projects/{id}/tasks/
GET/POST/PATCH/DELETE /api/tasks/v1/task-types/[{id}/]
```

**Сервисы** ([apps/tasks/services/](backend/apps/tasks/services/)): `task_service.py`, `task_content_service.py`, `task_response.py`, `project_service.py`, `sequence_service.py` (Jira-style ключи), `calendar_service.py`, `production_calendar.py` (казахстанские праздники), `gantt_service.py`, `link_service.py`, `notification_service.py`, `reference_service.py`, `hydration.py`.

**Kanban** ([KanbanBoard.tsx](frontend/src/components/tasks/KanbanBoard.tsx)) — без изменений на фронте.

---

## 5. Видео/конференции

| Компонент | Где | Что делает |
|---|---|---|
| **SFU** | [sfu/src/server.ts](./sfu/src/server.ts), [sfu/src/room.ts](./sfu/src/room.ts) | Mediasoup SFU, медиа-роутинг. Кодеки: `media-codecs.config.json`. Не тронут миграцией. |
| **WebTransport proxy** | [webtransport/server.py](./webtransport/server.py) | QUIC-сигнализация (aioquic) для SFU. Не тронут миграцией. |
| **Frontend WebRTC** | [frontend/src/lib/webrtc/](./frontend/src/lib/webrtc/) | `MediaEngine`, `WebRTCManager`, `SignalingClient`(WS)/`WebTransportSignalingClient`, `SdpMunger`, `BitrateController`. |
| **UI** | [frontend/src/pages/ConferencePage.tsx](./frontend/src/pages/ConferencePage.tsx) | Страница конференции. |
| **Конфиг конференции** | `apps.cms.services.conference_service` ([backend/apps/cms/services/conference_service.py](backend/apps/cms/services/conference_service.py)), `GET /api/cms/v1/conference/config` | Статический ICE/SFU-конфиг из `htqweb/settings/base.py` (`CONFERENCE_SFU_URL`/`_PATH`/`ICE_SERVERS`) — порт `services/cms/app/data/conference.yaml`. Сам SFU-стек (`conference` в реестре) по умолчанию выключен через `ServiceStatus`, но статический конфиг отдаётся всегда. |

Туннели/HTTPS для LAN: [docs/TUNNEL_SETUP.md](./docs/TUNNEL_SETUP.md), скрипты — [scripts/start-sfu-tunnel.ps1](./scripts/start-sfu-tunnel.ps1).

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
/api/                    → backend        (все остальные домены — users/hr/tasks/requests/cms/mail/messenger)
/ws/sfu/                 → sfu:4443       (WebRTC-сигналинг, не Django)
/django-admin/           → backend
/static/                 → backend        (collectstatic)
/grafana/  /prometheus/  → grafana / prometheus (наблюдаемость, см. §8)
/                        → frontend (Vite-сборка через nginx)
```
> `/sqladmin/*` и `/mongo-admin` **убраны** — старой sqladmin/AdminJS-панели больше нет, база администрируется через `/django-admin/` (см. §3.1, §10).

При добавлении эндпойнта: роутер в `backend/apps/<domain>/views.py` → зарегистрировать в `backend/apps/<domain>/urls.py` (оба написания — со слешем и без, `APPEND_SLASH=False`) → nginx трогать НЕ нужно (уже проксирует весь `/api/`, кроме уже выделенных под особые лимиты location'ов выше). Полный контракт — в [API.md](./API.md).

---

## 7. БД, миграции, фоновые задачи

- **PostgreSQL** — Django ходит **напрямую** (`DB_HOST=db DB_PORT=5432`, `psycopg`, синхронно, `CONN_MAX_AGE=0` — пул на уровне приложения, не внешнего пулера). PgBouncer (`:6432`) остаётся в compose для хостовых утилит/ручного `psql`, но в путь живого запроса больше не входит.
- **Схема:** одна `public`. Имена таблиц — **стандартные Django** `<app_label>_<model>` (например `hr_department`, `tasks_task`, `mail_emailaccount`, `users_user`) — никакого ручного префиксования: раньше (`hr_*`, `task_*`, `request_*`…) это было вынужденной адаптацией под то, что PgBouncer в transaction-режиме сбрасывал `search_path`; в Django-монолите такой проблемы нет (см. §10 — как было).
- **MongoDB — убрана.** HR-документы, раньше лежавшие в `htqweb_docs`, теперь обычные Django-модели/файлы через `apps.media_files`.
- **Миграции:** обычные Django `makemigrations`/`migrate`, `managed=True`. Никакого Alembic, никакого ручного управления транзакцией миграции.
- **Фоновые задачи:** Celery (Redis-брокер `redis://redis:6379/2` — задаётся `x-django-env` в `docker-compose.yml` и одинаков в проде и dev-оверлее, который эту переменную не переопределяет; `/9` — это лишь запасной дефолт в `htqweb/settings/base.py` на случай запуска `manage.py` вне docker-compose. Результаты — `django-celery-results`, периодика — `django-celery-beat` DatabaseScheduler). Объявление — `apps/<domain>/tasks.py`, `@shared_task`, обязательная первая строка `require_service("<name>")` (метатест-конвенция потоков). Мониторинг — Flower (`:5555`). Отдельные `<svc>-worker`/`<svc>-scheduler`-контейнеры на домен — история; теперь один `backend-worker` + один `backend-beat` на всю платформу.
- **Идентификация:** `apps.users` сам выпускает и валидирует JWT, `iss=htqweb-auth` (см. `htqweb/settings/base.py::JWT_ISSUER`) — имя issuer'а не изменилось с FastAPI-эпохи, хотя отдельного `user-service` больше нет.
- **ETL (фаза 10, разовая операция при cutover):** `apps/<domain>/management/commands/etl_<domain>.py` (hr/mail/messenger/task/requests(`etl_requests`)/media) + общий хелпер [`apps/core/etl.py`](backend/apps/core/etl.py) — read-only курсор в legacy-Postgres (порт `:55432`) + детерминированный per-row hash для сверки count+hash между legacy-схемой и новыми Django-таблицами. `--dry-run`/`--verify`/`--limit`/`--source-dsn` флаги у каждой команды.

### 7.1 Объектное хранилище (S3 / MinIO)

> Манифест поменялся с миграцией: раньше было «1 микросервис = 1 бакет»; теперь файловый ввод-вывод **консолидирован** — большинство доменов (hr, mail, messenger) пишут через `apps.media_files.interface` (`store_file`/`get_file_url`/`delete_file`), а не держат свой собственный `s3_storage.py`-клон. Исключение — `cms`, у которого остался свой бакет и прямой доступ к `htqweb.storage` (пилотная аппка, появилась раньше `media_files`).

В dev — контейнер **MinIO** в [docker-compose.dev.yml](./docker-compose.dev.yml) (консоль `:9001`). При первом запуске `minio-bootstrap` создаёт бакеты (в т.ч. исторические `htqweb-messenger`/`htqweb-mail-attachments`/`htqweb-conferences`, которые сейчас ничем не заполняются — см. ниже). В проде — настоящий S3, сменой `S3_ENDPOINT` без правок кода.

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
| Метрики backend'а | ⚠️ Пока НЕТ: `/metrics` не выставлен (старая `libs/htqweb_metrics` снесена вместе с FastAPI; `django-prometheus` не установлен — задача закомментирована в `infra/logging/prometheus/prometheus.yml`). Prometheus сейчас скрейпит только себя + postgres/redis-exporter + MinIO + Loki + Grafana. |
| Аудиты/анализы | [docs/audit-2026-04-28/](./docs/audit-2026-04-28/), [docs/static-analysis-2026-04-28.md](./docs/static-analysis-2026-04-28.md), [docs/dependency-audit-2026-04-28.md](./docs/dependency-audit-2026-04-28.md) — из FastAPI-эпохи, не обновлялись под Django |
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
| Фоновая задача | `backend/apps/<domain>/tasks.py` (`@shared_task`, первая строка `require_service`) |
| Периодика (cron) | Django-миграция данных для `django_celery_beat.PeriodicTask` — см. `apps/mail/migrations/0004_mail_periodic_tasks.py` как образец |
| Включить/выключить домен | `manage.py service <name> --on/--off` (см. `apps/core/management/commands/service.py`) |
| Django-admin страница | `backend/apps/<domain>/admin.py` — `ModelAdmin`, обёрнутый в `htqweb.admin_gate.ServiceGatedAdminMixin` |
| Новый фронтенд-роут/страница | `frontend/src/app/routing/routeDefinitions.ts` + `pages/<Name>.tsx` |
| HTTP-вызов из фронтенда | `frontend/src/api/<domain>.ts` (axios через `client.ts`, префиксы в `endpoints.ts`) — без изменений |
| Доменная UI-фича | `frontend/src/features/<name>/` (масштаб > одной страницы) |
| Локализация | `frontend/src/locales/{ru,kz,en}/*.json` (валидатор `check-i18n.mjs`) |
| Конференц-логика на клиенте | `frontend/src/lib/webrtc/` |
| SFU/медиа | `sfu/src/` |
| Загрузить/отдать файл (из бэкенда) | `apps.media_files.interface.store_file()`/`.get_file_url()` (соседи); `htqweb.storage.get_storage()` напрямую — только `apps.cms` |
| Шлюз/маршрутизация | `infra/nginx/default.conf` (прод) / `frontend/vite.config.ts` (dev) |
| Compose / порты / переменные | `docker-compose.yml` (+ `docker-compose.dev.yml` dev, `docker-compose.test.yml` тесты) |
| Перелить legacy-данные (cutover) | `manage.py etl_<domain>` — см. `apps/core/etl.py` за общими хелперами |

---

## 10. Известные «ловушки»

- **`/sqladmin/`, `/mongo-admin` больше не существуют.** Несколько мест во фронтенде всё ещё на них ссылаются (см. §4) — это не 503 «сервис выключен», это честный 404/дохлая ссылка, потому что маршрута нет вовсе ни в nginx, ни во Vite-proxy. Админка — `/django-admin/`.
- **`POST /api/users/v1/admin-session/login`/`/logout` — код существует, но реального потребителя больше нет.** Эти эндпойнты ставили `admin_session`-cookie для входа в sqladmin; сам sqladmin снесён, а `django-admin` использует свою обычную Django session-аутентификацию (не эту JWT-cookie). Не удивляться, что "рабочий" эндпойнт никуда не ведёт.
- **Схема ≠ schema-per-service — эта проблема ИСЧЕЗЛА, а не "решена префиксами".** В FastAPI-эпоху PgBouncer (transaction-режим) сбрасывал `search_path`, что вынуждало держать все сервисы в `public` с ручными префиксами таблиц. В Django-монолите Postgres — прямое подключение, префиксы — стандартные Django `<app_label>_<model>`, руками ничего не мэнеджится. Если видишь код/комментарий про «schema-per-service» — это history, не текущая реальность.
- **JWT issuer — `htqweb-auth`**, как и раньше (не `users`, не `django`). `apps.users` выпускает и валидирует сам, без отдельного identity-сервиса.
- **`docker-compose.django.yml`/`RUN-DJANGO-CHECK.md`** описывают промежуточный, давно перегнанный proof-of-concept (только 4 домена из 8 были перенесены на момент их написания). Не путать с боевым `docker-compose.yml` — актуальны только `docker-compose.yml`+`docker-compose.dev.yml`(+`.test.yml`).
- **`docs/architecture.md` не в ногу с реальным деревом** — упоминает DRF ViewSets и `backend/tasks/viewsets/`, чего в репозитории нет (реальность: `htqweb.http.api_view`, `backend/apps/tasks/`). Похоже на неадаптированный шаблон; не источник истины по структуре, см. §1/CLAUDE.md.
- **`scripts/generate-monitoring-traffic.sh`** всё ещё бьёт по старым портам микросервисов (`:8005`–`:8012`) — не работает против текущего `backend-web:8000`/`backend-asgi:8001` без переписывания.
- **`apps.media_files` — общая точка отказа для файлов** трёх доменов (hr/mail/messenger) плюс аватарок users. Если он выключен через `ServiceStatus` (`manage.py service media --off`), у соседей это всплывёт как `ServiceDisabled`/503, а не как их собственная ошибка — смотреть на `service` в JSON-конверте, прежде чем искать баг в вызывающей аппке.
- **Изоляция аппок — всё ещё исполняемое правило, не конвенция на доверии.** `apps/core/tests/test_app_isolation.py` гоняется в обычном test run'е (`pytest`, `cd backend`) — а не отдельным линтом, который можно забыть запустить.
- **Метрик backend'а нет.** Не искать `/metrics` на `backend-web`/`backend-asgi` — не выставлен (см. §8). Дашборды Grafana, которые ссылаются на метрики Django-процесса, будут пустыми до тех пор, пока не поставят `django-prometheus`.
