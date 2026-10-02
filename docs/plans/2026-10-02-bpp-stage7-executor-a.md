# БЗО, этап 7 — план исполнителя A (Санжар, ветка `new-module-BPP-sanzhar`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** задачи вне критического пути модуля (мастер-план §5, этап 7) и хвосты этапа 6:
- **A7.1** — календарь отдельной аппкой: производственный календарь — общий (`public`), события — в схеме компании, API для фронта и конференций сохраняется;
- **A7.2** — блокировка входа после 5 неудач на 15 минут и лимит 300 запросов в минуту на пользователя (D-37);
- **A7.3** — заготовки 1С: клиент OData, сопоставление по `ext_1c_ref`, идемпотентный upsert контрагентов и «Проектов» без запуска синхронизации (D-38);
- **A7.4** — ClamAV: эксплуатационная часть (D-31) — сканер уже встроен, не хватает проверки здоровья, метрик, ранбука включения;
- **хвосты этапа 6** — привлечение партнёра к договору модуля (M-5 итогового ревью), имена в карточке «Проекта», мелочи из журнала.

**Стартовая точка:** `new-module-BPP-sanzhar` после сведения с веткой B 02.10 (`778eb74`: этап 6 A + PR #44 Руслана) и слияния PR #45 в `new-module-BPP-merge`. Связка «доска задач ↔ Проект» — версия B (сверка B §25–26), миграции: связка досок `tasks/0023`–`0024`, партнёр → контрагент `tasks/0025`, узлы `.all` — `access/0021`.

**Architecture:**
- **A7.1.** Две части, потому что аппка в Django либо тенантная, либо общая целиком (`settings.TENANT_APPS` — по метке аппки):
  - **производственный календарь** — справочник `refdata` (`public`): таблица ручных переопределений дня и расчёт рабочих дней поверх `apps/core/kz_holidays.py`. Справочники ведёт управляющая компания (решение модуля), праздники РК у всех компаний одни;
  - **события** — новая тенантная аппка `calendar`: модели `CalendarEvent`, `EventException`, `CalendarEventParticipant` переезжают **только состоянием** (`SeparateDatabaseAndState`, `db_table` прежние `tasks_*`) — физически в схемах компаний ничего не двигается, `id` событий сохраняются (на них ссылается `conference.ConferenceSession.calendar_event_id`).
- **A7.2.** Платформенный модуль `htqweb/ratelimit.py` (рядом с `idempotency.py`) на кэше Redis: счётчик неудач входа по логину и окно запросов по пользователю. Блокировка — в выдаче токена, лимит — в `api_view` сразу после разбора токена. Redis недоступен — механизмы не действуют (fail-open, как весь кэш платформы), это слышно через `htqweb.fallback`.
- **A7.3.** Клиент OData — общий (`htqweb/integrations/onec.py`), upsert — у владельцев данных: контрагент — `bpp`, «Проект» — `project`. Выключатель — пустой `ONEC_ODATA_URL`, как у антивируса. Ни Celery-задачи, ни команды синхронизации нет — только проверка связи.
- **A7.4.** Код сканера не меняется; задача — compose, наблюдаемость, ранбук и проверка на настоящем `clamd`.

**Tech Stack:** Django 5.2.7 на Python 3.14, PostgreSQL (схема на компанию), Redis, Celery; React 18 + TypeScript, vitest; ClamAV 1.4; httpx.

**Spec:**
- [Мастер-план](2026-09-26-bpp-master-plan.md): §5 этап 7 (A7.1–A7.4); решения D-31, D-37, D-38; §7 «Изменения к ТЗ» (§27 — 300 запросов/мин).
- [Вопросы](2026-09-25-bpp-open-questions.md): Q-C11, Q-E19 (календарь), Q-C31, Q-E21, Q-B33 (лимиты), Q-B34, В-17 (1С), Q-B25 (антивирус).
- ТЗ `docs/tz/TZ-budget-procurement-payments-v1.0.md` §27 (НФТ).
- Итоговое ревью этапа 6 — `.superpowers/sdd/2026-10-01-bpp-stage6-executor-a/final-review.md` (M-5); сверка B §26 (имена в карточке «Проекта»).

---

## Решения этого плана

**D-S7-1. Производственный календарь — в `refdata`, один на группу.**
- Сегодня это таблица переопределений `tasks.ProductionDay` в схеме каждой компании; базовый календарь (выходные и праздники РК) считается кодом `apps/core/kz_holidays.py`. Строки появляются только от `PATCH production-calendar/<date>/` — ни сид, ни миграция их не пишут.
- Переезд: модель `refdata.ProductionDay` (`public`), функции расчёта — `refdata.interface` (`day_type`, `is_working_day`, `working_days_between`, `days_between`, `add_working_days`). Перенос строк из всех `co_*` — data-миграцией с отчётом; две компании с разным типом одного дня — стоп с перечнем (ожидается пусто; проверить запросом до миграции).
- **Правка — узел `refdata.production_calendar`** (как остальные справочники управляющей компании), чтение — всем. Сегодня день правит любой держатель `tasks:write` — это сужение прав, оно в списке «Довести до Алгазы».
- Календарь `hr` (`hr.CalendarDay`, смены, нормы часов) не трогаем: это другой календарь — график работы, а не производственный календарь РК.

**D-S7-2. События — новая тенантная аппка `calendar`, таблицы на месте.**
- Модели переезжают `SeparateDatabaseAndState`: в `tasks` — удаление из состояния, в `calendar/0001` — создание в состоянии с `db_table="tasks_calendarevent"` и т. д. В схемах компаний — ни одного DDL; переименование таблиц — contract-миграцией этапа 8, если понадобится.
- API: новый префикс `/api/calendar/v1/` (сервис `calendar` в `KNOWN_SERVICES` и `CORE_MODULES` — календарь нужен всем, как мессенджер); старые пути `/api/tasks/v1/calendar/*` и `/api/tasks/v1/production-calendar/*` — алиасы на те же вьюхи на один релиз (фронт переходит сразу, алиасы ловят закэшированный старый бандл). Снимаются на этапе 8.
- Узел прав: `calendar.events` с теми же строками, что у `tasks.calendar` (миграция `access` копирует строки всех ролей); `tasks.calendar` остаётся до этапа 8 (expand).
- Связи: `calendar` → `tasks.interface` (задачи в «ленте» `timeline`), `tasks` → `refdata.interface` (рабочие дни для сроков задач и план-факта), `conference`/`cms` → `calendar.interface` (встречи). Функции встреч уходят из `tasks.interface` — иначе `tasks` и `calendar` звали бы друг друга.
- Celery: напоминания переезжают в `calendar.tasks` с прежними именами задач (`name="apps.tasks.tasks.calendar_event_reminder"` и `…_dispatch`) — строки `PeriodicTask` на бою уже записаны под этими именами. События уведомлений (`tasks.calendar_invited`, `tasks.calendar_reminder`, `target_type="calendar_event"`) не переименовываются: на них держится дедупликация в центре уведомлений.

**D-S7-3. Блокировка входа — по логину, 5 неудач за 15 минут → 15 минут.**
- Ключ — хеш нормализованного логина (`strip().lower()`, как `_find_user`), не сам логин: логин в ключах Redis и метках не нужен.
- Считаются **все** неудачи, включая неизвестный логин и неактивированную учётку: иначе блокировка выдавала бы, существует ли логин.
- Ответ — 429 с `code: "E-AUTH-LOCKED"` и `Retry-After`; успешный вход сбрасывает счётчик; смена пароля администратором и `manage.py auth_unlock <логин>` снимают блокировку.
- **Refresh не блокируется** (D-37 — «блокировка входа»): уже выданные токены живут до истечения (access 60 мин). Отзыв токенов — вне D-37.
- Цена: чужой логин можно заблокировать пятью неверными паролями — поэтому метрика, алерт и ручное снятие.

**D-S7-4. Лимит 300 запросов в минуту — на пользователя, на всю платформу.**
- Хук — `htqweb/http.py::api_view` сразу после `request.token = payload`, только `auth="jwt"`; фиксированное окно в минуту (`cache.add` + `cache.incr`). Суперпользователь — тоже под лимитом.
- Мимо лимита: SSE `approvals/stream`, Socket.IO мессенджера, `/ws/*`, `/metrics`, `/health`, анонимные ручки — они не идут через JWT-ветку `api_view`.
- Ответ — 429 `E-RATE-01` + `Retry-After`. Настройки — env: `RATE_LIMIT_USER_PER_MIN` (300; `0` — выключено), `AUTH_LOCKOUT_THRESHOLD` (5), `AUTH_LOCKOUT_SECONDS` (900).
- Фронт: 429 больше не повторяется автоматически (`App.tsx::RETRYABLE_4XX`), иначе react-query утроит запросы под лимитом; форма входа показывает текст блокировки.
- nginx: лимиты по IP остаются, `limit_req_status 429` — чтобы фронт получал 429, а не 503 (сейчас `API.md` обещает 429, а nginx отдаёт 503).
- **До включения на бою** — замер профиля запросов SPA по логам nginx/Loki (вопрос Q-S7-4): 300/мин — 5 запросов в секунду, опрос уведомлений и мессенджера на нескольких вкладках может к этому приближаться.

**D-S7-5. 1С — заготовка без запуска.**
- `ext_1c_ref` уникален среди непустых (частичный `UniqueConstraint`) у контрагента `bpp`, «Проекта» и статьи `refdata`; у «Проекта» поле появляется в API (как у контрагента).
- Сопоставление: сначала `ext_1c_ref`, затем естественный ключ (контрагент — страна + рег. номер, «Проект» — код). Найден по естественному ключу с ДРУГИМ непустым `ext_1c_ref` — конфликт в отчёт, без перезаписи. Невалидный БИН — отказ строки в отчёт, а не падение пачки.
- Upsert идёт через сервисы владельцев (`counterparties.service.create/update`, `projects.create/update`) — та же проверка БИН, страны, дублей; повтор с теми же данными ничего не меняет (версия не растёт).
- Отображение полей OData → модель — **предположение** до ответа по публикации 1С (Q-S7-2): справочник `Catalog_Контрагенты` (`Ref_Key`, `Description`, `ИНН`, …), «Проекты» — по ответу.

**D-S7-6. ClamAV по-прежнему выключен по умолчанию.** Включение на бою — отдельным шагом по новому ранбуку, решение пользователя (Q-S7-3). Задача делает так, чтобы включённый сканер был виден: проверка здоровья, метрика, алерт, проверка на EICAR.

---

## Global Constraints

- **Окружение.** pytest — корневой `.venv` на Python 3.14, команды из `backend/`; один прогон за раз; длиннее 10 минут — `nohup`-скриптом.
- **Ветки и коммиты.** Ветки не создавать. Коммитить только файлы своей задачи. Правка в зоне B (`bpp` счёт/договор/подотчёт/заявка, `tasks` доски) — отдельным коммитом «зона B».
- **Межаппный доступ** — только `apps.<x>.interface`; новые связи этапа: `calendar` → `tasks`, `tasks` → `refdata`, `conference`/`cms` → `calendar`. Сторож — `apps/core/tests/test_app_isolation.py`.
- **Тенантные изменения схемы — expand.** Удаление старых узлов прав, алиасов API, переименование таблиц — этап 8.
- **Новая тенантная аппка** (`calendar`) — весь список: `INSTALLED_APPS`, `TENANT_APPS`, `KNOWN_SERVICES`, `CORE_MODULES`, `PREFIX_TO_SERVICE`, `apps.py` с `API_PREFIX`, `access_functions.py`, `holding.py` (`HOLDING_MODELS = ()`), `metrics.py` по необходимости. Пропуск любого пункта роняет `migrate_companies` или сводки холдинга.
- **Ручки** — `api_view(module=…, level=…)` с явным уровнем; сторож `test_gate.py`.
- **Метрики** — без цифр в имени, каждая на панели или в правиле (`test_metrics_are_observed`); Counter вне `collect_all()` — в `_DEFINED_OUTSIDE_APPS`.
- **Фронт.** `t('<ключ>', 'Русский текст')`, ошибки — `reportApiError`; полный `npx vitest run` без новых падений (кроме 8 известных hr); `tsc` не выше 148; `eslint` чисто.
- **Compose.** Новые переменные окружения — во все три файла (`x-django-env`); сверять `git diff docker-compose*.yml`.
- **Документация** — `API.md`, `STRUCTURE.md`, `CLAUDE.md` в той задаче, что меняет ручки или структуру.

## Review Focus

1. **Календарь переехал без потери данных и API.**
   - После `migrate_companies` у компании те же события (`id`, участники, исключения), что до; `conference` находит встречу по комнате.
   - Старые и новые пути отвечают одинаково; напоминание приходит один раз.
   - `migrate_companies` на схеме без событий и на схеме с событиями — без DDL по `tasks_calendar*` (проверка `sqlmigrate`).
   - Тесты — задачи 1–2.
2. **Рабочие дни считаются так же.** Срок задачи по рабочим дням и план-факт до и после переезда календаря совпадают на одном наборе дат (включая переопределённый день и перенос праздника). Тест — задача 1.
3. **Блокировка не выдаёт существование логина и не ломает вход при падении Redis.**
   - Ответы для неизвестного и известного логина под блокировкой одинаковы.
   - Redis недоступен — вход работает, лимит не применяется, `FALLBACK` в логе.
   - Тест — задача 3.
4. **Лимит не задевает потоки и служебные пути.** SSE, Socket.IO, `/metrics`, `/health` — без счётчика; 301-й запрос за минуту — 429 с `Retry-After`; следующая минута — снова 200. Тест — задача 3.
5. **Upsert 1С идемпотентен и не затирает.** Повтор — ноль изменений; конфликт GUID — отчёт, не перезапись; невалидный БИН — отказ строки. Тест — задача 4.
6. **Сканер виден.** Включённый, но мёртвый `clamd` — проверка здоровья красная, алерт, а не только 503 у пользователей. Задача 5.

---

## Волны

- **Волна 1:** задача 1 (производственный календарь → `refdata`, dev1) и задача 3 (блокировка и лимит, dev2).
- **Волна 2:** задача 2 (события → `calendar`, dev1; после задачи 1) и задача 4 (1С, dev2).
- **Волна 3:** задача 5 (ClamAV, dev1) и задача 6 (хвосты этапа 6, dev2).
- **Волна 4:** задача 7 — полный прогон, итоговое ревью, PR.

---

## Task 1: Производственный календарь → `refdata` (A7.1, часть 1)

**Files:**
- Create:
  - `backend/apps/refdata/` — модель `ProductionDay` (поля как у `tasks.ProductionDay`: `date` unique, `day_type`, `note`, `working_days_since_epoch`), `services/production_calendar.py` (перенос `tasks/services/production_calendar.py` и расчётных функций `calendar_service.py:441–544`), ручки `production-calendar/` и `production-calendar/<date>/` в `refdata` (чтение — `refdata:read`, правка — узел `refdata.production_calendar` `edit`);
  - миграции `refdata/00NN_production_day` (таблица) и `refdata/00NN_import_production_days` (data: строки из всех `co_*` по реестру компаний; конфликт — `RuntimeError` с перечнем дат и компаний), узел в `refdata/access_functions.py` + миграция `access` с явной строкой у системных ролей (образец — `access/0008`, `0021`).
- Modify:
  - `backend/apps/refdata/interface.py` — `day_type(date)`, `is_working_day(date)`, `working_days_between(a, b)`, `days_between(a, b, *, production)`, `add_working_days(date, n)`, `production_days(date_from, date_to)`;
  - `backend/apps/tasks/services/{plan_fact,roadmap,sequence,task}_service.py` — рабочие дни через `refdata.interface`; `tasks.ProductionDay` больше не читается (модель и таблица остаются до этапа 8 — expand);
  - `backend/apps/tasks/views.py`, `urls.py` — старые пути `production-calendar*` — алиасы на ручки `refdata` (одна реализация, ответ тот же);
  - `frontend/src/api/calendar.ts` — `fetchProductionCalendar`/`updateProductionDay` на `refdata/v1/production-calendar…`; кнопка правки дня — по `refdata.production_calendar` `edit` (`usePermissions`).

- [ ] **Step 1: Падающие тесты:**
  - `refdata/tests/test_production_calendar.py` — переопределение дня меняет `working_days_between`; перенос праздника из `kz_holidays`; правка без узла — 403;
  - `test_import_production_days` — две компании с одинаковыми переопределениями → одна строка; разные `day_type` на одну дату → стоп с перечнем;
  - `tasks/tests/test_sequence_service.py`, `test_plan_fact.py` — те же сроки, что до переезда (Review Focus 2);
  - старый путь `tasks/v1/production-calendar` отвечает как новый.
- [ ] **Step 2: Реализация.** Фронт: vitest, eslint, tsc.
- [ ] **Документация:** API.md (`refdata` — производственный календарь, алиасы `tasks`), STRUCTURE.md, CLAUDE.md (абзац про календарь).
- [ ] **Коммит** — `feat(refdata,tasks): производственный календарь — общий справочник группы (A7.1, часть 1)`.

## Task 2: События → аппка `calendar` (A7.1, часть 2)

**Files:**
- Create: `backend/apps/calendar/` — `apps.py` (`API_PREFIX = "api/calendar/v1/"`), `models.py` (`CalendarEvent`, `EventException`, `CalendarEventParticipant` с `db_table` прежних таблиц и прежними именами ограничений), `migrations/0001_initial.py` (`SeparateDatabaseAndState`, только состояние), `services/calendar_service.py` (перенос из `tasks`, лента — через новую `tasks.interface.tasks_for_timeline(user_id, start, end)`), `schemas.py`, `views.py`, `urls.py`, `interface.py` (`get_conference_event_for_room`, `list_user_conference_events` — перенос из `tasks.interface`), `tasks.py` (напоминания с прежними `name=`), `access_functions.py` (`calendar.events`), `holding.py`, `admin.py`.
- Modify:
  - `backend/apps/tasks/` — `migrations/00NN_move_calendar_to_calendar_app` (удаление моделей только из состояния, зависимость от `calendar/0001`), `models.py`, `views.py`/`urls.py` (старые пути `calendar/*` — алиасы на вьюхи `calendar`), `schemas.py`, `admin.py`, `tasks.py`, `interface.py` (функции встреч удалены, добавлена `tasks_for_timeline`), `management/commands/etl_task.py`;
  - `backend/htqweb/settings/base.py` (`INSTALLED_APPS`, `TENANT_APPS`), `apps/core/models.py` (`KNOWN_SERVICES`), `apps/core/services.py` (`CORE_MODULES`), `htqweb/middleware/service_gate.py` (`PREFIX_TO_SERVICE`), `apps/core/periodic_tasks.py` (`PERIODIC_TASKS` — путь задачи), `apps/companies/services/migration_service.py` (если нужно — `SHARED_EFFECT_MIGRATIONS`);
  - миграция `access` — узел `calendar.events` со строками ролей, скопированными с `tasks.calendar`;
  - `backend/apps/conference/services/{access,overview_service,session_service}.py`, `conference/tasks.py`, `cms/services/conference_invite_service.py` — `calendar.interface` вместо `tasks.interface` (ключи `fallback` не трогать);
  - тесты `conference/tests/*`, импортирующие `apps.tasks.models` календаря, — на `apps.calendar.models`;
  - `frontend/src/api/calendar.ts` (`calendar/v1/…`), `api/endpoints.ts`.

- [ ] **Step 1: Падающие тесты:**
  - перенос тестов `tasks/tests/test_calendar_api.py`, `test_calendar_conference_rooms.py`, `test_interface_conference.py` в `calendar/tests/` + проверка старых путей-алиасов;
  - `test_move_keeps_rows` — события, участники, исключения, созданные до миграции, после неё читаются через `calendar` с теми же `id`;
  - `test_no_ddl` — `sqlmigrate calendar 0001` и миграции `tasks` не содержат DDL по `tasks_calendar*`;
  - `test_reminder_task_names` — задачи напоминаний зарегистрированы под прежними именами; `test_periodic_tasks.py` зелёный;
  - `test_access_copies_calendar_node` — у каждой роли со строкой `tasks.calendar` есть такая же `calendar.events`.
- [ ] **Step 2: Реализация.** Прогон `apps/calendar`, `apps/tasks`, `apps/conference`, `apps/cms`, `apps/core` (сторожа изоляции, гейта, периодики, холдинга). Фронт: vitest, eslint, tsc.
- [ ] **Документация:** API.md (`calendar`), STRUCTURE.md (новая аппка), CLAUDE.md (список аппок, «Модель прав», `TENANT_APPS`), ранбук выкатки — `migrate_companies` переносит календарь только состоянием.
- [ ] **Коммит** — `feat(calendar): события календаря — отдельная аппка, API и таблицы прежние (A7.1, часть 2)`.

## Task 3: Блокировка входа и лимит запросов (A7.2)

**Files:**
- Create: `backend/htqweb/ratelimit.py` — `login_locked(login) -> int | None` (секунд до снятия), `register_login_failure(login)`, `reset_login(login)`, `hit_user(user_id) -> int | None`; атомарно (`cache.add` + `cache.incr`), ключи `htqweb:auth:fails:<h>`, `htqweb:auth:lock:<h>`, `htqweb:rl:u:<id>:<минута>`; недоступный кэш — `fallback("htqweb.ratelimit.store_unavailable", None, …)`; Counter-метрики `htqweb_auth_lockout_total`, `htqweb_rate_limited_total{kind}`; тесты `htqweb/tests/test_ratelimit.py`; команда `apps/users/management/commands/auth_unlock.py`.
- Modify:
  - `backend/apps/users/views.py::obtain_token` — проверка блокировки до `authenticate`, учёт неудачи, сброс на успехе, строка лога `auth_login_locked`; смена пароля администратором снимает блокировку;
  - `backend/htqweb/http.py::api_view` — `hit_user` после `request.token = payload`;
  - `backend/htqweb/settings/base.py` — `RATE_LIMIT_USER_PER_MIN`, `AUTH_LOCKOUT_THRESHOLD`, `AUTH_LOCKOUT_SECONDS`; три compose-файла и `.env.example`;
  - `infra/nginx/default.conf` — `limit_req_status 429;`;
  - `infra/logging/grafana-dashboards/*`, `alerting/rules.yml` — панель и правило (всплеск блокировок, всплеск 429); `apps/core/tests/test_metrics_are_observed.py::_DEFINED_OUTSIDE_APPS`;
  - фронт: `App.tsx` (`RETRYABLE_4XX` без 429), `components/LoginForm.jsx` (429 — текст блокировки с минутами из `Retry-After`), `api/client.ts` (тост на 429 `E-RATE-01`, кроме ручек входа), переводы.

- [ ] **Step 1: Падающие тесты:**
  - `test_auth_api.py`: 5 неудач → 6-я попытка 429 даже с верным паролем; неизвестный логин блокируется так же; `Admin`/`admin` — один счётчик; успех сбрасывает; `auth_unlock` снимает; refresh под блокировкой работает;
  - `test_ratelimit.py`: 301-й запрос → 429 с `Retry-After`; новая минута — 200; `RATE_LIMIT_USER_PER_MIN=0` — без лимита; недоступный кэш — без лимита и `FALLBACK` (Review Focus 3, 4);
  - SSE и `/metrics` счётчик не трогают.
- [ ] **Step 2: Реализация.** `./scripts/check-monitoring-config.sh`. Фронт: vitest, eslint, tsc.
- [ ] **Документация:** API.md (429 `E-AUTH-LOCKED`, `E-RATE-01`, исправить строку про 429 nginx), CLAUDE.md (абзац о лимитах), мастер-план §7 — §27 ТЗ (100 → 300) уже записан.
- [ ] **Коммит** — `feat(users,htqweb): блокировка входа после 5 неудач и лимит 300 запросов в минуту (A7.2, D-37)`.

## Task 4: Заготовки 1С (A7.3)

**Files:**
- Create:
  - `backend/htqweb/integrations/onec.py` — клиент OData (`httpx.Client`, Basic-аутентификация, `$filter`/`$top`/`$skip`, таймаут, разбор `odata.error`), `OneCUnavailable`, `OneCDisabled` (пустой `ONEC_ODATA_URL`);
  - `backend/apps/bpp/services/counterparties/onec.py::upsert_counterparty(record) -> Outcome` и `backend/apps/project/services/onec.py::upsert_project(record) -> Outcome` (`created | updated | unchanged | conflict | rejected` + причина);
  - миграции: частичный `UniqueConstraint` на `ext_1c_ref` у `bpp.Counterparty`, `project.Project` (тенантные, expand) и `refdata.Article` (`public`); перед ограничением — проверка дублей непустых значений (стоп с перечнем);
  - команда `manage.py onec_check [--company <slug>]` — конфигурация и связь (как `mail_check`): адрес, вход, чтение одной записи справочников; ничего не пишет;
  - тесты на `httpx.MockTransport`.
- Modify:
  - `backend/apps/project/schemas.py`, `services/projects.py::brief`, `views.py` — `ext_1c_ref` в API «Проекта»; фронт карточки «Проекта» — «Код в 1С» (как у контрагента);
  - `backend/apps/bpp/interface.py`, `backend/apps/project/interface.py` — `upsert_*_from_1c` для будущего слоя синхронизации;
  - `backend/htqweb/settings/base.py` — `ONEC_ODATA_URL`, `ONEC_USER`, `ONEC_PASSWORD`, `ONEC_TIMEOUT`; три compose и `.env.example`.

- [ ] **Step 1: Падающие тесты** (Review Focus 5): повтор upsert — `unchanged`, версия контрагента не растёт; найден по рег. номеру с другим GUID — `conflict`, данные не тронуты; невалидный БИН — `rejected`; «Проект» по коду; дубль непустого `ext_1c_ref` — `IntegrityError` ограничения; клиент — постраничное чтение, `odata.error`, таймаут → `OneCUnavailable`; пустой URL → `OneCDisabled`.
- [ ] **Step 2: Реализация.**
- [ ] **Документация:** STRUCTURE.md (слой интеграции), CLAUDE.md (абзац «1С — заготовка, без синхронизации»), API.md («Проект» — `ext_1c_ref`).
- [ ] **Коммит** — `feat(bpp,project): заготовки 1С — клиент OData и идемпотентный upsert контрагентов и «Проектов» (A7.3, D-38)`.

## Task 5: ClamAV — эксплуатация (A7.4)

**Files:**
- Modify:
  - три compose-файла: `ANTIVIRUS_CLAMD_PORT`, `ANTIVIRUS_TIMEOUT` в `x-django-env` (сейчас описаны в `.env.example`, но до backend не доходят); у `clamav` — `healthcheck` (`clamdcheck.sh` образа), `mem_limit`, `FRESHCLAM_CONF_DatabaseMirror` из `.env` (пусто — по умолчанию); `ANTIVIRUS_TIMEOUT` по умолчанию 30 — меньше `gunicorn --timeout 60`;
  - `backend/apps/media_files/services/upload_service.py::_scan` — Counter `htqweb_antivirus_scans_total{verdict="clean|infected|unavailable"}`; панель и правило «сканер недоступен» (`unavailable` растёт); `_DEFINED_OUTSIDE_APPS`;
  - `apps/core/infrastructure.py` — `clamd` в проверке инфраструктуры, если хост задан (PING);
  - `scripts/check-monitoring-config.sh` — второй `config` с `--profile antivirus`.
- Create:
  - `docs/deploy/antivirus-runbook.md` — включение (`.env`, `--profile antivirus`), первый старт (базы качаются минуты — 503 на загрузку документов), зеркало при 403 от `database.clamav.net`, память, проверка EICAR (ожидается 422 `E-FIL-08`), откат (пустой хост);
  - `backend/apps/core/tests/test_antivirus_live.py` — EICAR против настоящего `clamd`, `skipif` без `ANTIVIRUS_E2E_HOST`.

- [ ] **Step 1:** тест метрики вердикта на поддельном сканере; живой тест — прогнать локально с `--profile antivirus`.
- [ ] **Step 2:** `./scripts/check-monitoring-config.sh`; `docker compose -f docker-compose.test-local.yml --profile antivirus up -d clamav` — healthcheck зелёный после загрузки баз, EICAR через панель файлов → 422.
- [ ] **Документация:** CLAUDE.md (абзац «Антивирус» — ссылка на ранбук), STRUCTURE.md.
- [ ] **Коммит** — `feat(infra): ClamAV — проверка здоровья, метрика вердиктов, ранбук включения (A7.4, D-31)`.

## Task 6: Хвосты этапа 6

- [ ] **Привлечение партнёра → договор модуля (M-5 итогового ревью этапа 6).** Сейчас `tasks/services/contractor_service.py:379` связывает привлечение только с договором «Договоров» (`contracts.get_agreements_brief`), а у замороженной компании новые договоры живут в `bpp`. Нужно:
  - поле `bpp_agreement_id` (строка UUID, expand) у привлечения, выбор договора модуля того же контрагента (`bpp.interface.agreement_brief/search_agreements` — новые, зона A — интерфейс), номер `ДГ-…` в `contract_no`;
  - старая связь с договором «Договоров» читается для истории;
  - тесты; фронт экрана партнёра.
  Коммит — `feat(tasks,bpp): привлечение партнёра связывается с договором модуля (M-5)`; правка в `tasks` (зона B, если сервис привлечений — B) — отдельным коммитом.
- [ ] **Имена в карточке «Проекта» (сверка B §26).** `features/bpp/projects/useUserNames.ts` берёт ФИО из `hr/v1/employees` — у ТД, ОД, ПМ без кадровых прав 403 и «Пользователь №13». Брать из учёток (`users`), как реестры модуля.
- [ ] **`seed_purchase_request_template`** вне контекста компании падает (`signoff_approvalroute.scope`): команда — `--company <slug>` (обязателен при заведённых компаниях) либо явная ошибка; CLAUDE.md — убрать «безопасна на проде» или уточнить.
- [ ] **Мелочи из журнала этапа 6:** докстринг `contracts/counterparty_service.py` про «модуль задач»; `contracts_freeze --revoke-pending` молча морозит документ «на согласовании» без процесса — печатать его в отчёте; переводы `contracts.frozen.*` — в `ru`/`en` (сейчас только умолчания `t()`).
- [ ] **Коммиты** — по пункту.

## Task 7: Прогон, ревью, PR

- [ ] **Полный бэкенд** на 3.14 по аппкам (`nohup`-скрипт); фронт — полный vitest, tsc, eslint; `check-monitoring-config.sh`.
- [ ] **Стенд:** `migrate_companies` на `test-local` с существующими событиями календаря — события на месте, напоминания приходят; e2e `tests/e2e/3*_bpp_*` зелёные (`--project=chromium`).
- [ ] **Ранбук выкатки:** шаги этапа 7 — календарь (миграции идут в общем `migrate_shared`/`migrate_companies`), переменные `RATE_LIMIT_*`, `AUTH_LOCKOUT_*`, `ONEC_*`, антивирус — по своему ранбуку.
- [ ] **Итоговое ревью** ветки; Critical и Important исправить.
- [ ] **PR** в `new-module-BPP-merge` (мерж — по команде пользователя).

---

## Вопросы

| # | Кому | Вопрос | По умолчанию |
|---|---|---|---|
| Q-S7-1 | Алгазы | Учитывать праздники РК в рабочих днях модуля («банк не подтвердил > 3 раб. дней», закрывающие «> 5 дней»)? С задачи 1 производственный календарь доступен через `refdata.interface` | Нет — Пн–Пт, как D-S4-5 |
| Q-S7-2 | Алгазы / админ 1С | Адрес публикации OData, учётная запись, имена справочников контрагентов и проектов, какие реквизиты в них | Отображение — предположение (D-S7-5) |
| Q-S7-3 | Пользователь | Включать ClamAV на бою в окне выкатки модуля или отдельно? | Отдельно, по ранбуку (D-S7-6) |
| Q-S7-4 | Пользователь | 300 запросов/мин включать сразу или после замера профиля запросов по логам | После замера; до него `RATE_LIMIT_USER_PER_MIN=0` |
| Q-S7-5 | Алгазы | Производственный календарь правит управляющая компания (узел `refdata.production_calendar`), а не любой сотрудник с правом на задачи — согласны? | Да (D-S7-1) |

## Довести до Алгазы и Руслана

- **Руслан:** события календаря уходят из `tasks` в аппку `calendar` (D-S7-2) — в `tasks` остаются только доски и задачи; функции встреч в `tasks.interface` больше нет. Срок задачи по рабочим дням считается через `refdata.interface` (D-S7-1). Привлечение партнёра (сервис `tasks`) получает связь с договором модуля (задача 6).
- **Алгазы:** вопросы Q-S7-1, Q-S7-2, Q-S7-5; блокировка входа и лимит запросов меняют §27 ТЗ (300 вместо 100 — уже в «Изменениях к ТЗ»).

## Связь с этапом 8

С решением D-S6-9 модуль получают все компании одним окном, поэтому этап 8 (кросс-компанейское согласование B8.1, директора в дочерних компаниях и сводка группы A8.1) становится нужен раньше, чем планировалось «после пилота». На этапе 8 же — contract-шаги этапов 6–7: удаление `tasks.Contractor.counterparty_id`, `tasks.ProductionDay`, узла `tasks.calendar`, алиасов `tasks/v1/calendar*` и `production-calendar*`, `tasks.Notification`.
