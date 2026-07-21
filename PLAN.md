# HTQWeb: FastAPI → Django — мастер-план на ДВУХ исполнителей (фазы 4–11)

> **Назначение.** План для **двух исполнителей (Поток A и Поток B), каждый ведёт разработку в
> своей сессии Claude Code**. Работа разделена по принципу **равной нагрузки** (§1). Жёсткое
> правило: **агент каждого потока делает ТОЛЬКО свои домены и не трогает чужие** — при
> кросс-доменной нужде он вызывает `interface`-заглушку соседа (§4.2), а не реализует чужой код.
> Оба потока читают этот файл целиком, чтобы **знать, что делает второй**, и не дублировать/не
> перехватывать его задачи.
>
> Родитель по содержанию фаз: [полный план перехода](./docs/superpowers/plans/2026-07-19-django-full-transition-plan.md).
> Наследуемые правила и решения — из фаз 0–3 и блока устранения R0–R6 (см. §3).

---

## 0. Где мы сейчас (факт на 2026-07-20)

Готово и принято ревью (**861 тест, 0 warnings**, ветка `main`):
- **Фаза 0** — фундамент: `api_view`, `htqweb.authn` (JWT), реестр отключаемости + `ServiceGateMiddleware`, конвенция `interface.py` + lint изоляции, Celery, `htqweb.storage`.
- **Фаза 1** — `cms` (пилот): 7 таблиц, полный CRUD, отключаемость, контрактный паритет.
- **Фаза 2** — `users`: идентичность, JWT-authority, профиль, регистрация, админ-управление, аудит.
- **Фаза 3** — `media_files`: загрузка/ScopePolicy/варианты, Range/302-отдача, авторизация scope.
- **Устранение R0–R6**: три **рефлексивных мета-теста** инвариантов (guard задач / миксин админки / свип из резолвера), единый admin-гейт `api_view(admin=True)`, аудит во всех аппках, hardening отдачи.

Осталось: **5 доменов (task, requests, hr, email, messenger)** + подготовка + данные + cutover, **≈79 таблиц**. Всё это разделено между двумя потоками ниже.

> **Поправка чисел (2026-07-21).** Изначальные счётчики таблиц в этом плане были завышены:
> метод подсчёта (`grep __tablename__`) захватывал бинарные `.pyc` («Binary file matches»).
> Реальные числа по `.py`: task **21**, requests **15**, hr **29**, email **7**, messenger **7**
> (было 50/27/64/7/9). Ниже по тексту цифры и баланс приведены к факту.

---

## 1. Разделение на два потока (ГЛАВНОЕ)

### 1.1. Кто что делает

| | **Поток A** | **Поток B** |
|---|---|---|
| **Роль** | Домены с интеграциями и оргданными; **производитель** интерфейсов | Инфраструктура параллелизма + движковые домены; **потребитель** интерфейсов + интегратор |
| **Домены** | `hr` (29) · `mail`/email (7) · `messenger` (7) | **prep 4.0** · `task` (21) · `approvals`/requests (15) |
| **Таблиц** | **43** | **36** |
| **Вес сложности** | hr 8 + mail 3 + messenger 4 = **15** | prep 2 (сделан) + task 7 + requests 7 = **14** |
| **Ветки** | `phase/6-hr`, `phase/7-mail`, `phase/8-messenger` | `prep/parallel-scaffold`, `phase/4-task`, `phase/5-approvals` |
| **ASGI-поверхность** | Socket.IO `/ws/messenger/` (messenger) | SSE `/api/requests/v1/stream` (requests) |
| **Производит interface** | `apps.hr.interface`, `apps.mail.interface`, `apps.messenger.interface` | `apps.tasks.interface` (по необходимости), `apps.approvals.interface` (нет) |
| **Потребляет interface** | `apps.users.interface` (готов) | `apps.users` (готов) + **`apps.hr`, `apps.messenger` (Поток A)** через заглушки |
| **ETL (фаза 10)** | hr, mail, messenger | task, requests |
| **Особая роль в хвосте** | лид декоммиссии кода `services/` (фаза 11) | **лид prep + лид интеграции/мерджа** (§8) |

### 1.2. Почему нагрузка равная

- **По таблицам: 43 vs 36** — Поток A чуть тяжелее; компенсируется тем, что prep (общий фундамент) уже выполнен на ветке Потока A, а Поток B ведёт интеграцию (§8). Переспличивать домены не нужно.
- **По сложности: ≈15 vs ≈14** — примерно поровну. `hr` — по-прежнему самый сложный домен (Mongo→JSONB, 18 роутеров, оргдерево по строковому пути), хотя и не «монстр»: 29 таблиц, вес 8. Поток A = hr 8 + mail (OAuth) 3 + messenger (Socket.IO) 4 = 15. Поток B = task (FSM/sequences) 7 + requests (workflow-движок+SSE) 7 = 14; prep (вес 2) уже сделан.
- **Симметрия навыков**: у каждого потока по одной async/ASGI-поверхности (A — Socket.IO, B — SSE), по одному «монстру» логики (A — hr, B — task/requests), по интеграционному узлу (A — OAuth/IMAP в mail, B — движок согласований).
- **Кросс-поток однонаправлен**: Поток A — чистый **производитель** интерфейсов (зависит только от готового `users`). Поток B — **потребитель** A. Это исключает взаимную блокировку: A может целиком уйти вперёд, B работает против заглушек A (§4.2) и подхватывает живые реализации только на интеграции.

### 1.3. Мандат Потока A (читает агент A как свой устав)

> Ты — **агент Потока A**. Твоя рабочая зона — **ТОЛЬКО**:
> `backend/apps/hr/**`, `backend/apps/mail/**`, `backend/apps/messenger/**`
> (+ `backend/requirements.txt` для своих зависимостей — append-only).
>
> **ЧЕГО НЕ КАСАТЬСЯ (зона Потока B):** `backend/apps/tasks/**`, `backend/apps/approvals/**`,
> файлы подготовки (`htqweb/urls.py`, `INSTALLED_APPS`, `service_gate.py`,
> `apps/core/tests/test_invariants.py`, `htqweb/asgi.py`-каркас) — их делает Поток B в prep 4.0.
> Ты стартуешь **после** мерджа `PARALLEL_BASE`.
>
> **Если задача выглядит так, будто нужно тронуть `apps.tasks`/`apps.approvals`** — это сигнал,
> что нужно **вызвать заглушку** `apps.tasks.interface` (её нет — значит, тебе она не нужна) — а
> не реализовывать чужой домен. Свои интерфейсы (`hr`, `mail`, `messenger`) ты **производишь**
> для B; их сигнатуры зафиксированы в §7 — менять в одностороннем порядке нельзя.
>
> **Что делает Поток B (для осведомлённости, НЕ для исполнения):** сначала prep 4.0 (скаффолд
> всех 5 аппок, автодискавери URL, заглушки интерфейсов — включая твои каркасы), затем `task` и
> `requests`. `requests` **потребляет твои** `hr.org_ancestors`/`hr.get_department_brief` и
> `messenger.dispatch_notification` — держи эти сигнатуры стабильными; `task` потребляет твой
> `hr.get_department_brief`. Если B попросит доработать твой интерфейс — это твоя задача, не его.

### 1.4. Мандат Потока B (читает агент B как свой устав)

> Ты — **агент Потока B**. Твоя рабочая зона — **ТОЛЬКО**:
> подготовительные общие файлы в prep 4.0 (перечислены в §5), затем
> `backend/apps/tasks/**`, `backend/apps/approvals/**` (+ `backend/requirements.txt` — append-only,
> + `htqweb/asgi.py` секция SSE — только своя размеченная секция).
>
> **ЧЕГО НЕ КАСАТЬСЯ (зона Потока A):** `backend/apps/hr/**`, `backend/apps/mail/**`,
> `backend/apps/messenger/**`. Ты их **потребляешь**, но **не реализуешь**.
>
> **Если задача `task`/`requests` требует оргданных, отделов, диспатча уведомлений** — вызывай
> заглушку соседа: `apps.hr.interface.*`, `apps.messenger.interface.*` (созданы тобой же в prep
> как stub, наполняет их Поток A). **Не дописывай чужой интерфейс и чужую модель сам** — если
> stub-сигнатуры не хватает, зафиксируй потребность и согласуй с A (контракт §7); реализует A.
> Тестируй свой код против локального дубля (mock) интерфейса — §4.2.
>
> **Что делает Поток A (для осведомлённости, НЕ для исполнения):** `hr` (сотрудники/отделы/
> оргдерево/HR-документы), `mail` (почта/OAuth), `messenger` (чат/Socket.IO). A производит
> интерфейсы, которые ты зовёшь. Твоя дополнительная роль — **лид интеграции** (§8): ты сводишь
> ветки обоих потоков в `main` после того, как домены готовы.

### 1.5. Жёсткое правило границ (для обоих агентов)

1. **Один поток = свои `apps/*`.** Ни один агент не создаёт, не редактирует, не мигрирует и не удаляет код в аппках чужого потока. Нарушение ловится на ревью и при мердже (конфликт в чужом каталоге = откат).
2. **Кросс-домен только через `interface`.** Нужны чужие данные → зови `apps.<чужой>.interface.*` (заглушка из prep). Никаких прямых импортов чужих моделей, никаких межаппных FK (lint `test_app_isolation.py` это ловит).
3. **Чужой интерфейс не дописываешь.** Не хватает сигнатуры — согласуй (§7), пусть владелец допишет. Ты кодишь против согласованной сигнатуры и mock-дубля.
4. **Общие файлы после prep никто не трогает.** prep 4.0 (Поток B) снимает необходимость править `urls.py`/`INSTALLED_APPS`/`service_gate.py`/мета-тесты. Если после prep всплыла нужда их тронуть — это ошибка планирования, эскалируй, а не правь молча.
5. **`asgi.py` — по одной секции на поток.** B правит только SSE-секцию, A только Socket.IO-секцию; секции размечены якорями в prep.

---

## 2. Как читать этот план (для исполнителя любого потока)

1. Прочитай §1 (свой мандат + границы), §3 (глобальные правила — обязательны, выведены кровью фаз 1–3), §4 (протокол параллельной работы).
2. Найди свои домены в §6. Там: имя аппки, таблицы, роутеры, **какой `interface.py` ты ПРОИЗВОДИШЬ** и **какой ПОТРЕБЛЯЕШЬ**, особые узлы, DoD.
3. Работай **только внутри своих `apps/<домен>/**`** (+ `backend/requirements.txt`). Больше ничего — §1.5.
4. Внутри домена веди работу как в фазах 1–3: свежий субагент на задачу, ревью после каждой, TDD, полная сюита зелёная перед коммитом. Детальный TDD-план своего домена пишешь сам (навык writing-plans) по §6-спеке, сверяясь с FastAPI-исходником `services/<домен>/`.

---

## 3. Глобальные правила (ОБЯЗАТЕЛЬНЫ в обоих потоках)

Выведены из фаз 1–3 и ревью. Нарушение = переделка.

**Архитектура/схема**
- Репозиторий — **копия**, бок о бок с FastAPI не работает. Идиоматичный Django «с нуля»: схема **`public`**, стандартные имена таблиц Django, натуральный `makemigrations`, `managed=True`. Alembic-цепочки **не портируем**. PG-enum → `TextChoices`. Без схемо-квалификации, без ручных RunSQL-констрейнтов (кроме бизнес-триггеров).
- **Не терять индексы!** Сверять `index=True` в FastAPI-моделях, восстанавливать `db_index=True`; FK Django индексирует сам — дубли не добавлять. (Фаза 1 молча потеряла 11 индексов — поймало только ревью.)
- **`db_default=`** на серверных дефолтах (Now(), "", False, …). `default_auto_field = AutoField` в `apps.py`.
- Каждая аппка — интроспекционный тест схемы + проверка сборки на пустой БД.

**API/контракты**
- API-слой — только `htqweb.http.api_view(methods, auth, body, admin, status)`. Конверт ошибок всегда `{"detail": ...}`. Никакого DRF/ninja.
- **Admin-роуты — только `api_view(admin=True)`** (единый гейт, зовёт `rbac.require_admin`). Не писать приватных `_require_admin`.
- Контракт эндпойнтов — байт-в-байт по FastAPI-исходнику: пути, коды, имена полей. `APPEND_SLASH=False` — **аудит реальных вызовов фронта** (`grep frontend/src`) перед регистрацией роутов; регистрировать каждое написание (слеши дважды ловили 404).
- Контрактные фикстуры формы ответов — из Pydantic-схем FastAPI-исходника (провенанс в `"source"`-ключе).

**Отключаемость (машинно проверяется мета-тестами R0)**
- Каждая аппка в `KNOWN_SERVICES` (уже засеяны все). Свип: выключенная аппка → 503-конверт на **всех** роутах (включая публичные), соседи живы.
- Каждая Celery-задача — `@shared_task`, **первая строка `require_service("<svc>")`**. Периодика — `django_celery_beat.PeriodicTask` через data-миграцию в СВОЕЙ аппке.
- Каждая доменная `ModelAdmin` — под `ServiceGatedAdminMixin` (кроме `ServiceStatus`). Мета-тест `test_invariants.py` поймает пропуск автоматически.
- Межаппный доступ — **ТОЛЬКО** через `apps.<other>.interface` (lint `test_app_isolation.py`). Никаких FK между доменами, никаких прямых импортов чужих моделей.

**Решения Р1–Р5 (в силе)**
- Р1 без `PermissionsMixin`. Р2 без Redis pub/sub и таблиц-реплик — соседи через `interface.py`. Р3 без S2S — файлы через `htqweb.storage`/`media_files.interface.store_file`. Р4 `/api/core/v1/services/` публичен. Р5 админка отдаёт 503-native.

**Воркер/рантайм**
- Воркер — **Celery** (`@shared_task`, beat, results, flower), брокер Redis. Тесты — eager-режим (`CELERY_TASK_ALWAYS_EAGER`).
- **WSGI по умолчанию; ASGI точечно** только там, где реально нужен async: SSE (`/api/requests/v1/stream`, Поток B) и Socket.IO (`/ws/messenger/`, Поток A). Эти две поверхности монтируются в `htqweb/asgi.py`; всё остальное — WSGI.

**Тесты**
- Только Postgres, контейнер на host-порту 55432 (`docker compose -f docker-compose.yml -f docker-compose.test.yml up -d db`). ⚠️ Если тесты падают `ConnectionTimeout` на :55432 — контейнер остановлен, поднять его. Сюита зелёная и **0 warnings** после каждой задачи. `makemigrations --check --dry-run` чист.
- Библиотеки-кандидаты (из `requirementsNDPP.txt`): `django-filter`, `django-simple-history`, `django-json-widget` (взят), `django-recurrence` (task-календарь), `django-import-export`+`openpyxl`, `docxtpl` (HR-документы), `oauthlib` (email). DRF/allauth не берём.

---

## 4. Протокол параллельной работы (как НЕ столкнуться)

Архитектура специально построена под это: **аппки изолированы** (нет межаппных FK, нет прямых импортов, только `interface.py`), **мета-тесты рефлексивны** (не редактируются при добавлении аппки), а **реестр сервисов засеян заранее** (`PREFIX_TO_SERVICE` уже содержит `tasks/hr/requests/mail/messenger`).

### 4.1. Общие файлы и как их обезвредить (делает Поток B в prep 4.0)

Всего два файла, которые «наивно» правил бы каждый домен, — оба снимаются подготовкой (§5):
1. `htqweb/urls.py` — монтирование `include("apps.<x>.urls")`. → **Автодискавери**: `urls.py` перебирает установленные `apps.*`, у которых `AppConfig` объявляет `API_PREFIX`, и монтирует их сам. После prep домены `urls.py` **не трогают**.
2. `htqweb/settings/base.py` → `INSTALLED_APPS` — строка на аппку. → prep **скаффолдит все 5 доменных аппок сразу** и регистрирует их одной пачкой. После prep `INSTALLED_APPS` **не трогают**.

`htqweb/middleware/service_gate.py` — **править не нужно вообще**: `PREFIX_TO_SERVICE` уже содержит все префиксы, `APP_LABEL_TO_SERVICE` — все расхождения (`approvals`, `mail`).

Итог: после prep каждый поток трогает **только свои `apps/*`**. Единственный общий файл — `backend/requirements.txt` (append-only, конфликты тривиальны). Исключение: `htqweb/asgi.py` трогают оба потока — B (SSE) и A (Socket.IO); prep готовит его размеченным по секциям, интегратор при мердже сверяет.

### 4.2. Межпоточные зависимости через контракты интерфейсов

Поток B (task, requests) зовёт домены Потока A (hr, messenger) только через `interface.py`. Чтобы B не блокировался на A, **prep создаёт stub-интерфейсы для всех 5 аппок** с согласованными сигнатурами (§7). B кодит против сигнатуры и тестирует с локальным дублем (mock интерфейса); A наполняет свой `interface.py` в своих доменах; при мердже настоящая реализация замещает stub, и интеграционный тест проверяет живую связку. Сигнатуры менять в одностороннем порядке нельзя — только совместным согласованием (это контракт).

### 4.3. Ветки и последовательность

- **Шаг 0.** Поток B делает `prep/parallel-scaffold` (§5), Поток A ревьюит его. Мердж в `main` = **`PARALLEL_BASE`**. Пока идёт prep, Поток A **читает исходники** `services/hr|email|messenger` и пишет детальные TDD-планы своих доменов (read-only, без правок репозитория).
- **Шаг 1 (fan-out).** От `PARALLEL_BASE`: A ведёт `phase/6-hr` → `phase/7-mail` → `phase/8-messenger`; B ведёт `phase/4-task` → `phase/5-approvals`. Внутри своей ветки каждый — полный SDD-цикл (субагенты + ревью), частые коммиты.
- **Правило:** **не ребейзить чужие ветки, не мерджить между потоками** — только через интеграцию (§8). `PARALLEL_BASE` после prep **не меняется** (никто не правит общие файлы) — дрейфа нет.

### 4.4. Что делает параллелизм безопасным (сводка)

| Риск столкновения | Снят чем |
|---|---|
| `urls.py` | автодискавери по `API_PREFIX` (prep, Поток B) |
| `INSTALLED_APPS` | скаффолд всех аппок в prep (одна пачка) |
| `service_gate.py` | префиксы уже засеяны — правок нет |
| мета-тесты инвариантов | рефлексивны — правок нет; prep делает их толерантными к «аппка есть, моделей ещё нет» |
| межпоточные вызовы (B→A) | stub-контракты интерфейсов (prep + §7) |
| миграции разных аппок | у каждой аппки свой `migrations/`, доменных FK нет → Django не пересекает |
| `requirements.txt` | append-only; известные деп-ы добавлены в prep |
| `asgi.py` (SSE B + socketio A) | prep размечает секции якорями; интегратор сверяет |
| агент лезет в чужой домен | мандаты §1.3/§1.4 + жёсткое правило §1.5 + конфликт в чужом каталоге на мердже |

---

## 5. Prep 4.0 — Parallel Scaffold & Seams (**Поток B**, до fan-out)

**Ветка `prep/parallel-scaffold`; ревью — Поток A; мердж в `main` → `PARALLEL_BASE` до старта любого домена.**

- [ ] **URL-автодискавери.** В `htqweb/urls.py`: перебрать `django.apps.apps.get_app_configs()`, для каждого `apps.*` с атрибутом `API_PREFIX` и наличием модуля `urls` — `path(config.API_PREFIX, include(f"{config.name}.urls"))`. Существующие cms/users/media_files перевести на этот механизм (добавить `API_PREFIX` в их `AppConfig`, убрать хардкод-строки). Тест: cms/users/media эндпойнты по-прежнему резолвятся.
- [ ] **Скаффолд 5 доменных аппок**: `apps/tasks`, `apps/approvals`, `apps/hr`, `apps/mail`, `apps/messenger`. Каждая: `__init__.py`, `apps.py` (`AppConfig` c `name`, `API_PREFIX="api/<svc>/v1/"`, `default_auto_field="django.db.models.AutoField"`), пустой `models.py`, `urls.py` (`urlpatterns=[]`), `services/__init__.py`, `tasks.py` (пустой), `admin.py` (пустой), `interface.py` (stub-функции по §7, guard первой строкой, `raise NotImplementedError` или пустой результат + докстринг-контракт), `migrations/__init__.py`, `tests/__init__.py`. Имена service ↔ app_label: `tasks`→`tasks`, `approvals`→`approvals`, `hr`→`hr`, `mail`→`mail`, `messenger`→`messenger` (уже в реестрах).
- [ ] **Регистрация**: добавить все 5 в `INSTALLED_APPS` одной пачкой.
- [ ] **Мета-тест толерантен к пустым аппкам.** В `apps/core/tests/test_invariants.py`: аппка-нарушитель по админ-миксину — только та, у которой **есть ≥1 конкретная модель, но не зарегистрирована**. Пустая скаффолд-аппка (0 моделей) — пропускается. Так `_KNOWN_UNREGISTERED` не нужен и потоки не правят общий тест. (Аналогично: аппка без `tasks.py`-задач — пропускается guard-тестом; пустой `urls.py` — свип ничего не находит.)
- [ ] **`asgi.py` расширяемый.** Подготовить `htqweb/asgi.py` так, чтобы SSE (Поток B) и Socket.IO (Поток A) добавляли свои mount'ы в явно размеченные секции с комментами-якорями (чтобы мерджи двух потоков не пересекались построчно).
- [ ] **Известные зависимости** в `requirements.txt`: `celery`/`django-celery-*`/`flower` (есть), кандидаты `django-recurrence`, `oauthlib`/`requests-oauthlib`, `openpyxl`, `docxtpl`, `python-socketio` — добавить те, что точно нужны (recurrence, socketio, oauthlib); остальное потоки дотянут в своих доменах.
- [ ] **Verify**: полная сюита зелёная, мета-тесты зелёные (5 пустых аппок допустимы), `makemigrations --check` чист (у пустых аппок миграций нет), автодискавери монтирует cms/users/media как раньше, 5 новых аппок отвечают 404 на своих префиксах (роутов ещё нет) и **503 при выключении** (гейт работает по префиксу сразу).
- [ ] **Ревью (Поток A, opus)** — это общий фундамент обоих потоков; ошибка здесь стоит обоим. Затем мердж в `main` = `PARALLEL_BASE`.

**DoD prep:** все 5 доменных аппок установлены, изолированы, отключаемы, с автодискавери URL и stub-интерфейсами; ни один домен больше не обязан трогать общие файлы. Мета-тесты зелёные.

---

## 6. Доменные спеки (детальный TDD-план каждый поток пишет сам по исходнику)

Каждый работает **только** в своих `apps/<домен>/**`. Источник контракта — `services/<домен>/app/api/v1/*` и `.../models/*`, `.../schemas/*`, `.../services/*`. Общий DoD домена — в §6.6.

### 6.1. [Поток B] Фаза 4 — `task` (аппка `apps.tasks`, сервис `tasks`, 21 таблица)
- **Роутеры** (`services/task/app/api/v1/`): tasks, comments, attachments, activity, links, labels, calendar, sequences, notifications, projects, task_types, assignments, equipment, reports.
- **Особое:** FSM 7 статусов (`TRANSITIONS`), матрица прав `_can_edit_task`, **атомарные sequences** (`select_for_update()`), производственный календарь РК, календарь (+ `django-recurrence` — кандидат на recurrence/exceptions), `task_types` как таблица (не enum). Вложения — через `media_files.interface.store_file(scope="task_attachment", internal_authorized=…)`.
- **Р2:** `replica_sync` user/department **не портируем** — исполнители/супервайзеры/watchers резолвятся через `apps.users.interface`; проекты с `department_id` — через `apps.hr.interface` (**Поток A, кросс-поток → заглушка**).
- **Produces interface:** `apps.tasks.interface` — по необходимости `get_task_brief(id)` (вероятно не нужен). **Consumes:** `apps.users.interface` (готов), `apps.hr.interface` (Поток A, stub).
- **Периодика:** если у task-scheduler есть джобы — перенести в beat; мёртвые — `enabled=False`.

### 6.2. [Поток B] Фаза 5 — `requests` (аппка `apps.approvals`, сервис `approvals`, 15 таблиц)
- **Роутеры:** forms, instances, actions, projects, stats, stream (**SSE**), reference. (`example.py` — мусор: сверить и НЕ переносить.)
- **Особое:** workflow-движок (`workflow_engine`/`form_schema`/`condition_eval`/`assignee_resolver`/`dispatch`/`stats_rollup`) — **самая ценная логика, переносить с юнит-тестами 1:1** (141 тест ветки — регрессионная база). **SSE `/api/requests/v1/stream`** — ASGI-узел Потока B: `async` StreamingHttpResponse, токен в query (`EventSource` не шлёт заголовки) — как в оригинале; mount в **свою SSE-секцию** `htqweb/asgi.py`. nginx-локация без буферизации — деплой-этап.
- **Р2:** реплики user/department (`request_departments`/`user_replica`) — не портируем; обогащение оргданными через `apps.hr.interface`, диспатч уведомлений — через `apps.messenger.interface` (**обе — Поток A, кросс-поток → заглушки; best-effort деградация:** недоступность hr/messenger не роняет workflow).
- **Produces:** — (никто не зовёт). **Consumes:** `apps.users` (готов), `apps.hr`, `apps.messenger` (Поток A, stubs).

### 6.3. [Поток A] Фаза 6 — `hr` (аппка `apps.hr`, сервис `hr`, 29 таблиц — самый сложный домен)
- **Роутеры (18):** employees, departments, positions, vacancies, applications, time, documents, mongo_documents, org, pmo, audit, personnel_history, share_links, staffing, calendar, department_files, employee_card, internal.
- **Особое:** **Mongo → PostgreSQL JSONB** (HR-документы) — в исходнике **опционально** (при пустом `mongo_uri` сервис работает SQL-only, деградационный путь есть): две коллекции (`hr_documents`, `hr_employee_groups`) → JSONB-модели; сам ETL Mongo→JSONB — в фазе 10, здесь только модели+эндпойнты. **Оргдерево — НЕ `ltree`** (уточнено 2026-07-21 разведкой): `Department.path` — обычная строка (`String(500)` с индексом), предки = её префиксы; `django-tree-queries`/raw SQL **не нужны** (комментарий «ltree» в исходнике вводит в заблуждение — расширение не подключено). LibreTranslate (перевод оргдерева) — за настройкой, тесты без сети. Публичные share-links. Файлы отделов — через `media_files.interface`. Производственный календарь / табель.
- **Р2:** `user_identity_sync` **умирает** — сотрудники линкуются на `user_id`, данные пользователя через `apps.users.interface`.
- **Produces interface:** `apps.hr.interface` — `get_department_brief(id)`, `get_departments_brief(ids)`, `get_employee_brief(user_id)`, `org_ancestors(department_id)` (для task и assignee_resolver requests — **обе задачи Потока B; держи сигнатуры стабильными**). **Consumes:** `apps.users.interface` (готов).
- Кандидаты: `django-import-export`+`openpyxl` (штатка/T-2/выгрузки), `docxtpl` (генерация HR-документов — новая возможность, если в целях).

### 6.4. [Поток A] Фаза 7 — `email` (аппка `apps.mail`, сервис `mail`, 7 таблиц)
- **Роутеры:** accounts, emails, mailboxes, oauth, webhooks.
- **Особое:** OAuth Google/Microsoft (`oauthlib`), sync (`sync/gmail.py`/`microsoft.py`/`mailcow_imap.py`) и sender-стратегии переносятся почти как есть (httpx/imap, от фреймворка не зависят). IMAP IDLE → management command (`run_imap_idle`, отдельный процесс). Вебхуки Gmail Pub/Sub + Graph — **публичная локация без rate-limit**, контрактные тесты на записанных payload; живой прогон — деплой-этап. `pg_try_advisory_lock` сохранить (raw SQL). Dramatiq-актора (`deliver_email`, sync, `final_purge_archived_mailboxes` 03:15) → Celery + beat.
- **Р2/Р3:** каскад «user SUSPENDED → архивация ящика» — теперь `apps.mail.interface.archive_user_mailboxes(user_id)`, который зовёт `users` при деактивации (подписчик `user_events` на pub/sub умирает). **Consumes:** `apps.users.interface` (готов). **Produces:** `apps.mail.interface.archive_user_mailboxes(user_id)` — вызов в `users` добавляется на интеграции (§8).

### 6.5. [Поток A] Фаза 8 — `messenger` (аппка `apps.messenger`, сервис `messenger`, 7 таблиц)
- **Роутеры + socket:** messages, rooms, users, read, keys, attachments, admin, internal + `socket.py`.
- **Особое:** **Socket.IO** — `python-socketio AsyncServer(async_mode="asgi", client_manager=AsyncRedisManager)`, mount в **свою Socket.IO-секцию** `htqweb/asgi.py` (`socketio_path="ws/messenger/socket.io"`); фронтовый socket.io-client не трогаем. **Обработчик `connect` ПЕРВЫМ делом зовёт `require_service("messenger")`** и отклоняет коннект (закрывает риск Р10 — гейт middleware не покрывает WS-scope). Presence, E2EE-ключи (CRUD), недельный S3-архив (сб 04:30 GMT+5) → beat. Аттачменты — через `media_files.interface`. `bot_dispatch` → Celery. `replica_sync` user — Р2, через `apps.users.interface`.
- **Produces interface:** `apps.messenger.interface.dispatch_notification(user_ids, payload)` / `send_system_message(...)` (зовёт `requests` — **задача Потока B; держи сигнатуры стабильными**). **Consumes:** `apps.users.interface` (готов).
- ⚠️ Мессенджер по решению заказчика может пойти на связку **Redis + Celery** — Celery уже воркер платформы; сверить, не нужен ли отдельный брокер/паттерн, в детальном плане домена.

### 6.6. DoD домена (единый, для обоих потоков)
1. Все эндпойнты домена отвечают идентично FastAPI-оригиналу (пути/коды/поля; контрактные фикстуры).
2. Отключаемость: свип всех роутов → 503 при выключенной аппке; соседи живы; критический тест — валидный токен в чужой аппке при выключенном своём домене по-прежнему 200.
3. Все Celery-задачи с guard'ом; периодика в beat; мета-тесты R0 зелёные (guard/mixin/sweep автоматически покрывают новую аппку).
4. `interface.py` домена реализован (guard-первой-строкой, простые словари), lint изоляции зелёный; потребляемые интерфейсы соседей вызываются по согласованным сигнатурам (у Потока B — против заглушек A, до интеграции).
5. Модели `managed=True`, схема строится на пустой БД, индексы на месте, `makemigrations --check` чист, интроспекционный тест.
6. Django-админка домена под гейтом (регистрируется здесь же — так фаза 9 сведётся к декоммиссии панелей).
7. Сюита зелёная, **0 warnings**. Финальное ревью домена (opus) пройдено.

---

## 7. Контракты интерфейсов (согласованы; менять только совместно A↔B)

Stub'ы создаёт prep (Поток B); наполняет — производящий поток; вызывает — потребляющий. Все функции — `require_service("<owner>")` первой строкой, возвращают простые словари/списки словарей, не ORM-объекты.

| Интерфейс (владелец) | Поток-производитель | Сигнатуры | Кто потребляет |
|---|---|---|---|
| `apps.users.interface` (готов) | — | `get_user_brief(user_id)->dict|None`, `get_users_brief(ids)->list[dict]` | оба потока |
| `apps.hr.interface` | **A** | `get_department_brief(id)`, `get_departments_brief(ids)`, `get_employee_brief(user_id)`, `org_ancestors(department_id)->list[dict]` | **B**: task (projects.department), requests (assignee_resolver) |
| `apps.messenger.interface` | **A** | `dispatch_notification(user_ids, payload)->None`, `send_system_message(room_id, text)->None` | **B**: requests (dispatch) |
| `apps.mail.interface` | **A** | `archive_user_mailboxes(user_id)->None` | `users` (каскад деактивации) — **вызов добавляется в users на интеграции** |
| `apps.tasks.interface` | **B** | по необходимости `get_task_brief(id)` | (вероятно никто) |
| `apps.approvals.interface` | **B** | — | (никто) |

**Наблюдение:** все кросс-поточные стрелки идут **B → A** (B потребляет hr/messenger, произведённые A) плюс `mail → users`. Поток A ни от кого из потоков не зависит (только готовый `users`). Поэтому A может уйти вперёд, а B работает против заглушек.

Правила деградации потребителя: если `require_service` соседа кинул `ServiceDisabled` или сосед недоступен — **не падать**: обогащение опускается (list без оргданных), диспатч уведомлений best-effort (лог, workflow продолжается). Тест на деградацию — обязателен у потребителя (Поток B).

---

## 8. Мердж и интеграция (**Поток B — лид**, после доменных фаз)

### 8.1. Порядок мерджа
`PARALLEL_BASE` уже в `main`. Далее так, чтобы производители (A) легли до потребителей (B):
1. **hr, mail, messenger** (Поток A) — в любом порядке (потребляют только готовый `users`; производят интерфейсы для B).
2. **task** (Поток B) — после `hr` (потребляет `hr.get_department_brief`).
3. **requests** (Поток B) — **последним** (потребляет живые `hr` + `messenger`).
4. При мердже **mail**: добавить в `apps/users` вызов `apps.mail.interface.archive_user_mailboxes(user_id)` в каскад деактивации (единственная правка `users` при интеграции — согласована контрактом §7; делает интегратор = Поток B, по согласованию с A).

### 8.2. Что резолвит интегратор (Поток B) на каждом мердже
- **`requirements.txt`** — append-конфликты (тривиально: объединить строки).
- **`htqweb/asgi.py`** — при мердже requests (SSE, B) и messenger (socketio, A): обе секции должны оказаться в файле; якоря-комменты из prep делают это построчно-непересекающимся.
- Ничего больше общего быть не должно (см. §4). **Конфликт в `urls.py`/`INSTALLED_APPS`/`service_gate.py` или в чужом `apps/*` = поток нарушил границы §1.5, вернуть на доработку.**

### 8.3. Гейт на каждом мердже (обязателен, до следующего мерджа)
```
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d db
cd backend && .venv/Scripts/python -m pytest -q                       # ВСЯ сюита зелёная
cd backend && .venv/Scripts/python -m pytest apps/core/tests/test_invariants.py -q   # инварианты
cd backend && .venv/Scripts/python manage.py makemigrations --check --dry-run        # чисто
```
Рефлексивные мета-тесты R0 автоматически подтверждают, что **свежесмердженная аппка гейтится, её задачи с guard'ом, её админка под миксином, её роуты в свипе**. Плюс `test_app_isolation.py` (изоляция) и замена stub-интерфейса потребителя (B) на живой (A) + интеграционный тест связки (например, requests → hr.org_ancestors реально резолвит; requests → messenger.dispatch_notification доходит).

---

## 9. Фаза 10 — Данные (ETL из старой БД + Mongo→JSONB) — **раздельно по владельцу домена**

**После мерджа всех доменов** (нужны финальные Django-схемы). Каждый поток пишет ETL для **своих** доменов — он знает маппинг таблиц/колонок лучше всех:
- **Поток A:** ETL `hr` (+ **Mongo → JSONB** для HR-документов), `mail`, `messenger`.
- **Поток B:** ETL `task`, `requests`.

Общие правила ETL:
- Management command per домен: перелив из старой БД (старые схемы `cms`/`auth`/`public`+префиксы, старые имена таблиц/колонок) в новые Django-таблицы. Помодельный **маппинг** фиксируется каждым потоком СРАЗУ при переносе моделей (пока свежа память), в отчёте домена.
- Идемпотентный upsert; **сверка count + выборочные per-row hash** на каждый домен.
- HR-документы: Mongo→JSONB command (idempotent-upsert, сверка count+checksum), mongo read-only до фазы 11.
- Пароли/секреты не трансформировать (bcrypt/PBKDF2 уже совместимы в модели `User`).
- Verify: после ETL — count/hash-отчёт по каждому домену зелёный; выборочные live-запросы через ORM.

---

## 10. Фаза 11 — Cutover + декоммиссия (**совместно; B — инфра, A — снос кода**)

**Ветка `phase/11-cutover`, последней; оба потока сводят вместе.**

- **Трафик (Поток B):** `frontend/vite.config.ts` и `infra/nginx/default.conf` → один upstream `backend` (вместо девяти); SSE/socketio-локации — на ASGI-процесс.
- **Compose (Поток B):** `backend-web` (gunicorn WSGI) + `backend-asgi` (uvicorn: `/api/requests/v1/stream` + `/ws/messenger/`) + `backend-worker` (celery) + `backend-beat` + `flower`. Снести из compose: 9 сервисов, dramatiq, mongo(+exporter), adminjs, sqladmin/admin-service.
- **Снос кода (Поток A):** `services/user|hr|task|requests|cms|media|messenger|email|admin|adminjs|_template`, `scaffold.py`, `libs/htqweb_auth`, per-service alembic, S2S-механика, реестры реплик.
- **Наблюдаемость (Поток B):** Prometheus targets −9 сервисов +backend; Grafana-дашборды; `django-prometheus` (кандидат) вместо `htqweb_metrics`.
- **Доки (совместно):** переписать `API.md`, `STRUCTURE.md`, `services/README.md` → `backend/README.md`, `CLAUDE.md` (убрать умершие PgBouncer/schema-per-service гётчи; историю про search_path оставить как контекст).
- SFU/webtransport остаются (Node/aioquic, `conference` disabled), не мигрируют.

**Фаза 9 (Django-админка)** сводится сюда: если модели регистрировались в своих доменах (DoD §6.6 п.6), здесь — только декоммиссия старых панелей sqladmin/adminjs (в сносе кода/compose выше).

---

## 11. Финальная приёмка — готовность и корректность (совместно)

После фазы 11 — общий приёмочный прогон:

**Автоматическая корректность**
- [ ] Полная backend-сюита зелёная, **0 warnings**; счётчик тестов ≈ сумма доменных.
- [ ] Мета-тесты инвариантов зелёные: **все** аппки гейтятся, **все** задачи с guard'ом, свип покрывает все префиксы; `test_app_isolation.py` — ноль межаппных импортов мимо `interface`.
- [ ] `makemigrations --check` чист; **на ПУСТОЙ БД `migrate` строит полную схему**; индексы/дефолты/enum на месте.
- [ ] Контрактный паритет всех доменов (формы ответов из FastAPI-схем) зелёный.
- [ ] ETL-отчёт (фаза 10): count+hash по каждому домену сходится; Mongo→JSONB сверен.

**Фронтенд/e2e**
- [ ] `cd frontend && npx tsc --noEmit` чисто; `npm test` зелёный; `npm run test:e2e` (Playwright, канал `msedge`) против Django-бэкенда (vite-proxy → один upstream) — ключевые сценарии каждого домена.

**Безопасность/архитектура**
- [ ] Финальное whole-repo ревью (opus): auth/JWT, файловый доступ, admin-гейт, отключаемость сквозь все домены; отдельно — что осталось открытым (домен-сепарация подписи из R6, `_json_safe` в users/media из R3 — закрыть или осознанно оставить).
- [ ] Ручная проверка отключаемости: выключить каждый сервис по очереди (`manage.py service <svc> --off`) → его страницы отдают 503/попап, остальная платформа работает, токены не инвалидируются.

**Декоммиссия**
- [ ] `services/`, `libs/`, dramatiq, mongo, adminjs, sqladmin — удалены; `grep -r "fastapi\|dramatiq\|alembic\|sqlalchemy" backend services` пусто (в активном коде).
- [ ] Один backend-upstream в nginx/vite; WSGI+ASGI процессы поднимаются; flower/beat живы.
- [ ] Доки переписаны и соответствуют факту.

**Критерий готовности:** все чекбоксы §11 зелёные → переход с FastAPI на Django завершён.

---

## 12. Риски двухпоточной модели и меры

| # | Риск | Мера |
|---|------|------|
| 1 | Агент лезет в домен чужого потока | Мандаты §1.3/§1.4 (устав агента) + жёсткое правило §1.5; конфликт в чужом `apps/*` на мердже = откат |
| 2 | Поток трогает общий файл (`urls.py`/`INSTALLED_APPS`/`service_gate.py`) вопреки §4 | prep снимает необходимость; конфликт в этих файлах на интеграции = вернуть на доработку |
| 3 | Расхождение сигнатур интерфейсов A↔B | Контракты §7 зафиксированы в prep-заглушках; менять только совместно; интеграционный тест связки на мердже |
| 4 | Оба потока правят `asgi.py` (B — SSE, A — socketio) | prep размечает секции якорями; интегратор (B) сверяет обе |
| 5 | Неравная нагрузка по факту (hr тяжелее оценки) | Контрольная точка после первого домена каждого потока: если A на hr отстаёт — B, закончив task/requests, берёт `mail` или `messenger` у A (они изолированы, передаются по границе аппки без конфликтов) |
| 6 | B заблокирован ожиданием A | Заглушки §4.2: B кодит и тестирует против mock; живые интерфейсы A подключаются только на интеграции |
| 7 | ETL стартовал до финализации схем | Жёсткая последовательность: фаза 10 только после мерджа ВСЕХ доменов; маппинги собираются по ходу |
| 8 | Данные/cutover необратимы | Фазы 10–11 не трогают боевую БД до отдельного go; ETL — на копии, сверка count/hash; всё через management-команды с dry-run |

---

## 13. Резюме для координации

1. **Поток B делает prep 4.0** (`prep/parallel-scaffold`), **Поток A ревьюит**, мердж → `PARALLEL_BASE`. Пока идёт prep — A пишет детальные планы своих доменов (read-only). Без prep параллелить нельзя.
2. **Fan-out от `PARALLEL_BASE`:**
   - **Поток A:** `phase/6-hr` → `phase/7-mail` → `phase/8-messenger`. Только `apps/hr|mail|messenger`. Производит интерфейсы для B.
   - **Поток B:** `phase/4-task` → `phase/5-approvals`. Только `apps/tasks|approvals`. Потребляет заглушки A.
   - Каждый — свой SDD-цикл (субагенты + ревью), детальный план по §6-спеке. **Границы §1.5 соблюдать строго.**
3. **Интеграция (Поток B — лид, §8):** мердж hr/mail/messenger (A), затем task, затем requests (B); гейт R0 на каждом мердже; добавить вызов `mail.interface` в `users`.
4. **Фаза 10 (данные):** A — ETL hr/mail/messenger (+Mongo→JSONB), B — ETL task/requests. После всех мерджей.
5. **Фаза 11 (cutover):** совместно — B инфра/compose/трафик, A снос кода `services/`+`libs/`.
6. **§11 приёмка** — критерий готовности всего перехода.
