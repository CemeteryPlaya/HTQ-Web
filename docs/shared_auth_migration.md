# Shared Auth Migration — Handoff

Дата: 2026-05-05. Ветка: `Rus`. Репо: `D:\HTQWeb-main`.

## Цель

Вынести JWT/RBAC из 7 копий в один пакет `libs/htqweb_auth/`, чтобы добавление нового отдела (IT, Финансы, Продажи, Логистика, …) сводилось к данным, а не к копипасте `hr_access.py`. Это фундамент под последующие этапы (messenger/email/cms enforcement, расширение test seed).

## Контекст

- HR + Task — полный department-scoped RBAC.
- Messenger — `department_path` ltree в моделях (без enforcement).
- Email / CMS / Media — без department-scope.
- TokenPayload скопирован в 7 сервисах, расходится по полям.
- Подробности предыдущих итераций — `employee_hr_rbac_handoff.md` (если у текущей сессии есть).

## Согласованный дизайн

### Структура пакета

```
libs/htqweb_auth/
├── __init__.py        ✅
├── config.py          ✅  AuthSettings (fail-fast JWT_SECRET)
├── payload.py         ✅  TokenPayload + is_elevated
├── dependencies.py    ✅  security, get_current_user, get_optional_user
├── rbac.py            ✅  require_admin
└── levels.py          ✅  DepartmentLevel + require_level(minimum, resolver)
```

### TokenPayload (union)

`user_id:int`, `exp:int`, `token_type:str="access"`, `username:str|None`, `email:str|None`, `is_staff/is_superuser/is_admin:bool=False`, `iat:int|None`, `iss:str|None`, `model_config = {"extra": "ignore"}`. Property `is_elevated = is_admin or is_staff or is_superuser`.

### DepartmentLevel

Generic enum: `JUNIOR`, `MIDDLE`, `SENIOR`, `LEAD`. Привязка к отделу — через `department_id` отдельно. Никаких `co_hr` / `co_finance` как разных строк.

`require_level(minimum, resolver)` — фабрика FastAPI-зависимости. `resolver: Callable[[TokenPayload], DepartmentLevel]` — реализуется per-service (например `app/auth/hr_access.py` → `resolve_hr_level`). Глобальные admin/staff/superuser (`is_elevated`) всегда проходят, не упираясь в department-проверку.

### Конфигурация JWT

`AuthSettings` читает только process env (`JWT_SECRET`, `JWT_ALGORITHM`, `JWT_ISSUER`). `.env` не читается. Fail-fast: `JWT_SECRET` без default — `pydantic.ValidationError` на импорте.

### Build / runtime

- `docker-compose.yml`: для 6 мигрируемых сервисов `build.context: .`, `dockerfile: services/<name>/Dockerfile`.
- Dockerfile: `COPY services/<name>/requirements.txt /app/`, `RUN pip install -r requirements.txt`, `COPY services/<name>/ /app/`, `COPY libs/htqweb_auth /app/libs/htqweb_auth`.
- `PYTHONPATH=/app:/app/libs` в env.
- Импорт в сервисе: `from htqweb_auth import ...` (без `libs.` префикса).

### Migration scope

**Мигрируем 6 сервисов:** `user`, `hr`, `task`, `messenger`, `email`, `cms`.

**`media` НЕ мигрируем** — у него S2S-JWT через отдельный `service_jwt_secret` + `X-User-Id` header. Оставляем как есть.

## Прогресс

### Сделано

- [x] Аудит `auth/dependencies.py` во всех 7 сервисах.
- [x] Аудит Dockerfiles 6 целевых сервисов.
- [x] Дизайн канонического TokenPayload + DepartmentLevel + plan согласован с пользователем.
- [x] `libs/htqweb_auth/config.py` — `AuthSettings` (fail-fast `jwt_secret = Field(..., min_length=1)`), `auth_settings`, `get_auth_settings`.
- [x] `libs/htqweb_auth/payload.py` — `TokenPayload` + `is_elevated`.
- [x] `libs/htqweb_auth/dependencies.py` — `security` (`HTTPBearer(auto_error=False)`), `_decode`, `get_optional_user`, `get_current_user`. Использует `auth_settings.*` через `jwt.decode`.
- [x] `libs/htqweb_auth/rbac.py` — `require_admin` через `is_elevated`.
- [x] `libs/htqweb_auth/levels.py` — `DepartmentLevel` enum + `rank` property + `meets()` + `require_level(minimum, resolver)`.
- [x] `libs/htqweb_auth/__init__.py` — публичный API.
- [x] `services/email/tests/conftest.py` — env-seed (`JWT_SECRET`/`JWT_ALGORITHM`/`JWT_ISSUER`) до любого `from app.*`. `make_admin_token`/`make_user_token` подписывают `TEST_JWT_SECRET`.
- [x] `.dockerignore` (root) — добавлены `frontend/`, `sfu/`, `webtransport/`, `node_modules/`, `services/adminjs/`, `services/_template/`, кэши и dist.

### Осталось

#### Pilot — email

- [x] **`docker-compose.yml`** секции `email-service` / `email-worker` / `email-scheduler`:
  - заменить `build: ./services/email` (или текущий) на:
    ```yaml
    build:
      context: .
      dockerfile: services/email/Dockerfile
    ```
  - добавить в `environment:` строку `PYTHONPATH: /app:/app/libs`
- [x] **`services/email/Dockerfile`** — текущий [services/email/Dockerfile](services/email/Dockerfile) однофайловый, контекст был `./services/email`. После переноса контекста в корень (см. выше):
  - `COPY services/email/requirements.txt .` (вместо `COPY requirements.txt .`)
  - `COPY services/email/ /app/` (вместо `COPY . .`)
  - добавить `COPY libs/htqweb_auth /app/libs/htqweb_auth`
  - `COPY services/email/entrypoint.sh /app/entrypoint.sh`
  - В runtime stage оставить `WORKDIR /app` без изменений
- [x] **`services/email/app/auth/dependencies.py`** — заменить тело файла на тонкий re-export, чтобы routers, импортирующие `from app.auth.dependencies import get_current_user`, продолжили работать без правок.
- [x] **Сборка и smoke**:
  ```powershell
  docker compose build email-service
  ```

#### Propagate (после успеха пилота)

Тот же паттерн на:
- [x] `user`  — Dockerfile одностадийный (`services/user/Dockerfile`), требует тех же замен COPY
- [x] `hr`    — двухстадийный (builder/runtime), внимание к `entrypoint.sh`
- [x] `task`  — одностадийный
- [x] `messenger` — двухстадийный
- [x] `cms`   — двухстадийный

Для каждого:
1. Обновить секцию(и) в `docker-compose.yml` (включая worker/scheduler).
2. Обновить `services/<name>/Dockerfile` под root-context.
3. Заменить `services/<name>/app/auth/dependencies.py` на re-export шим.
4. У сервисов, чьи existing TokenPayload имели *особые* поля (`role` в HR/Task) — оставить шим, который импортирует canonical TokenPayload и расширяет его при необходимости. Лучше: не расширять, а переписать call-sites. Но это уже Stage 2.
5. Прогнать тесты: `docker compose run --rm --no-deps -e ... <name>-service pytest -q`.
6. Для каждого сервиса повторить env-seed в `tests/conftest.py` по образцу email — fail-fast будет ломать pytest collection.

#### Stage 2+ (вне scope текущей миграции)

- Реализовать `services/<name>/app/auth/<name>_access.py` где нужны levels (messenger / email / cms enforcement). Использовать `from htqweb_auth import DepartmentLevel, require_level`.
- Обновить `services/hr/app/auth/hr_access.py` — оставить как есть на этом этапе, либо отрефакторить `resolve_hr_level()` чтобы возвращать `DepartmentLevel` вместо строки.
- Расширить `scripts/generate_test_users.py` — пользователи всех уровней для всех 5 отделов (Руководство / HR / IT / PM / Финансы).

## Важные ограничения

- **Не трогать модули HR sidebar** (Сотрудники / Структура / Должности / Оргструктура / PMO) — другой разработчик. Файлы:
  - `services/hr/app/api/v1/{employees,departments,positions,org,pmo}.py`
  - `frontend/src/pages/hr/HR{Employees,Departments,Positions,OrgChart,PMO}.tsx`
- **Не откатывать unrelated dirty файлы** в worktree:
  - `.env`, `docker-compose.yml` (сейчас уже dirty — наша миграция расширит правки)
  - `services/hr/app/core/settings.py`
  - `services/hr/app/main.py`
  - `services/hr/app/schemas/employee.py`
  - `services/hr/requirements.txt`
  - untracked: `services/adminjs/`, `services/hr/app/api/v1/mongo_documents.py`, `services/hr/app/mongo.py`, `services/hr/app/schemas/mongo_document.py`, `docs/rbac_matrix_analysis.md`, `docs/test_accounts.md`, `scripts/generate_test_users.py`.
- **Никаких параллельных helper'ов / костылей** — сначала grep, потом создание. Явное правило пользователя.
- **`media` не мигрируем** на этом этапе.

## Существующий контекст для копирования логики

- `services/user/app/auth/dependencies.py` — базовый TokenPayload
- `services/hr/app/auth/dependencies.py:13` — расширенный TokenPayload + `role` синтез (back-compat — посмотреть, кто реально читает `role`, перед удалением)
- `services/task/app/auth/dependencies.py:29` — `is_elevated` property (унаследовано в shared)
- `services/messenger/app/auth/dependencies.py` — `auto_error=False` + `get_optional_user`
- `services/email/app/auth/dependencies.py` — то же что messenger (целевой пилот — самый простой)
- `services/cms/app/auth/dependencies.py` — минимальный TokenPayload + `get_optional_user`
- `services/media/app/auth/dependencies.py` — НЕ мигрируем (S2S JWT)
- `services/hr/app/auth/hr_access.py` — образец для будущих `*_access.py` (Stage 2)

## Память Claude

`~/.claude/projects/d--HTQWeb-main/memory/`:
- `feedback_no_duplicates.md` — правило «проверить перед созданием».
- `project_rbac_expansion.md` — обзор плана этапов 1–6.
- `MEMORY.md` — индекс.

## Точка возобновления для нового чата

1. Прочитать этот файл целиком.
2. Прочитать `libs/htqweb_auth/__init__.py` чтобы увидеть готовый публичный API.
3. Прочитать `services/email/Dockerfile` и секцию `email-service` в `docker-compose.yml` — это входная точка пилота.
4. Сделать правки пилота (secret три точки в «Pilot — email» выше).
5. Запустить smoke-команды.
6. После зелёного пилота — пропагировать на 5 оставшихся сервисов по списку в «Propagate».
