# Handoff: HR-задачи B и C (админка должностей + PMO allocation)

> Документ для продолжения работы в новом чате. Содержит весь контекст: что уже сделано, какие приняты архитектурные решения, что именно нужно сделать в задачах B и C, и где это лежит в коде. Никакого предварительного знакомства с проектом не нужно.

---

## 1. Что это за проект

`HTQWeb1` — внутренний enterprise-стек Hi-Tech Group, один из микросервисов — `services/hr/`. Стек:

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.0 async (`AsyncSession`, `Mapped`, `mapped_column`), PostgreSQL 14+ с `ltree` и `pgcrypto`, Alembic, Redis. Логи через `structlog`. Аутентификация — JWT, проверяется в `app/auth/dependencies.py`.
- **Frontend:** React 18 + Vite + TypeScript, TanStack Query, shadcn/ui (Radix + Tailwind). Граф рисуется на `@xyflow/react@^12` + `@dagrejs/dagre`. Уже установлены.
- **Сервис HR:** `services/hr/`, схема `public` в БД (search_path задаётся в `app/db.py`), порт 8006, префикс API `/api/hr/v1`. Тесты — pytest + pytest-asyncio + httpx.AsyncClient, фикстуры в `services/hr/tests/conftest.py`. Тесты гоняются на testcontainers Postgres (или `TEST_DATABASE_URL`).

Полная структура и навигация: см. `STRUCTURE.md` в корне репозитория. Бизнес-логика всегда живёт в `app/services/<domain>_service.py`, роуты в `app/api/v1/<file>.py` тонкие.

---

## 2. Что уже сделано (задача A — не повторять)

Задача A («безопасность share-ссылок»), миграция **007**, уже выехала. После неё:

- `hr_shareable_links` хранит `token_hash` (SHA-256), сырой `token` для новых строк = `NULL`, legacy-строки сохраняют исходный `token` до планового drop.
- Новые поля: `viewer_label`, `watermark_text`, `revoked_at`, `used_at`.
- Таблица `hr_share_link_audit` с действиями `created/open/denied_*/revoked` (append-only).
- `POST /api/hr/v1/share-links/` теперь возвращает `{token, url, ...}` ровно один раз; список и detail токен не отдают.
- `GET /api/hr/v1/share-links/{id}/audit` — журнал открытий.
- Публичный `GET /api/hr/v1/public/org/{token}` хэширует входящий токен, ищет по `token_hash`, пишет аудит, возвращает `watermark` payload.
- Frontend: `frontend/src/components/share-link/ShareWatermark.tsx` (CSS overlay), модалка одноразового показа URL и журнал в `frontend/src/pages/hr/HRShareLinks.tsx`.
- Тесты: `services/hr/tests/integration/test_share_links.py`.

**Следующая миграция нумеруется 008 (для B), потом 009 (для C).** `down_revision` ставить корректно.

---

## 3. Принятые архитектурные решения (важно — следовать)

Эти решения приняты в обсуждении задачи A и распространяются на B и C:

1. **Не переименовывать существующие колонки.** В частности, в `hr_pmo_members` колонки называются `from_date` / `to_date` — НЕ переименовывать в `valid_from/valid_to`. Pydantic-схемы используют `from_date/to_date`.
2. **Иерархия — через `Department.path` (LTREE).** Концепции «двух штабов с virtual root» и `staff_id` не вводить — у проекта одна оргструктура через департаменты. `path` уже на `Department`, не на `Employee`.
3. **One-time enforcement = `SELECT FOR UPDATE` в Postgres.** Никаких Lua-скриптов в Redis, никакого дублирования source-of-truth. Redis допустим только для rate-limit и кэша дерева.
4. **Никогда не отдавать PII** (`email`, `phone`, `salary`, `iin`, `birthday`, `home_address`) в публичных эндпоинтах. Под публикой — отдельная Pydantic `*Public` схема, не `model_dump(exclude=...)`.
5. **Любые изменения схемы БД — только через новую Alembic-миграцию.** Никаких `op.execute("ALTER ...")` в коде приложения.
6. **Аудит — append-only таблицы.** Никогда не UPDATE/DELETE.
7. **Не ломать публичные контракты.** Существующие эндпоинты расширяем опциональными query-параметрами, новые шлём sibling-роутами. Не плодить `/v2/` без необходимости.
8. **Локальные тесты гоняются через `pytest -p pytest_asyncio` из `services/hr/`.** Конфигурация — в `services/hr/tests/conftest.py`. Хелперы для авторизации: `admin_headers()` и `make_admin_token(user_id=...)`.

---

## 4. Текущее состояние моделей (для контекста задач)

### `services/hr/app/models/position.py`

```python
class Position(BaseModel):  # BaseModel = id + created_at + updated_at
    name: Mapped[str]                              # "Менеджер"
    department_id: Mapped[int]                     # FK
    weight: Mapped[int]                            # NOT NULL, INDEXED, sparse 0..N
    level: Mapped[int]                             # NOT NULL, кешируется из LevelThreshold
    is_active: Mapped[bool]                        # NOT NULL, default True
    # ... другие поля проф. описания
```

Уникальный индекс на `weight` **есть** — учитывать при «уплотнении» weights.

### `services/hr/app/models/level_threshold.py`

Уровень = диапазон весов с лейблом. Сейчас 5 уровней по умолчанию (миграция 002):

```python
class LevelThreshold(BaseModel):
    level_number: Mapped[int]      # UNIQUE, 0..N (0 = топ)
    weight_from: Mapped[int]
    weight_to: Mapped[int]
    label: Mapped[str]             # "C-level", "Директор", "Руководитель", "Менеджер", "Сотрудник"
```

### `services/hr/app/models/pmo.py`

```python
class PMO(BaseModel):
    code: Mapped[str]                             # UNIQUE
    name: Mapped[str]
    description: Mapped[str | None]
    head_employee_id: Mapped[int | None]          # FK на employees
    status: Mapped[str]                           # 'active' | 'suspended' | 'closed'
    # parent_pmo_id, target_kind, target_id — есть, см. файл

class PMOMember(Base):
    pmo_id: Mapped[int]                           # FK
    employee_id: Mapped[int]                      # FK
    membership_type: Mapped[str]                  # 'lead' | 'pm' | 'analyst' | ...
    position_in_pmo: Mapped[str | None]
    from_date: Mapped[date]                       # NOT NULL
    to_date: Mapped[date | None]                  # NULL = бессрочно
    # UNIQUE (pmo_id, employee_id, from_date) — НЕ менять
```

`PMOMember` **наследуется от `Base`, не `BaseModel`** — у неё нет `id`/`created_at`. Учитывать.

---

## 5. Существующие сервисы и API (B/C расширяют их, не заменяют)

### Должности

- `services/hr/app/services/position_service.py` — есть `_compute_level(weight)`, `update_weight()`, `_recompute_levels_in_range()`, `update_threshold()` (правка `LevelThreshold` с автопересчётом).
- `services/hr/app/api/v1/positions.py` — есть:
  - `GET /positions/` — список
  - `GET /positions/levels/` — все уровни
  - `PUT /positions/levels/{level_number}` — изменить диапазон уровня (вызывает recompute)
  - `PATCH /positions/{id}/weight` — поменять вес (с автопересчётом level)
- Frontend: `frontend/src/pages/hr/HRPositions.tsx` — таблица с inline-редактированием weight, цвета по уровню (`LEVEL_COLORS`).

### PMO

- `services/hr/app/services/pmo_service.py` — есть `create()`, `update()`, `delete()` (soft через `status`), `list_members()`, `add_member()`, `remove_member()`, `get_pmo_org_chart()`.
- `services/hr/app/api/v1/pmo.py` — `CRUD /pmo`, `GET/POST/DELETE /pmo/{id}/members`, `GET /pmo/{id}/org-chart`.
- Frontend: `frontend/src/pages/hr/HRPMO.tsx` — список + участники + мини-график.

---

# === ЗАДАЧА B: Админка должностей (DnD + move + rebalance + admin/levels) ===

## B.1. Цель

Дать админу:
1. Перетаскивать позиции в списке внутри уровня и между уровнями (drag-and-drop) — на бэке это превращается в назначение нового `weight` через сервер.
2. Кнопку «Перебалансировать» — массово выставить `weight = rownum * 100` в одной транзакции с инвалидацией кэшей.
3. Полноценный CRUD `LevelThreshold` через UI на отдельной странице `/admin/levels` с цвет-пикером.

## B.2. Backend

### B.2.1. Новых моделей не нужно

Используем существующий `Position` и `LevelThreshold`. Если у `LevelThreshold` нет колонки `color VARCHAR(7)` — добавить миграцией 008.

Также нужна append-only таблица аудита изменений веса/уровня:

```python
class PositionWeightAudit(Base):
    __tablename__ = "hr_position_weight_audit"
    id: Mapped[int]                                # BIGINT PK autoincrement
    position_id: Mapped[int]                       # FK ON DELETE CASCADE
    old_weight: Mapped[int | None]
    new_weight: Mapped[int | None]
    old_level: Mapped[int | None]
    new_level: Mapped[int | None]
    changed_by: Mapped[int | None]                 # user_id, может быть NULL для system
    changed_at: Mapped[datetime]                   # server_default=now()
    reason: Mapped[str | None]                     # 'move' | 'rebalance' | 'threshold_change' | ручной текст
    # INDEX (position_id, changed_at)
```

### B.2.2. Миграция `008_position_admin.py`

- `down_revision = "007"`
- `ALTER TABLE hr_level_thresholds ADD COLUMN color VARCHAR(7) NULL` (если ещё нет — проверить миграцию 002)
- `CREATE TABLE hr_position_weight_audit (...)` с индексом
- НИКАКИХ изменений в `hr_positions`

### B.2.3. Новые/изменённые сервисные методы

В `position_service.py`:

```python
async def move_position(
    self,
    position_id: int,
    *,
    before_position_id: int | None = None,
    after_position_id: int | None = None,
    actor_user_id: int | None = None,
) -> Position:
    """Поставить position между before и after.

    Алгоритм:
    1. SELECT FOR UPDATE по обеим сторонам (если заданы) и самому position.
    2. new_weight = (before.weight + after.weight) // 2.
       Если before is None: new_weight = after.weight - 100.
       Если after is None:  new_weight = before.weight + 100.
       Если |before.weight - after.weight| < 2: вызвать rebalance_level(level=before.level)
       и пересчитать new_weight ПОСЛЕ ребаланса.
    3. UPDATE position SET weight = new_weight; пересчитать level из LevelThreshold.
    4. Записать строку в hr_position_weight_audit.
    5. Инвалидировать redis-кэш 'org:tree:*' (если используется).
    """
    ...

async def rebalance_level(self, level: int, *, actor_user_id: int | None = None) -> int:
    """Уплотнить веса всех позиций уровня: weight = rownum * 100. Вернуть число затронутых.

    Одна транзакция. Audit-строка на каждое изменившееся значение.
    """
    ...

async def rebalance_all(self, *, actor_user_id: int | None = None) -> dict[int, int]:
    """Аналог по всем уровням. Возвращает {level: count}."""
    ...
```

В `position_service.py` уже есть `update_weight()` — её **не дублировать**, а внутри `move_position` вызвать общий приватный `_apply_new_weight(position, new_weight, reason, actor)`, в который вынести и текущую `update_weight`, и логику записи в audit.

### B.2.4. Новые роуты

В `services/hr/app/api/v1/positions.py`:

```python
class MoveIn(BaseModel):
    before_position_id: int | None = None
    after_position_id: int | None = None

@router.post("/{position_id}/move", response_model=PositionOut)
async def move_position(
    position_id: int,
    body: MoveIn,
    svc: PositionService = Depends(_svc),
    user = Depends(get_current_user),  # проверить роль admin/hr
):
    if not body.before_position_id and not body.after_position_id:
        raise HTTPException(422, "before_position_id or after_position_id required")
    return await svc.move_position(
        position_id,
        before_position_id=body.before_position_id,
        after_position_id=body.after_position_id,
        actor_user_id=user.user_id,
    )

@router.post("/rebalance", status_code=status.HTTP_202_ACCEPTED)
async def rebalance(
    level: int | None = None,
    svc: PositionService = Depends(_svc),
    user = Depends(get_current_user),
):
    """Если level=None — перебалансировать всё. Возвращает {level: count}."""
    if level is not None:
        n = await svc.rebalance_level(level, actor_user_id=user.user_id)
        return {"level": level, "updated": n}
    return await svc.rebalance_all(actor_user_id=user.user_id)
```

Защита по роли: посмотреть в `app/auth/dependencies.py`, есть ли уже helper типа `require_role`. Если нет — добавить:

```python
def require_role(*roles: str):
    async def _dep(user=Depends(get_current_user)):
        # JWT payload в проекте включает is_staff/is_superuser/is_admin (см. tests/conftest)
        if not (user.is_admin or user.is_superuser):
            raise HTTPException(403)
        return user
    return _dep
```

### B.2.5. Тесты (новый файл `tests/integration/test_positions_admin.py`)

- (а) `move_position(before=None, after=X)` — позиция получает weight = X.weight - 100.
- (б) `move_position(before=X, after=Y)` где Y.weight - X.weight = 1 — триггерит ребаланс уровня; финальный weight уложен в новый промежуток.
- (в) `rebalance_level(level=2)` — все позиции уровня получили (rownum)*100.
- (г) Аудит: каждое изменение веса/уровня даёт строку в `hr_position_weight_audit` с правильным `actor_user_id` и `reason`.
- (д) `DELETE /positions/levels/{n}` где есть position на этом уровне — 409 (уже должно работать в существующем коде; проверить).
- (е) После `move_position` сортировка `/org/tree` — `level ASC, weight ASC, full_name ASC`.

## B.3. Frontend

### B.3.1. Зависимость

Добавить в `frontend/package.json`:

```json
"@dnd-kit/core": "^6.1.0",
"@dnd-kit/sortable": "^8.0.0",
"@dnd-kit/utilities": "^3.2.2"
```

### B.3.2. Страница `/admin/positions`

- Расширить `frontend/src/pages/hr/HRPositions.tsx` (или вынести в `frontend/src/pages/admin/AdminPositions.tsx` если такой шаблон уже принят в проекте — сначала проверить наличие админ-секции в `app/routing/routeDefinitions.ts`).
- Группировать позиции по `level`, внутри уровня — `<DndContext>` + `<SortableContext>` с `verticalListSortingStrategy`.
- На `onDragEnd`:
  - Если кинули в тот же уровень: вычислить before/after id-шники соседей в новом порядке, вызвать `POST /positions/{id}/move`.
  - Если кинули в другой уровень: тот же `move`, но соседи — из целевого уровня.
- Кнопка «Перебалансировать всё» в шапке — вызывает `POST /positions/rebalance` без параметра.
- Optimistic update: сразу переставляем в локальном кэше TanStack Query, откатываем при ошибке. После — `invalidateQueries(['hr-positions'])`.

### B.3.3. Страница `/admin/levels`

Новый файл `frontend/src/pages/admin/AdminLevels.tsx`:

- Список карточек с `level_number`, `weight_from`, `weight_to`, `label`, `color`.
- Inline-редактирование, цвет — `<input type="color">`.
- Создание/удаление уровня (бэкенд endpoints для create/delete уровней — добавить в `position_service` и `positions.py`, если ещё нет).
- Регистрация роута: `frontend/src/app/routing/routeDefinitions.ts` + `lazyPages.ts`.

## B.4. Критерии приёмки B

1. Перетаскивание 50 позиций без видимых лагов; оптимистичное обновление; ошибка → откат.
2. Кнопка «Перебалансировать» в одной транзакции выставляет sparse-spacing; на каждое изменение — строка в `hr_position_weight_audit`.
3. CRUD уровней через UI с цвет-пикером; цвет потом виден в OrgChart как обводка.
4. `/org/tree` сортирует по `(level, weight, full_name)`.
5. Покрытие новых сервис-методов и роутов >85%.

---

# === ЗАДАЧА C: PMO allocation (allocation_percent + is_primary + reverse lookup) ===

## C.1. Цель

1. Отслеживать процент загрузки сотрудника в каждом PMO (`allocation_percent`).
2. Один сотрудник в PMO может быть лидом (`is_primary=true`); таких ровно один на PMO.
3. По сотруднику быстро возвращать список его активных PMO с ролью и процентом.
4. UI показывает warning, если сумма `allocation_percent` сотрудника по активным PMO > 100% (НЕ блокировать — только предупредить).

## C.2. Backend

### C.2.1. Миграция `009_pmo_allocation.py`

```python
def upgrade():
    op.add_column("hr_pmo_members",
        sa.Column("allocation_percent", sa.SmallInteger(),
                  nullable=False, server_default="100"))
    op.add_column("hr_pmo_members",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_check_constraint(
        "ck_pmo_member_allocation_pct",
        "hr_pmo_members",
        "allocation_percent BETWEEN 0 AND 100",
    )
    # Один lead на PMO среди активных. Активный = to_date IS NULL.
    op.execute(
        "CREATE UNIQUE INDEX ux_pmo_one_primary "
        "ON hr_pmo_members(pmo_id) "
        "WHERE is_primary AND to_date IS NULL"
    )
    op.create_index(
        "ix_pmo_members_employee_active",
        "hr_pmo_members",
        ["employee_id"],
        postgresql_where=sa.text("to_date IS NULL"),
    )

def downgrade():
    op.drop_index("ix_pmo_members_employee_active", table_name="hr_pmo_members")
    op.execute("DROP INDEX IF EXISTS ux_pmo_one_primary")
    op.drop_constraint("ck_pmo_member_allocation_pct", "hr_pmo_members", type_="check")
    op.drop_column("hr_pmo_members", "is_primary")
    op.drop_column("hr_pmo_members", "allocation_percent")
```

`down_revision = "008"`. Если задача B не сделана — поставить `"007"`.

### C.2.2. Обновление модели

В `services/hr/app/models/pmo.py` добавить поля в `PMOMember`:

```python
allocation_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=100)
is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

Импорт `SmallInteger` из `sqlalchemy`.

### C.2.3. Сервис

В `pmo_service.py`:

```python
async def add_member(
    self, pmo_id: int, data: dict, *, actor_user_id: int | None = None,
) -> tuple[PMOMember, bool]:
    """Возвращает (member, has_overallocation_warning).

    Бизнес-правила:
    - is_primary=True: проверить, что нет другого активного primary в этом PMO.
      Если есть — поднять HTTPException(409, "PMO already has a primary member").
    - allocation_percent: не валидировать сумму, но вернуть warning-флаг.
    """
    ...

async def get_employee_pmos(self, employee_id: int) -> list[dict]:
    """Активные PMO сотрудника с allocation. Используется для UI и
    для проверки overallocation."""
    ...

async def employee_total_allocation(self, employee_id: int) -> int:
    """Сумма allocation_percent по активным членствам сотрудника."""
    ...
```

При `add_member` и `update_member`, если `employee_total_allocation > 100` — НЕ кидать ошибку, вернуть warning. Роутер положит warning в HTTP-заголовок `X-Allocation-Warning: <value>`.

### C.2.4. Новые/изменённые роуты

```python
# services/hr/app/api/v1/pmo.py
class MemberIn(BaseModel):
    employee_id: int
    membership_type: Literal['lead','pm','analyst','developer','observer','other']
    position_in_pmo: str | None = None
    allocation_percent: int = Field(default=100, ge=0, le=100)
    is_primary: bool = False
    from_date: date = Field(default_factory=date.today)
    to_date: date | None = None

    @field_validator("to_date")
    @classmethod
    def _check_dates(cls, v, info):
        if v is not None and v <= info.data["from_date"]:
            raise ValueError("to_date must be > from_date")
        return v

@router.post("/{pmo_id}/members", response_model=MemberOut, status_code=201)
async def add_member(pmo_id: int, body: MemberIn, response: Response, ...):
    member, warning_total = await svc.add_member(pmo_id, body.model_dump(), actor_user_id=user.user_id)
    if warning_total > 100:
        response.headers["X-Allocation-Warning"] = str(warning_total)
    return member

@router.patch("/{pmo_id}/members/{member_id}", response_model=MemberOut)
async def update_member(...): ...

# Новый: reverse-lookup
@router.get("/employees/{employee_id}/pmos", response_model=list[EmployeePmoOut])
async def employee_pmos(employee_id: int, svc = Depends(_svc), user = Depends(get_current_user)):
    return await svc.get_employee_pmos(employee_id)
```

Внимание: путь `/employees/{employee_id}/pmos` логически принадлежит namespace employees. Можно либо положить его в `services/hr/app/api/v1/employees.py` (impl зовёт `pmo_service`), либо смонтировать в pmo router без префикса. Предпочтительно — в `employees.py`, чтобы клиенты искали в одном месте.

### C.2.5. Тесты (`tests/integration/test_pmo_allocation.py`)

- (а) Добавление 3 участников с разной ролью и `allocation_percent`; `GET /pmo/{id}/members` возвращает их.
- (б) Попытка добавить второго `is_primary=true` в активные → 409.
- (в) После `to_date` уходящего primary можно назначить нового.
- (г) Если у сотрудника сумма по 3 активным PMO = 110% — POST/PATCH возвращает 200/201, но в `X-Allocation-Warning: 110`.
- (д) `to_date <= from_date` → 422.
- (е) `GET /api/hr/v1/employees/{id}/pmos` возвращает только активные (`to_date IS NULL` или в будущем) и не отдаёт сотрудников из soft-deleted PMO.
- (ж) Soft-delete PMO (`status='closed'`): все members получают `to_date=today` (если этот side-effect ожидается — добавить в сервис).

## C.3. Frontend

### C.3.1. Изменения в `HRPMO.tsx`

- В таблице участников показать колонки `Загрузка %` и бейдж «Лид» (если `is_primary`).
- Форма добавления участника:
  - `<Input type="number" min=0 max=100 />` для allocation.
  - Чекбокс «Назначить лидом».
- Если ответ создания/обновления вернул заголовок `X-Allocation-Warning` — показать неблокирующий `<Alert>` сверху таблицы: «Суммарная нагрузка сотрудника в активных PMO: 110%. Превышает 100%».
- Получить заголовок: в TanStack Query mutation `mutationFn` использовать `axios` напрямую и читать `response.headers['x-allocation-warning']`, прокинуть через `onSuccess` в локальный `useState`.

### C.3.2. Профиль сотрудника

- Если есть страница профиля (`MyProfile.tsx` или `/employees/{id}`): добавить блок «Мои проекты (ПМУ)»:
  - `useQuery(['employee-pmos', id], () => api.get('hr/v1/employees/{id}/pmos'))`.
  - Список PMO с ролью и процентом.
  - Под списком — суммарная загрузка с предупреждением, если >100%.

## C.4. Критерии приёмки C

1. Добавление 20 участников в PMO с разными ролями и процентами; partial unique index запрещает второй активный primary.
2. Сотрудник с суммой 110% получает warning, не блок.
3. Soft-delete PMO снимает (`to_date=today`) всех активных участников.
4. `/employees/{id}/pmos` отдаёт только активные.
5. UI показывает бейдж «Лид» и предупреждение о перегрузке.
6. Покрытие новых сервис-методов и роутов >85%.

---

## 6. Чек-лист действий для нового агента

В порядке выполнения:

1. **Прочитать этот файл целиком.**
2. Прочитать актуальные модели и сервисы:
   - `services/hr/app/models/position.py`, `level_threshold.py`, `pmo.py`.
   - `services/hr/app/services/position_service.py`, `pmo_service.py`.
   - `services/hr/app/api/v1/positions.py`, `pmo.py`, `employees.py`.
   - `services/hr/tests/conftest.py` (фикстуры и хелперы для тестов).
3. Проверить, что миграция 007 уже в `services/hr/alembic/versions/` — это контрольная точка. Если её нет — сначала пройти задачу A (см. раздел 2 этого документа и `services/hr/app/models/shareable_link.py`, который уже отражает целевое состояние).
4. Решить порядок: B → C (естественный — sortable level definitions раньше, чем PMO).
5. Делать каждую задачу одной feature-веткой и одним PR. Миграцию 008 (B) и 009 (C) — разными ревизиями.
6. Перед мерджем: `pytest services/hr/tests/integration/` зелёный, `tsc --noEmit -p tsconfig.app.json` без новых ошибок (pre-existing TS-ошибки в `AdminChats.tsx`, `ConferencePage.tsx`, `Email/*` — НЕ трогать).

## 7. Что НЕ делать

- Не переименовывать колонки `from_date/to_date` в PMOMember в `valid_from/valid_to`.
- Не вводить `Employee.path`, `staff_id`, virtual root — иерархия уже через `Department.path`.
- Не вводить Redis Lua для one-time или allocation — Postgres `SELECT FOR UPDATE` достаточно.
- Не добавлять `BaseModel` к `PMOMember` (она наследуется от `Base` и не имеет `id`/`created_at` — это намеренно).
- Не отдавать PII в публичных эндпоинтах.
- Не делать `/v2/` форки существующих роутов — расширять опциональными параметрами.
- Не создавать общую библиотеку между микросервисами — изоляция намеренная.
- Не трогать `backend/` — это мёртвые остатки Django.

---

## 8. Полезные команды

```bash
# Запуск тестов HR-сервиса (нужен Docker или TEST_DATABASE_URL):
cd services/hr && pytest tests/integration/ -v

# Применить новую миграцию локально:
cd services/hr && alembic upgrade head

# Проверить TypeScript фронта:
cd frontend && npx tsc --noEmit -p tsconfig.app.json

# Сгенерировать Alembic-миграцию по diff моделей (использовать как стартовую точку,
# затем дописать data-migration вручную):
cd services/hr && alembic revision --autogenerate -m "008_position_admin"
```

---

Удачи. Любые вопросы по архитектуре — `STRUCTURE.md` в корне репо, по микросервисам — `services/README.md`.
