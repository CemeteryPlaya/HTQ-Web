# RBAC Matrix Analysis — HTQWeb Platform

**Дата анализа:** 2026-05-05  
**Версия:** 1.0  
**Автор:** Automated Architecture Audit

---

## 1. Обзор архитектуры

HTQWeb — внутренняя enterprise-платформа, построенная на **микросервисной архитектуре**:

| Компонент | Технология | Назначение |
|---|---|---|
| **Frontend** | React 18 + Vite + TypeScript | SPA, shadcn/ui |
| **Backend** | FastAPI + SQLAlchemy 2.0 async | Микросервисы |
| **СУБД** | PostgreSQL 16 (через PgBouncer) | Транзакционные данные |
| **Кэш** | Redis 7 | Кэш + channel layer |
| **Auth** | JWT (HS256, iss=htqweb-auth) | Единый user-service — JWT authority |
| **Admin** | sqladmin | Агрегатор всех сервисов |
| **Workers** | Dramatiq + Redis | Фоновые задачи |

### 1.1 Сервисы и их схемы БД

| Сервис | Порт | PG Schema | Описание |
|---|---|---|---|
| `user-service` | 8005 | `auth` | Identity, JWT, регистрация, профиль, администрирование |
| `hr-service` | 8006 | `public` (hr_*) | Сотрудники, отделы, должности, документы, PMO |
| `task-service` | 8007 | `tasks` | Задачи, проекты, календарь |
| `messenger-service` | 8008 | `messenger` | Чат, WebSocket |
| `media-service` | 8009 | `media` | Файловое хранилище |
| `email-service` | 8010 | `email` | Внутренняя почта |
| `cms-service` | 8011 | `cms` | Новости, контакты, конференция |
| `admin-service` | 8012 | multi-schema | Агрегатор sqladmin |

---

## 2. SQL-модели (Entity Relationship)

### 2.1 User Service (schema: `auth`)

```
┌──────────────────────────────┐
│           users              │
├──────────────────────────────┤
│ id          : INTEGER PK     │
│ username    : VARCHAR(150) UQ│
│ email       : VARCHAR(254) UQ│
│ password_hash: VARCHAR(256)  │
│ first_name  : VARCHAR(150)   │
│ last_name   : VARCHAR(150)   │
│ patronymic  : VARCHAR(100)   │
│ display_name: VARCHAR(100)   │
│ bio         : TEXT           │
│ phone       : VARCHAR(30)    │
│ avatar_url  : VARCHAR(500)   │
│ settings    : JSON           │
│ status      : ENUM           │  ← pending|active|suspended|rejected
│ is_staff    : BOOLEAN        │  ← Флаг admin-уровня
│ is_superuser: BOOLEAN        │  ← Суперпользователь
│ must_change_password: BOOLEAN│
│ date_joined : TIMESTAMPTZ    │
│ last_login  : TIMESTAMPTZ    │
│ created_at  : TIMESTAMPTZ    │
│ updated_at  : TIMESTAMPTZ    │
└──────────────────────────────┘
```

**UserStatus (enum):**
- `pending` — ожидает одобрения (is_active=False)
- `active` — может авторизоваться
- `suspended` — заблокирован администратором
- `rejected` — регистрация отклонена

### 2.2 HR Service (schema: `public`, prefix `hr_`)

```
┌──────────────────────────┐       ┌─────────────────────────┐
│    hr_departments        │       │     hr_positions        │
├──────────────────────────┤       ├─────────────────────────┤
│ id          : INT PK     │◄──────│ department_id : INT FK  │
│ name        : VARCHAR UQ │       │ id           : INT PK   │
│ path        : VARCHAR UQ │ ltree │ title        : VARCHAR  │
│ description : TEXT       │       │ grade        : INT 1-10 │
│ manager_id  : INT FK     │───┐   │ description  : TEXT     │
│ is_active   : BOOL       │   │   │ requirements : JSON     │
│ unit_type   : VARCHAR    │   │   │ is_active    : BOOL     │
│ created_at  : TIMESTAMP  │   │   │ weight       : INT UQ   │ ← 0=top
│ updated_at  : TIMESTAMP  │   │   │ level        : INT      │ ← cached
└──────────────────────────┘   │   └─────────────────────────┘
                                │
┌──────────────────────────┐   │   ┌─────────────────────────┐
│    hr_employees          │   │   │     hr_documents        │
├──────────────────────────┤   │   ├─────────────────────────┤
│ id          : INT PK     │◄──┘   │ id           : INT PK   │
│ user_id     : INT UQ     │───────│ employee_id  : INT FK   │
│ first_name  : VARCHAR    │       │ title        : VARCHAR  │
│ last_name   : VARCHAR    │       │ doc_type     : VARCHAR  │
│ middle_name : VARCHAR    │       │ file_path    : VARCHAR  │
│ email       : VARCHAR UQ │       │ file_size    : INT      │
│ phone       : VARCHAR    │       │ mime_type    : VARCHAR  │
│ department_id: INT FK    │       │ uploaded_by  : INT FK   │
│ position_id : INT FK     │       │ metadata     : JSON     │
│ hire_date   : DATE       │       └─────────────────────────┘
│ termination_date: DATE   │
│ status      : VARCHAR    │  ← active|inactive|terminated
│ avatar_url  : VARCHAR    │
│ bio         : TEXT       │
│ is_deleted  : BOOL       │  ← soft delete
└──────────────────────────┘

┌──────────────────────────┐
│  hr_level_thresholds     │
├──────────────────────────┤
│ id           : INT PK    │
│ level_number : INT UQ    │  ← Уровень иерархии (≥1)
│ weight_from  : INT       │  ← Диапазон весов позиций
│ weight_to    : INT       │
│ label        : VARCHAR   │  ← Человекочитаемое название
│ color        : VARCHAR   │  ← Цвет для визуализации
└──────────────────────────┘

Дополнительные модели:
- hr_pmos — Проектные офисы (PMO)
- hr_pmo_departments — Привязка PMO к отделам
- hr_pmo_positions — Привязка PMO к должностям
- hr_pmo_members — Участники PMO
- hr_vacancies — Вакансии
- hr_applications — Заявки на вакансии
- hr_time_entries — Учёт рабочего времени
- hr_audit_logs — Журнал аудита
- hr_personnel_history — Кадровая история
- hr_reporting_relations — Отношения подчинения
- hr_org_settings — Настройки оргструктуры
- hr_shareable_links — Публичные ссылки на оргструктуру
```

### 2.3 Связь User ↔ Employee

```
auth.users.id  ←→  public.hr_employees.user_id (cross-schema, по значению, не FK)
```

> [!IMPORTANT]
> Прямой SQL FK между схемами **отсутствует** (изоляция сервисов). Связь поддерживается **по соглашению**: `hr_employees.user_id` хранит `auth.users.id`. Синхронизация — через HTTP (hr-service проксирует запросы к user-service) и Redis events (Dramatiq actors: `user_upserted`, `user_deactivated`).

---

## 3. Иерархия ролей и уровней доступа

### 3.1 Системные роли (User Service)

```
┌─────────────────────────────────────────────────────────────┐
│                    RBAC Hierarchy                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐                                            │
│  │ superuser   │ ← is_superuser=true                        │
│  │ (admin)     │   Полный доступ ко всем сервисам            │
│  └──────┬──────┘   JWT claim: is_admin=true                 │
│         │                                                   │
│  ┌──────┴──────┐                                            │
│  │   staff     │ ← is_staff=true                            │
│  │ (admin)     │   Административный доступ                   │
│  └──────┬──────┘   JWT claim: is_admin=true                 │
│         │                                                   │
│  ┌──────┴──────┐                                            │
│  │  employee   │ ← is_staff=false, is_superuser=false       │
│  │  (user)     │   Обычный пользователь                      │
│  └─────────────┘   JWT claim: is_admin=false                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 JWT Token Claims

Токены выпускаются **только** `user-service` (`create_token_pair`):

```json
{
  "user_id": 1,
  "username": "admin",
  "email": "admin@htq.example",
  "is_staff": true,
  "is_superuser": true,
  "is_admin": true,          // is_staff OR is_superuser
  "token_type": "access",
  "iat": "2026-05-05T00:00:00Z",
  "exp": "2026-05-05T02:00:00Z",  // 2 часа
  "iss": "htqweb-auth"
}
```

- **access token TTL**: 2 часа
- **refresh token TTL**: 7 дней
- `is_admin` = `is_staff OR is_superuser` — единый флаг для sqladmin и admin-операций

### 3.3 HR Service — Coarse Access Levels

Backend HR-service определяет уровень доступа HR (`/api/hr/v1/employees/hr-level/`):

| Уровень | Условие | Описание |
|---|---|---|
| `senior` | `is_admin OR is_staff OR is_superuser` | Полный HR доступ |
| `junior` | *(зарезервировано, пока не реализовано)* | Ограниченный HR доступ |
| `null` | Все остальные | Нет HR доступа |

### 3.4 HR Service — RBAC Constants

В `hr/app/auth/dependencies.py`:

```python
HR_WRITE_ROLES = {"hr_admin", "hr_manager", "admin"}
HR_READ_ROLES  = {"hr_admin", "hr_manager", "recruiter", "employee", "admin"}
```

> [!NOTE]
> Роли `hr_admin`, `hr_manager`, `recruiter` зарезервированы, но **не реализованы в user-service JWT**. На текущий момент `role` вычисляется из `is_admin`/`is_staff`/`is_superuser` → `"admin"` или `"employee"`. Тонкая гранулярность — будущая итерация.

### 3.5 Frontend — Роли и защита доступа

В `frontend/src/lib/auth/roles.ts`:

```typescript
ELEVATED_ROLES = ['staff', 'admin', 'superuser', 'hr_manager', 'senior_hr',
                  'junior_hr', 'senior_manager', 'junior_manager']

HR_ROLES       = ['hr_manager', 'senior_hr', 'junior_hr', 'senior_manager',
                  'junior_manager', 'staff']

EDITOR_ROLES   = ['editors', 'staff']
```

Функции:
- `hasElevatedAccess(profile)` — проверяет, что `profile.roles` содержит хотя бы одну из `ELEVATED_ROLES`
- `isHrManager(profile)` — проверяет принадлежность к `HR_ROLES`
- `isEditor(profile)` — проверяет принадлежность к `EDITOR_ROLES`

---

## 4. Механизм защиты маршрутов

### 4.1 Backend — JWT Middleware

**Паттерн**: каждый сервис реализует `auth/dependencies.py` с `get_current_user`:

```
HTTP Request → Authorization: Bearer <JWT>
                    ↓
         jwt.decode(token, shared_secret, issuer="htqweb-auth")
                    ↓
         TokenPayload(user_id, username, is_staff, is_superuser, is_admin, ...)
                    ↓
         Route handler: проверяет is_staff/is_superuser для admin-операций
```

**Защита администратора** (user-service — пример из `admin.py`):
```python
if not current_user.is_staff and not current_user.is_superuser:
    raise HTTPException(status_code=403, detail="Admin access required")
```

**Защита HR-записи** (hr-service — `require_hr_write`):
```python
if current_user.role not in HR_WRITE_ROLES:  # {"hr_admin", "hr_manager", "admin"}
    raise HTTPException(status_code=403, detail="Insufficient permissions")
```

### 4.2 Frontend — Route Guard

```
Маршрут с requiresAuth=true
            ↓
    <RequireAuth> wrapper
            ↓
    useActiveProfile() → проверяет наличие JWT в localStorage
            ↓
    Нет JWT → Redirect to /login
    Есть JWT → Проверка must_change_password → <ForcePasswordChange>
            ↓
    Рендер дочернего компонента
```

> [!WARNING]
> **Frontend НЕ проверяет роли на уровне роутинга.** Все `protectedRoutes` требуют только аутентификацию (`requiresAuth: true`). Авторизация по ролям происходит **внутри компонентов** через `useHRLevel()` и `hasElevatedAccess()`. Это означает, что URL-страницы HR доступны любому аутентифицированному пользователю, но данные блокируются backend-ом (403).

### 4.3 sqladmin — Admin Panel Authentication

```
Запрос к /sqladmin → JWTAdminAuthBackend.authenticate()
                   → Проверяет session["admin_jwt"] или cookie["admin_session"]
                   → jwt.decode → payload.is_admin == true
                   → False → Redirect to /admin/login
```

### 4.4 Матрица доступа по эндпойнтам

| Маршрут (Backend) | Защита | Минимальная роль |
|---|---|---|
| `POST /api/users/v1/register/` | Нет (публичный) | — |
| `POST /api/users/v1/token/` | Нет (публичный) | — |
| `GET /api/users/v1/pending-registrations/` | `is_staff OR is_superuser` | staff |
| `POST .../approve/`, `POST .../reject/` | `is_staff OR is_superuser` | staff |
| `GET /api/users/v1/admin/users/` | `is_staff OR is_superuser` | staff |
| `POST /api/users/v1/admin/users/` | `is_staff OR is_superuser` | staff |
| `PATCH /api/users/v1/admin/users/{id}/` | `is_staff OR is_superuser` | staff |
| `POST .../set-password/` | `is_staff OR is_superuser` | staff |
| `GET /api/hr/v1/employees/` | `get_current_user` (любой JWT) | employee |
| `POST /api/hr/v1/employees/` | `get_current_user` (любой JWT) | employee* |
| `GET /api/hr/v1/employees/hr-level/` | `get_current_user` | employee |
| `GET /api/hr/v1/departments/` | Зависит от роутера | employee |
| `POST /api/hr/v1/documents/` | `require_hr_write` | admin/hr_manager |
| `GET /api/hr/v1/public/*` | Нет (публичный) | — |
| `/sqladmin/*` | `JWTAdminAuthBackend` | admin (is_admin=true) |

| Маршрут (Frontend) | Тип | Защита компонента |
|---|---|---|
| `/login`, `/register`, `/news` | public | Нет |
| `/myprofile`, `/settings`, `/messenger` | protected | RequireAuth (JWT) |
| `/admin/users`, `/admin/chats`, `/admin/mailboxes` | protected | RequireAuth + `hasElevatedAccess` |
| `/hr/*` | protected | RequireAuth + `useHRLevel` |
| `/tasks/*` | protected | RequireAuth |
| `/conference` | protected | RequireAuth |
| `/email` | protected | RequireAuth |

---

## 5. Системы создания пользователей

### 5.1 Самостоятельная регистрация
```
POST /api/users/v1/register/
  → status=PENDING
  → Требует одобрения admin-ом через POST .../approve/
```

### 5.2 Создание администратором
```
POST /api/users/v1/admin/users/
  → Может задать status=active (сразу активный)
  → Может создать mailbox (email-service)
  → must_change_password=true по умолчанию
```

### 5.3 Создание из HR-сервиса
```
POST /api/hr/v1/employees/users/
  → Проксирует к user-service
  → Генерирует username из email, пароль случайный
  → must_change_password=true
```

---

## 6. Обнаруженные позиции и уровни (Weight System)

Система позиций использует **weight** (вес) для определения иерархии:
- `weight=0` — высшее руководство
- `weight=100` — по умолчанию, средний уровень
- Чем ниже weight, тем выше позиция

Уровни кэшируются из `hr_level_thresholds`:

| Level | Диапазон weights | Описание |
|---|---|---|
| 1 | 0–9 | C-Level / Директора |
| 2 | 10–49 | Руководители направлений |
| 3 | 50–99 | Старшие специалисты |
| 4 | 100–199 | Специалисты |
| 5 | 200+ | Младшие специалисты / стажёры |

> [!NOTE]
> Конкретные диапазоны настраиваются через `hr_level_thresholds` таблицу. Приведённые значения — типичные, но зависят от содержимого БД.

---

## 7. Вывод по безопасности

### Сильные стороны
- ✅ Единый JWT issuer (`user-service`) — нет разрозненных токенов
- ✅ Shared secret для валидации во всех сервисах
- ✅ sqladmin защищён `is_admin` claim
- ✅ Backend всегда проверяет роли (не полагается на фронтенд)

### Риски / зоны для тестирования
- ⚠️ **HR эндпойнты**: `GET/POST /employees/` не проверяют `require_hr_write` — любой аутентифицированный пользователь может читать/создавать сотрудников
- ⚠️ **Frontend routing**: отсутствие ролевых guards на уровне React Router — пользователь видит UI страницы до получения 403 от backend
- ⚠️ **Горизонтальная эскалация**: нет проверки принадлежности employee к текущему пользователю в `GET/PUT /{id}/`
- ⚠️ **Роли hr_manager/junior_hr**: объявлены, но не реализованы — тестировать невозможно

---

## 8. Интеграция MongoDB (Hybrid Architecture)

### 8.1 Архитектура гибридного хранения

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Гибридная архитектура данных                       │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  PostgreSQL (PgBouncer)                MongoDB                       │
│  ┌────────────────────┐                ┌────────────────────┐        │
│  │ auth.users         │                │ hr_documents       │        │
│  │ hr_employees  ─────│── synthetic FK │ ┌────────────────┐ │        │
│  │ hr_departments     │   (employee_id)│ │sql_employee_id │ │        │
│  │ hr_positions       │                │ │title           │ │        │
│  │ hr_documents (SQL) │                │ │doc_type        │ │        │
│  │ hr_vacancies       │                │ │content         │ │        │
│  │ hr_time_entries    │                │ │file_url        │ │        │
│  │ hr_audit_logs      │                │ │tags[]          │ │        │
│  │ ...                │                │ │metadata{}      │ │        │
│  └────────────────────┘                │ │created_at      │ │        │
│                                        │ └────────────────┘ │        │
│  Быстрые транзакции,                   │                    │        │
│  реляционные связи,                    └────────────────────┘        │
│  RBAC, auth                            Объёмные документы,           │
│                                        нечастый доступ,              │
│                                        гибкая схема                  │
└──────────────────────────────────────────────────────────────────────┘
```

### 8.2 Связь PostgreSQL ↔ MongoDB

**Синтетический внешний ключ**: `hr_documents.sql_employee_id` в MongoDB хранит
`hr_employees.id` из PostgreSQL в виде целого числа внутри BSON-документа.

```json
{
  "_id": ObjectId("..."),
  "sql_employee_id": 42,          // ← FK к hr_employees.id (PostgreSQL)
  "title": "Трудовой договор",
  "doc_type": "contract",
  "content": "...",
  "tags": ["трудовой", "договор"],
  "metadata": { "contract_number": "TD-1234" },
  "created_by_user_id": 1,
  "created_at": ISODate("..."),
  "updated_at": ISODate("...")
}
```

**Индексы MongoDB** (создаются автоматически при старте HR-service):
- `sql_employee_id` — быстрый поиск по сотруднику
- `doc_type` — фильтрация по типу документа
- `(sql_employee_id, doc_type)` — составной индекс
- `created_at` — сортировка по дате

### 8.3 API endpoints для MongoDB HR-документов

| Метод | Маршрут | Защита | Описание |
|---|---|---|---|
| `GET` | `/api/hr/v1/mongo-documents/` | JWT (любой) | Список документов, фильтр по employee_id/doc_type |
| `POST` | `/api/hr/v1/mongo-documents/` | `require_hr_write` | Создание документа |
| `GET` | `/api/hr/v1/mongo-documents/{doc_id}` | JWT (любой) | Получение документа |
| `PATCH` | `/api/hr/v1/mongo-documents/{doc_id}` | `require_hr_write` | Частичное обновление |
| `DELETE` | `/api/hr/v1/mongo-documents/{doc_id}` | `require_hr_write` | Удаление |

### 8.4 Типы HR-документов (MongoDB)

| Тип | Описание |
|---|---|
| `contract` | Трудовой договор |
| `order` | Приказ (о приёме, увольнении, переводе) |
| `certificate` | Справка, сертификат |
| `policy` | Политика, регламент |
| `memo` | Служебная записка |
| `performance_review` | Отчёт об аттестации |
| `disciplinary` | Дисциплинарное взыскание |
| `training` | Обучение, повышение квалификации |
| `other` | Прочее |

---

## 9. Панель администрирования (AdminJS)

### 9.1 Архитектура AdminJS

AdminJS развёрнут как **отдельный Docker-сервис** на порту `3300` с dual-adapter архитектурой:

| Адаптер | Источник данных | Ресурсы |
|---|---|---|
| `@adminjs/sequelize` | PostgreSQL через PgBouncer | Users, Departments, Positions, Employees |
| `@adminjs/mongoose` | MongoDB | HR Documents |

### 9.2 Доступ

- **URL**: `http://localhost:3300/admin`
- **Аутентификация**: email/пароль (env vars `ADMINJS_EMAIL` / `ADMINJS_PASSWORD`)
- **Навигация**:
  - `PostgreSQL — Auth` → Users
  - `PostgreSQL — HR` → Departments, Positions, Employees
  - `MongoDB — HR Documents` → HR Documents (BSON)

### 9.3 Сосуществование с sqladmin

Существующая панель `sqladmin` (порт `8012`, `/sqladmin`) **остаётся без изменений**.
AdminJS добавляется как дополнительный инструмент для работы с гибридными данными.

| Панель | Порт | Путь | БД |
|---|---|---|---|
| sqladmin | 8012 | `/sqladmin` | PostgreSQL (все схемы) |
| AdminJS | 3300 | `/admin` | PostgreSQL + MongoDB |

---

## 10. QA — Тестовые аккаунты и чек-лист

### 10.1 Сгенерированные тестовые аккаунты (15 шт.)

Скрипт: `scripts/generate_test_users.py`

| # | Email | Пароль | Роль | Статус | Должность | Отдел |
|---|---|---|---|---|---|---|
| 1 | `qa_superadmin@htq.test` | `SuperAdmin!2026` | superuser | active | Генеральный директор | Руководство |
| 2 | `qa_superadmin2@htq.test` | `SuperAdmin2!2026` | superuser | active | Исполнительный директор | Руководство |
| 3 | `qa_staff_admin@htq.test` | `StaffAdmin!2026` | staff | active | Системный администратор | IT Отдел |
| 4 | `qa_staff_hr@htq.test` | `StaffHR!2026` | staff | active | HR Директор | HR Отдел |
| 5 | `qa_senior_hr@htq.test` | `SeniorHR!2026` | staff | active | Старший HR-менеджер | HR Отдел |
| 6 | `qa_junior_hr@htq.test` | `JuniorHR!2026` | employee | active | Младший HR-специалист | HR Отдел |
| 7 | `qa_recruiter@htq.test` | `Recruiter!2026` | employee | active | Рекрутер | HR Отдел |
| 8 | `qa_senior_dev@htq.test` | `SeniorDev!2026` | employee | active | Старший разработчик | IT Отдел |
| 9 | `qa_junior_dev@htq.test` | `JuniorDev!2026` | employee | active | Младший разработчик | IT Отдел |
| 10 | `qa_manager@htq.test` | `Manager!2026` | employee | active | Менеджер проектов | Управление проектами |
| 11 | `qa_accountant@htq.test` | `Accountant!2026` | employee | active | Главный бухгалтер | Финансовый отдел |
| 12 | `qa_suspended@htq.test` | `Suspended!2026` | employee | **suspended** | Аналитик данных | IT Отдел |
| 13 | `qa_pending@htq.test` | `Pending!2026` | employee | **pending** | Стажёр | IT Отдел |
| 14 | `qa_rejected@htq.test` | `Rejected!2026` | employee | **rejected** | Кандидат | HR Отдел |
| 15 | `qa_must_change_pw@htq.test` | `MustChange!2026` | employee | active | Специалист поддержки | IT Отдел |

### 10.2 Чек-лист: Вертикальная эскалация привилегий

> Цель: убедиться, что пользователь с более низким уровнем доступа **не может** выполнять действия, предназначенные для более высокого уровня.

| # | Тест | Аккаунт | Действие | Ожидаемый результат |
|---|---|---|---|---|
| V1 | Employee → Admin users list | `qa_junior_dev` | `GET /api/users/v1/admin/users/` | **403 Forbidden** |
| V2 | Employee → Create user | `qa_senior_dev` | `POST /api/users/v1/admin/users/` | **403 Forbidden** |
| V3 | Employee → Approve registration | `qa_recruiter` | `POST .../pending-registrations/{id}/approve/` | **403 Forbidden** |
| V4 | Employee → Set password | `qa_manager` | `POST .../admin/users/{id}/set-password/` | **403 Forbidden** |
| V5 | Employee → Create MongoDB doc | `qa_junior_dev` | `POST /api/hr/v1/mongo-documents/` | **403 Forbidden** |
| V6 | Employee → Delete MongoDB doc | `qa_accountant` | `DELETE /api/hr/v1/mongo-documents/{id}` | **403 Forbidden** |
| V7 | Employee → sqladmin access | `qa_senior_dev` | Перейти на `http://:8012/sqladmin` | **Redirect to login** |
| V8 | Employee → AdminJS access | `qa_junior_hr` | Перейти на `http://:3300/admin` | **Login required** |
| V9 | Staff → Superuser-only ops | `qa_staff_admin` | Изменить `is_superuser` другого пользователя | Проверить: допустимо ли? |
| V10 | Suspended → Login | `qa_suspended` | `POST /api/users/v1/token/` | **401 / не может авторизоваться** |
| V11 | Pending → Login | `qa_pending` | `POST /api/users/v1/token/` | **401 / аккаунт не активен** |
| V12 | Rejected → Login | `qa_rejected` | `POST /api/users/v1/token/` | **401 / аккаунт отклонён** |
| V13 | must_change_pw → Normal access | `qa_must_change_pw` | Авторизоваться, проверить redirect на смену пароля | **ForcePasswordChange** |

### 10.3 Чек-лист: Горизонтальная эскалация привилегий (IDOR)

> Цель: убедиться, что пользователь **не может** получить доступ к данным другого пользователя того же уровня.

| # | Тест | Аккаунт 1 | Аккаунт 2 | Действие | Ожидаемый результат |
|---|---|---|---|---|---|
| H1 | Чужой профиль (frontend) | `qa_senior_dev` | `qa_junior_dev` | Изменить `user_id` в URL `/myprofile` | Нет доступа к чужим данным |
| H2 | Чужой employee record | `qa_junior_hr` | `qa_senior_dev` | `PUT /api/hr/v1/employees/{other_id}/` | **Проверить**: есть ли защита? ⚠️ |
| H3 | Чужой MongoDB документ | `qa_senior_dev` | `qa_accountant` | `GET /api/hr/v1/mongo-documents/{doc_id}` | **Проверить**: документ доступен любому аутентифицированному? ⚠️ |
| H4 | Чужой чат | `qa_senior_dev` | `qa_junior_dev` | `GET /api/messenger/rooms/{room_id}/` | Не участник → нет доступа |
| H5 | Чужие email | `qa_manager` | `qa_accountant` | `GET /api/email/v1/emails/?user_id={other}` | Только свои письма |

### 10.4 Чек-лист: Граничные случаи

| # | Тест | Описание | Как проверить |
|---|---|---|---|
| E1 | Просроченный JWT | Использовать токен с `exp` в прошлом | Подставить вручную → **401** |
| E2 | Подделка `is_admin` | Создать JWT с `is_admin=true`, но подписать другим секретом | Подставить → **401 Invalid token** |
| E3 | Несуществующий employee_id | `GET /api/hr/v1/mongo-documents/?employee_id=999999` | **200 + пустой массив** |
| E4 | SQL Injection через email | `POST /register/` с `email: "'; DROP TABLE users;--"` | **400 / email-валидация** |
| E5 | XSS в display_name | Создать user с `display_name: "<script>alert(1)</script>"` | HTML экранирован на фронтенде |
| E6 | Уволенный сотрудник | `qa_suspended` → проверить доступ к `/hr/documents` | **Не авторизуется (status=suspended)** |
| E7 | MongoDB ObjectId injection | `GET /api/hr/v1/mongo-documents/invalid_id` | **400 Invalid document ID format** |
| E8 | Массовое удаление | `DELETE /api/hr/v1/mongo-documents/` (без ID) | **405 Method Not Allowed** |

### 10.5 Как запустить тестирование

```bash
# 1. Поднять инфраструктуру
docker compose up -d db pgbouncer redis mongo

# 2. Запустить генератор тестовых данных
pip install psycopg2-binary faker pymongo bcrypt
python scripts/generate_test_users.py \
    --pg-dsn "postgresql://htqweb:change-me@localhost:5432/htqweb" \
    --mongo-uri "mongodb://htqweb:change-me-mongo@localhost:27017/htqweb_docs?authSource=admin"

# 3. Поднять сервисы
docker compose up -d user-service hr-service admin-service adminjs-panel

# 4. Проверка (Postman / curl):
# Логин superadmin:
curl -X POST http://localhost:8005/api/users/v1/token/ \
     -H "Content-Type: application/json" \
     -d '{"email":"qa_superadmin@htq.test","password":"SuperAdmin!2026"}'

# Использовать полученный access-token для последующих запросов:
# curl -H "Authorization: Bearer <token>" http://localhost:8006/api/hr/v1/mongo-documents/
```
