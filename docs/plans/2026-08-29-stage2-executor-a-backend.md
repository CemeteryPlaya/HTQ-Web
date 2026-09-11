# Стадия 2 «Доступ и роли» · Исполнитель A (бэкенд) — план реализации

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ СУБ-СКИЛЛ: используйте
> `superpowers:subagent-driven-development` (рекомендуется) или
> `superpowers:executing-plans` для выполнения задача-за-задачей. Шаги
> размечены чекбоксами (`- [ ]`).

**Цель:** ввести аппку `apps.access` — глобальный каталог ролей, привязку
«должность → роли», личные назначения и разрешение прав по паре «модуль ×
уровень», с API по замороженному контракту.

**Архитектура:** роль заводится один раз на всю платформу и лежит в `public`;
должность принадлежит компании и живёт в её схеме (`apps.hr`). Связывают их две
таблицы в `public`, несущие слаг компании явным столбцом. Права сотрудника —
объединение прав ролей его должности и его личных назначений; иерархия задаёт
подчинение и область, но не наследует права.

**Стек:** Django 5.2.7, Python 3.14, psycopg 3, Postgres, pytest-django.

**Спека:** [2026-08-29-stage2-access-and-roles-spec.md](2026-08-29-stage2-access-and-roles-spec.md)
— §1 (модель), §4 (замороженный контракт API), §5 (задачи A1–A9).
Соответствие задач плана пунктам спеки указано в заголовке каждой задачи.

**Парный план:** [исполнитель B (фронтенд)](2026-08-29-stage2-executor-b-frontend.md).
Стык — только §4 спеки. Точка синхронизации — задача 7 (API готов).

---

## Глобальные ограничения

- **Ветка `structure-refactoring`.** Новых веток не создавать.
- **Зона — только `backend/**` и `docs/**`.** Файлы `frontend/**` принадлежат
  исполнителю B; правка любого из них ломает бесконфликтное слияние.
- **Межаппный доступ только через `apps.<x>.interface`.** Прямой импорт
  `apps.<other>.models` / `.services` запрещён и ловится
  `apps/core/tests/test_app_isolation.py`. Исключение — `apps.core`.
- **Межаппных ForeignKey нет.** Ссылка на чужую аппку — обычный
  `IntegerField`/`CharField` (образец: `apps.hr.models.Employee.user_id`).
  ⚠️ Это относится и к компании: `ForeignKey` на `companies.Company` из
  `apps.access` **запрещён**, ссылка мягкая — `company_slug`.
- **`APPEND_SLASH = False`** — в `urls.py` регистрируются оба написания пути.
- **Конверт ошибки всегда `{"detail": ...}`** (401/403/404/409/422/500/503).
- **Тесты идут против настоящего Postgres** на `:55432`. Поднять один раз:
  `docker compose -f docker-compose.test-local.yml up -d db`. **НЕ**
  `docker restart` — это роняет проброс порта.
- **Python-окружение:** команды запускаются из `backend/`, интерпретатор
  `../.venv/Scripts/python.exe`. Проверка: он обязан напечатать `5.2.7` на
  `-c "import django; print(django.__version__)"`.
- **Режим подмен в тестах — `strict`.** Любая подмена значения оформляется
  через `htqweb/fallback.py`, а не `try/except`-ом с дефолтом.
- **Уровни:** `none < read < write < admin`. Доступ разрешён, если
  эффективный уровень **не ниже** требуемого.
- **Модули** — значения `apps.core.models.KNOWN_SERVICES`. Своего справочника
  модулей аппка не заводит.
- **Коммит после каждой задачи**, сообщение на русском, префикс
  `feat(access):` / `test(access):` / `refactor(access):`.

---

## Структура файлов

**Создаются:**

| Файл | Ответственность |
|---|---|
| `backend/apps/access/__init__.py` | пусто |
| `backend/apps/access/apps.py` | `AccessConfig` с `API_PREFIX = "api/access/v1/"` |
| `backend/apps/access/models.py` | `Role`, `RoleModulePermission`, `PositionRole`, `RoleAssignment`, `Level` |
| `backend/apps/access/schemas.py` | Pydantic-схемы тел запросов по §4 |
| `backend/apps/access/services/catalog.py` | каталог ролей: создание, переименование, удаление, права роли |
| `backend/apps/access/services/assignment.py` | роли должности и личные назначения, валидация области |
| `backend/apps/access/services/resolve.py` | разрешение прав (§1.5 спеки) |
| `backend/apps/access/services/hierarchy.py` | подчинённые компании (§1.4 спеки) |
| `backend/apps/access/views.py` | HTTP-слой, CBV на `htqweb.http.ApiView` |
| `backend/apps/access/urls.py` | маршруты в обоих написаниях |
| `backend/apps/access/interface.py` | единственная дверь для соседей |
| `backend/apps/access/metrics.py` | `collect()` для `apps/core/metrics.py` |
| `backend/apps/access/admin.py` | регистрация моделей с `ServiceGatedAdminMixin` |
| `backend/apps/access/tests/*` | тесты задач ниже |

**Правятся:**

| Файл | Правка |
|---|---|
| `backend/htqweb/settings/base.py` | `apps.access` в `INSTALLED_APPS` (и **не** в `TENANT_APPS`) |
| `backend/apps/core/models.py` | `"access"` в `KNOWN_SERVICES` |
| `backend/apps/core/services.py` | `"access"` в `CORE_MODULES` |
| `backend/htqweb/middleware/service_gate.py` | `"/api/access/": "access"` в `PREFIX_TO_SERVICE` |
| `backend/apps/hr/interface.py` | `position_id` в ответе `get_employee_brief` |
| `backend/htqweb/http.py` | `module=`/`level=` в `api_view` |
| `backend/apps/users/services/profile_service.py` | карта прав в ответе профиля |

---

## Задача 1: Скелет `apps.access` (спека A1)

**Files:**
- Create: `backend/apps/access/__init__.py`, `apps.py`, `urls.py`, `views.py`,
  `interface.py`, `metrics.py`, `models.py` (пустой), `services/__init__.py`,
  `tests/__init__.py`, `tests/test_skeleton.py`
- Modify: `backend/htqweb/settings/base.py`, `backend/apps/core/models.py`,
  `backend/apps/core/services.py`, `backend/htqweb/middleware/service_gate.py`

**Interfaces:**
- Produces: смонтированный префикс `/api/access/v1/`, имя сервиса `access`
  в реестре модулей.

- [ ] **Шаг 1: Тест на монтирование и на отсутствие аппки в TENANT_APPS**

`backend/apps/access/tests/test_skeleton.py`:

```python
import pytest
from django.conf import settings
from django.urls import resolve


def test_access_is_not_a_tenant_app():
    """Роль одна на все компании (спека §1.3), значит таблицы в public."""
    assert "access" not in settings.TENANT_APPS


def test_access_has_no_holding_module():
    """holding.py обязателен только тенантным аппкам; у общей его быть не должно."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("apps.access.holding")


def test_prefix_is_mounted():
    assert resolve("/api/access/v1/roles").func is not None


def test_access_is_a_core_module():
    """Выключенный доступ означал бы «ни у кого нет прав» — это не режим работы."""
    from apps.core.services import CORE_MODULES
    assert "access" in CORE_MODULES
```

- [ ] **Шаг 2: Прогнать — тест обязан упасть**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_skeleton.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'apps.access'`

- [ ] **Шаг 3: Завести аппку**

`backend/apps/access/apps.py`:

```python
from django.apps import AppConfig


class AccessConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.access"
    verbose_name = "Доступ и роли"
    # URL-автодискавери (htqweb/urls.py) монтирует аппку по этому префиксу —
    # htqweb/urls.py не правится (правило №3, backend/README.md).
    API_PREFIX = "api/access/v1/"
```

`backend/apps/access/urls.py`:

```python
"""Маршруты ``/api/access/v1/*`` (контракт — спека §4).

``APPEND_SLASH = False``: каждый путь зарегистрирован в обоих написаниях,
со слэшем и без, иначе редирект теряет заголовок ``Authorization``.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("roles", views.RoleCollectionView.as_view()),
    path("roles/", views.RoleCollectionView.as_view()),
]
```

`backend/apps/access/views.py` — заглушка, наполняется в задаче 7:

```python
from htqweb.http import ApiView


class RoleCollectionView(ApiView):
    pass
```

- [ ] **Шаг 4: Зарегистрировать аппку и имя сервиса**

`htqweb/settings/base.py` — в `INSTALLED_APPS`, сразу после `"apps.companies"`:

```python
    # Роли и права. Живёт в public: роль заводится один раз на всю группу
    # (спека стадии 2, §1.3), поэтому в TENANT_APPS её НЕТ.
    "apps.access",
```

`apps/core/models.py`:

```python
KNOWN_SERVICES = ["users", "hr", "tasks", "approvals", "cms",
                  "media", "mail", "messenger", "conference", "contracts",
                  "signoff", "companies", "access"]
```

`apps/core/services.py`:

```python
CORE_MODULES = frozenset({"users", "companies", "core", "hr", "messenger",
                          "media", "cms", "access"})
```

`htqweb/middleware/service_gate.py`, в `PREFIX_TO_SERVICE`:

```python
    "/api/access/": "access",
```

- [ ] **Шаг 5: Прогнать тесты**

Run: `../.venv/Scripts/python.exe -m pytest apps/access apps/core/tests/test_app_isolation.py -q`
Expected: PASS

- [ ] **Шаг 6: Коммит**

```bash
git add backend/apps/access backend/htqweb/settings/base.py backend/apps/core/models.py backend/apps/core/services.py backend/htqweb/middleware/service_gate.py
git commit -m "feat(access): скелет аппки доступа и регистрация в реестре модулей"
```

---

## Задача 2: Модели и миграция (спека A2)

**Files:**
- Create: `backend/apps/access/models.py`, `backend/apps/access/migrations/0001_initial.py`
  (генерируется), `backend/apps/access/tests/test_models.py`
- Create: `backend/apps/access/admin.py`

**Interfaces:**
- Produces: `Role(code, title, is_system)`, `RoleModulePermission(role, module, level)`,
  `PositionRole(company_slug, position_id, role)`,
  `RoleAssignment(company_slug, user_id, role, scope_kind, scope_id)`,
  `Level` (TextChoices), `LEVEL_ORDER: dict[str, int]`.

- [ ] **Шаг 1: Написать падающие тесты**

`backend/apps/access/tests/test_models.py`:

```python
import pytest
from django.db import IntegrityError

from apps.access.models import Level, Role, RoleAssignment, ScopeKind


@pytest.mark.django_db
def test_role_code_is_unique_platform_wide():
    """Каталог один на все компании — код уникален глобально (спека §4.1)."""
    Role.objects.create(code="hr-admin", title="Кадровик")
    with pytest.raises(IntegrityError):
        Role.objects.create(code="hr-admin", title="Дубль")


@pytest.mark.django_db
def test_company_scope_forbids_scope_id():
    role = Role.objects.create(code="r1", title="Роль")
    with pytest.raises(IntegrityError):
        RoleAssignment.objects.create(
            company_slug="htq-kz", user_id=1, role=role,
            scope_kind=ScopeKind.COMPANY, scope_id=7,
        )


@pytest.mark.django_db
def test_department_scope_requires_scope_id():
    role = Role.objects.create(code="r2", title="Роль")
    with pytest.raises(IntegrityError):
        RoleAssignment.objects.create(
            company_slug="htq-kz", user_id=1, role=role,
            scope_kind=ScopeKind.DEPARTMENT, scope_id=None,
        )


@pytest.mark.django_db
def test_same_assignment_twice_is_rejected():
    """NULL в scope_id не должен обходить уникальность (частичные индексы)."""
    role = Role.objects.create(code="r3", title="Роль")
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=1, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    with pytest.raises(IntegrityError):
        RoleAssignment.objects.create(company_slug="htq-kz", user_id=1, role=role,
                                      scope_kind=ScopeKind.COMPANY, scope_id=None)


def test_level_order_is_total():
    from apps.access.models import LEVEL_ORDER
    assert [LEVEL_ORDER[v] for v in (Level.NONE, Level.READ, Level.WRITE, Level.ADMIN)] == [0, 1, 2, 3]
```

- [ ] **Шаг 2: Прогнать — обязан упасть**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_models.py -q`
Expected: FAIL, `ImportError: cannot import name 'Role'`

- [ ] **Шаг 3: Написать модели**

`backend/apps/access/models.py`:

```python
"""Модель доступа: глобальный каталог ролей и его привязки к компаниям.

Все таблицы аппки живут в схеме ``public`` — роль заводится один раз на всю
группу (спека стадии 2, §1.3), поэтому ``apps.access`` НЕ входит в
``settings.TENANT_APPS``.

Компания хранится СЛАГОМ, а не внешним ключом: межаппных ForeignKey у
платформы нет (тот же инвариант, по которому ``hr.Employee.user_id`` — обычный
int). Слаг, а не id, потому что разрешение прав получает из контекста запроса
именно слаг (``htqweb.tenancy.context.current_company``) — ссылка по id стоила
бы лишнего запроса в реестр на каждой проверке прав.
"""

from django.db import models


class Level(models.TextChoices):
    NONE = "none", "Нет доступа"
    READ = "read", "Чтение"
    WRITE = "write", "Запись"
    ADMIN = "admin", "Администрирование"


# Порядок сравнения уровней. Ровно один источник истины на бэкенде; фронт
# держит свою копию в src/api/access.ts — расхождение ловится тестом B.
LEVEL_ORDER = {Level.NONE: 0, Level.READ: 1, Level.WRITE: 2, Level.ADMIN: 3}


class ScopeKind(models.TextChoices):
    COMPANY = "company", "Компания"
    DEPARTMENT = "department", "Отдел"
    SITE = "site", "Объект"


class Role(models.Model):
    """Набор прав, действующий во всех компаниях группы (правило 1 и 3)."""

    code = models.SlugField(max_length=64, unique=True)
    title = models.CharField(max_length=255)
    # Служебные роли сидируются и не удаляются через API.
    is_system = models.BooleanField(default=False, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Роль"
        verbose_name_plural = "Роли"
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class RoleModulePermission(models.Model):
    """Уровень роли на один модуль. Отсутствие строки означает ``none``."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    # Значение из apps.core.models.KNOWN_SERVICES. Не choices: реестр модулей
    # меняется добавлением аппки, и миграция на каждое такое добавление
    # означала бы, что список живёт в двух местах.
    module = models.CharField(max_length=32)
    level = models.CharField(max_length=8, choices=Level.choices)

    class Meta:
        verbose_name = "Право роли"
        verbose_name_plural = "Права ролей"
        constraints = [
            models.UniqueConstraint(fields=["role", "module"], name="uniq_role_module"),
        ]


class PositionRole(models.Model):
    """Роль, выданная должности компании — штатный путь (правило 2)."""

    company_slug = models.CharField(max_length=32, db_index=True)
    # Мягкая ссылка в apps.hr: должность лежит в схеме компании, FK поперёк
    # схем невозможен. Тот же приём, что у apps.signoff в маршрутах.
    position_id = models.IntegerField()
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="position_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Роль должности"
        verbose_name_plural = "Роли должностей"
        constraints = [
            models.UniqueConstraint(
                fields=["company_slug", "position_id", "role"],
                name="uniq_position_role",
            ),
        ]
        indexes = [models.Index(fields=["company_slug", "position_id"])]


class RoleAssignment(models.Model):
    """Личное назначение — исключение из штатного пути (спека §1.2)."""

    company_slug = models.CharField(max_length=32, db_index=True)
    user_id = models.IntegerField()
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="assignments")
    scope_kind = models.CharField(max_length=16, choices=ScopeKind.choices)
    scope_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Личное назначение роли"
        verbose_name_plural = "Личные назначения ролей"
        constraints = [
            # Два ЧАСТИЧНЫХ индекса вместо одного составного: в Postgres NULL
            # не равен NULL, поэтому обычная уникальность по scope_id
            # пропустила бы сколько угодно копий назначения на всю компанию.
            models.UniqueConstraint(
                fields=["company_slug", "user_id", "role", "scope_kind"],
                condition=models.Q(scope_id__isnull=True),
                name="uniq_assignment_unscoped",
            ),
            models.UniqueConstraint(
                fields=["company_slug", "user_id", "role", "scope_kind", "scope_id"],
                condition=models.Q(scope_id__isnull=False),
                name="uniq_assignment_scoped",
            ),
            # Область «компания» не имеет идентификатора, остальные — обязаны.
            # Проверка в БД, а не только в схеме запроса: django-admin и ORM
            # мимо вьюхи — такие же входы (тот же довод, что у циклов ролей).
            models.CheckConstraint(
                condition=(
                    models.Q(scope_kind=ScopeKind.COMPANY, scope_id__isnull=True)
                    | (~models.Q(scope_kind=ScopeKind.COMPANY) & models.Q(scope_id__isnull=False))
                ),
                name="assignment_scope_id_matches_kind",
            ),
        ]
        indexes = [models.Index(fields=["company_slug", "user_id"])]
```

- [ ] **Шаг 4: Сгенерировать и применить миграцию**

```bash
../.venv/Scripts/python.exe manage.py makemigrations access
```

Ожидается один файл `0001_initial.py`. Прочитать его глазами: в нём не должно
быть ни одного `ForeignKey` на `companies` или `hr`.

- [ ] **Шаг 5: Прогнать тесты**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_models.py -q`
Expected: PASS (5 passed)

- [ ] **Шаг 6: Админка**

`backend/apps/access/admin.py`:

```python
from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import PositionRole, Role, RoleAssignment, RoleModulePermission


class PermissionInline(admin.TabularInline):
    model = RoleModulePermission
    extra = 0


@admin.register(Role)
class RoleAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("code", "title", "is_system")
    search_fields = ("code", "title")
    inlines = [PermissionInline]


@admin.register(PositionRole)
class PositionRoleAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("company_slug", "position_id", "role")
    list_filter = ("company_slug",)


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("company_slug", "user_id", "role", "scope_kind", "scope_id")
    list_filter = ("company_slug", "scope_kind")
```

- [ ] **Шаг 7: Коммит**

```bash
git add backend/apps/access
git commit -m "feat(access): модели каталога ролей, привязок и назначений"
```

---

## Задача 3: Шов в `apps.hr.interface` (спека A5)

**Files:**
- Modify: `backend/apps/hr/interface.py:38-56`
- Test: `backend/apps/hr/tests/test_interface.py` (дописать тест)

**Interfaces:**
- Produces: `get_employee_brief(user_id) -> dict | None` с новым ключом
  `position_id: int`. Существующие ключи (`id`, `full_name`, `department_id`,
  `position_title`, `status`) **не меняются**.

- [ ] **Шаг 1: Тест на новый ключ**

Дописать в `backend/apps/hr/tests/test_interface.py`:

```python
@pytest.mark.django_db
def test_employee_brief_carries_position_id(hr_employee):
    """apps.access ключуется на должности; ей нужен id, а не заголовок."""
    brief = interface.get_employee_brief(hr_employee.user_id)
    assert brief["position_id"] == hr_employee.position_id
    # Аддитивность: старые ключи на месте — их читает действующий фронт.
    assert {"id", "full_name", "department_id", "position_title", "status"} <= set(brief)
```

- [ ] **Шаг 2: Прогнать — обязан упасть**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_interface.py -q -k position_id`
Expected: FAIL, `KeyError: 'position_id'`

- [ ] **Шаг 3: Добавить поле**

`backend/apps/hr/interface.py`, в `get_employee_brief`: в `.values(...)`
добавить `"position_id"`, в возвращаемый словарь — строку

```python
        "position_id": row["position_id"],
```

- [ ] **Шаг 4: Прогнать тесты HR целиком**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr -q`
Expected: PASS

- [ ] **Шаг 5: Коммит**

```bash
git add backend/apps/hr/interface.py backend/apps/hr/tests/test_interface.py
git commit -m "feat(hr): position_id в get_employee_brief — шов для apps.access"
```

---

## Задача 4: Разрешение прав (спека A4)

**Files:**
- Create: `backend/apps/access/services/resolve.py`,
  `backend/apps/access/tests/test_resolve.py`
- Modify: `backend/apps/access/interface.py`

**Interfaces:**
- Consumes: `apps.hr.interface.get_employee_brief` (задача 3).
- Produces:
  - `permission_level(user, module: str, company: str | None) -> str`
  - `permissions_for(user, company: str | None) -> dict[str, dict]` —
    `{module: {"level": str, "scope": {"kind": str, "id": int | None}}}`,
    модули со `none` не включаются.

- [ ] **Шаг 1: Написать падающие тесты по всем пяти веткам**

`backend/apps/access/tests/test_resolve.py`:

```python
import pytest

from apps.access.models import Level, PositionRole, Role, RoleAssignment, RoleModulePermission, ScopeKind
from apps.access.services import resolve


@pytest.mark.django_db
def test_superuser_gets_admin_everywhere(superuser):
    assert resolve.permission_level(superuser, "hr", "htq-kz") == Level.ADMIN


@pytest.mark.django_db
def test_no_company_context_means_no_rights(user):
    """Подстановка «по умолчанию» запрещена — спека §1.5, пункт 2."""
    assert resolve.permission_level(user, "hr", None) == Level.NONE
    assert resolve.permissions_for(user, None) == {}


@pytest.mark.django_db
def test_position_roles_grant_rights(user, employee_with_position):
    role = Role.objects.create(code="hr-read", title="Чтение кадров")
    RoleModulePermission.objects.create(role=role, module="hr", level=Level.READ)
    PositionRole.objects.create(company_slug="htq-kz",
                                position_id=employee_with_position.position_id, role=role)
    assert resolve.permission_level(user, "hr", "htq-kz") == Level.READ


@pytest.mark.django_db
def test_personal_assignment_grants_rights_without_employee(user):
    """Директор холдинга без кадровой карточки — спека §1.2."""
    role = Role.objects.create(code="boss", title="Директор")
    RoleModulePermission.objects.create(role=role, module="tasks", level=Level.ADMIN)
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    assert resolve.permission_level(user, "tasks", "htq-kz") == Level.ADMIN


@pytest.mark.django_db
def test_max_level_wins_and_widest_scope_of_that_level(user, employee_with_position):
    """По модулю — максимум; область — самая широкая из давших этот уровень."""
    narrow = Role.objects.create(code="narrow", title="Узкая")
    RoleModulePermission.objects.create(role=narrow, module="hr", level=Level.WRITE)
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=user.id, role=narrow,
                                  scope_kind=ScopeKind.DEPARTMENT, scope_id=3)
    wide = Role.objects.create(code="wide", title="Широкая")
    RoleModulePermission.objects.create(role=wide, module="hr", level=Level.WRITE)
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=user.id, role=wide,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    perms = resolve.permissions_for(user, "htq-kz")
    assert perms["hr"] == {"level": "write", "scope": {"kind": "company", "id": None}}


@pytest.mark.django_db
def test_other_company_rights_are_invisible(user):
    """Изоляция держится фильтром по компании — спека §1.3, риск 3."""
    role = Role.objects.create(code="foreign", title="Чужая")
    RoleModulePermission.objects.create(role=role, module="hr", level=Level.ADMIN)
    RoleAssignment.objects.create(company_slug="kurly-kg", user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    assert resolve.permission_level(user, "hr", "htq-kz") == Level.NONE


@pytest.mark.django_db
def test_modules_with_none_are_absent(user):
    assert "mail" not in resolve.permissions_for(user, "htq-kz")


@pytest.mark.django_db
def test_disabled_hr_leaves_personal_assignments_and_logs_fallback(user, service_off, caplog):
    """Выключенный кадровый модуль не должен молча обнулять права."""
    role = Role.objects.create(code="own", title="Личная")
    RoleModulePermission.objects.create(role=role, module="tasks", level=Level.READ)
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    with service_off("hr"):
        assert resolve.permission_level(user, "tasks", "htq-kz") == Level.READ
    assert "FALLBACK" in caplog.text
    assert "access.resolve.hr_unavailable" in caplog.text
```

⚠️ Фикстуры `user`, `superuser`, `employee_with_position`, `service_off`
объявляются в `backend/apps/access/tests/conftest.py` этой же задачей. Тест
подмены (последний) идёт в прод-режиме подмен — используйте существующую
фикстуру прод-режима из `backend/conftest.py`, иначе `strict` уронит его
`FallbackNotAllowed`.

- [ ] **Шаг 2: Прогнать — обязан упасть**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_resolve.py -q`
Expected: FAIL, `ModuleNotFoundError: apps.access.services.resolve`

- [ ] **Шаг 3: Написать разрешение**

`backend/apps/access/services/resolve.py`:

```python
"""Разрешение прав — спека стадии 2, §1.5.

Порядок ветвления зафиксирован спекой и повторён здесь дословно, потому что
это единственное место платформы, где «нет ответа» и «нет прав» обязаны
совпадать: любая подстановка по умолчанию тихо расширяет доступ.
"""

from __future__ import annotations

from apps.access.models import (
    LEVEL_ORDER,
    Level,
    PositionRole,
    RoleAssignment,
    RoleModulePermission,
    ScopeKind,
)
from htqweb.fallback import fallback

# Чем шире область, тем больше число: сравниваем так же, как уровни.
_SCOPE_WIDTH = {ScopeKind.SITE: 0, ScopeKind.DEPARTMENT: 1, ScopeKind.COMPANY: 2}


def _position_role_ids(user, company: str) -> list[int]:
    """Роли штатной должности пользователя. Пусто, если карточки нет."""
    try:
        from apps.hr import interface as hr

        brief = hr.get_employee_brief(user.id)
    except Exception as exc:
        # Кадровый модуль выключен или недоступен: должностные роли не
        # прочитать. Это ПОДМЕНА (права считаются по неполным данным), и она
        # обязана быть видна — иначе выключенный hr снимет доступ у всей
        # компании, а искать будут в правах.
        fallback("access.resolve.hr_unavailable", None,
                 reason="кадровый модуль недоступен, роли должности не учтены",
                 exc=exc, expected=True)
        return []
    if brief is None or brief.get("position_id") is None:
        return []
    return list(
        PositionRole.objects.filter(
            company_slug=company, position_id=brief["position_id"],
        ).values_list("role_id", flat=True)
    )


def permissions_for(user, company: str | None) -> dict[str, dict]:
    if getattr(user, "is_superuser", False):
        return {
            module: {"level": Level.ADMIN, "scope": {"kind": ScopeKind.COMPANY, "id": None}}
            for module in _known_modules()
        }
    if company is None:
        return {}

    # (role_id -> область, с которой роль пришла). Должностная роль всегда
    # действует на всю компанию: область сужается только личным назначением.
    scopes: dict[int, tuple[str, int | None]] = {
        role_id: (ScopeKind.COMPANY, None)
        for role_id in _position_role_ids(user, company)
    }
    for row in RoleAssignment.objects.filter(company_slug=company, user_id=user.id):
        current = scopes.get(row.role_id)
        candidate = (row.scope_kind, row.scope_id)
        if current is None or _SCOPE_WIDTH[candidate[0]] > _SCOPE_WIDTH[current[0]]:
            scopes[row.role_id] = candidate
    if not scopes:
        return {}

    result: dict[str, dict] = {}
    rows = RoleModulePermission.objects.filter(role_id__in=scopes).values(
        "role_id", "module", "level")
    for row in rows:
        if row["level"] == Level.NONE:
            continue
        kind, scope_id = scopes[row["role_id"]]
        best = result.get(row["module"])
        if best is None or LEVEL_ORDER[row["level"]] > LEVEL_ORDER[best["level"]]:
            result[row["module"]] = {"level": row["level"],
                                     "scope": {"kind": kind, "id": scope_id}}
        elif (LEVEL_ORDER[row["level"]] == LEVEL_ORDER[best["level"]]
              and _SCOPE_WIDTH[kind] > _SCOPE_WIDTH[best["scope"]["kind"]]):
            best["scope"] = {"kind": kind, "id": scope_id}
    return result


def permission_level(user, module: str, company: str | None) -> str:
    entry = permissions_for(user, company).get(module)
    return entry["level"] if entry else Level.NONE


def _known_modules() -> list[str]:
    from apps.core.models import KNOWN_SERVICES

    return list(KNOWN_SERVICES)
```

- [ ] **Шаг 4: Опубликовать через интерфейс**

`backend/apps/access/interface.py`:

```python
"""Публичный API аппки access для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к правам. Прямой
импорт ``apps.access.models`` / ``.services`` запрещён и ловится
``apps/core/tests/test_app_isolation.py``.
"""

from __future__ import annotations

from apps.access.services import hierarchy, resolve
from apps.core.services import require_service


def permission_level(user, module: str, company: str | None) -> str:
    require_service("access")
    return resolve.permission_level(user, module, company)


def permissions_for(user, company: str | None) -> dict[str, dict]:
    require_service("access")
    return resolve.permissions_for(user, company)


def subordinate_companies(user, company: str | None) -> list[str]:
    require_service("access")
    return hierarchy.subordinate_companies(user, company)


__all__ = ["permission_level", "permissions_for", "subordinate_companies"]
```

⚠️ `hierarchy` появляется в задаче 5 — до неё импорт держите закомментированным
либо выполните задачу 5 перед этим шагом.

- [ ] **Шаг 5: Прогнать тесты**

Run: `../.venv/Scripts/python.exe -m pytest apps/access -q`
Expected: PASS

- [ ] **Шаг 6: Коммит**

```bash
git add backend/apps/access
git commit -m "feat(access): разрешение прав по должности и личным назначениям"
```

---

## Задача 5: Внешняя иерархия (спека A3)

**Files:**
- Create: `backend/apps/access/services/hierarchy.py`,
  `backend/apps/access/tests/test_hierarchy.py`

**Interfaces:**
- Consumes: `apps.companies.interface.get_company(slug) -> dict | None`,
  `active_company_slugs() -> list[str]`.
- Produces: `subordinate_companies(user, company: str | None) -> list[str]` —
  слаги компаний ниже по дереву владения; пусто у не-руководителя.

- [ ] **Шаг 1: Тесты**

`backend/apps/access/tests/test_hierarchy.py`:

```python
import pytest

from apps.access.services import hierarchy


@pytest.mark.django_db
def test_non_manager_has_no_subordinate_companies(user, company_tree):
    assert hierarchy.subordinate_companies(user, "htq-holding") == []


@pytest.mark.django_db
def test_manager_gets_whole_subtree(manager_user, company_tree):
    """Холдинг → региональная → сервисная: начальник видит обе нижние."""
    assert sorted(hierarchy.subordinate_companies(manager_user, "htq-holding")) == [
        "htq-kz", "kurly-kg",
    ]


@pytest.mark.django_db
def test_manager_with_external_hierarchy_off_gets_nothing(manager_user_opted_out, company_tree):
    assert hierarchy.subordinate_companies(manager_user_opted_out, "htq-holding") == []


@pytest.mark.django_db
def test_cycle_in_company_tree_does_not_hang(manager_user, cyclic_company_tree):
    """Цикл, заведённый мимо приложения, не должен вешать разрешение прав."""
    assert hierarchy.subordinate_companies(manager_user, "a") == ["b"]
```

- [ ] **Шаг 2: Прогнать — обязан упасть**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_hierarchy.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Шаг 3: Реализовать**

`backend/apps/access/services/hierarchy.py`:

```python
"""Внешняя иерархия — спека стадии 2, §1.4.

Дерево подчинения НЕ хранится: оно выводится из дерева владения компаниями.
Две таблицы с ответом на вопрос «кто чей начальник» разъехались бы на первой
же реорганизации, причём молча.
"""

from __future__ import annotations

from htqweb.fallback import fallback


def _is_external_manager(user, company: str) -> bool:
    """Руководящая ли должность у пользователя и включена ли внешняя иерархия.

    Поля ``is_manager`` и ``external_hierarchy`` заводит переработка HR
    (спека §1.6). До их появления ответ всегда False — и это корректное
    состояние «ни одна должность пока не помечена руководящей», а не сбой.
    """
    try:
        from apps.hr import interface as hr

        brief = hr.get_employee_brief(user.id)
    except Exception as exc:
        fallback("access.hierarchy.hr_unavailable", None,
                 reason="кадровый модуль недоступен, руководителя не определить",
                 exc=exc, expected=True)
        return False
    if brief is None:
        return False
    return bool(brief.get("is_manager")) and brief.get("external_hierarchy", "none") == "inherit"


def subordinate_companies(user, company: str | None) -> list[str]:
    if company is None or not _is_external_manager(user, company):
        return []

    from apps.companies import interface as companies

    parents: dict[str, str | None] = {}
    for slug in companies.active_company_slugs():
        row = companies.get_company(slug)
        parents[slug] = row.get("parent_slug") if row else None

    below: list[str] = []
    for slug in parents:
        if slug == company:
            continue
        seen = {slug}
        cursor = parents.get(slug)
        # Ограничение по числу пройденных узлов — защита от цикла, заведённого
        # в обход приложения: PROTECT на self-FK его не исключает.
        while cursor is not None and cursor not in seen:
            if cursor == company:
                below.append(slug)
                break
            seen.add(cursor)
            cursor = parents.get(cursor)
    return sorted(below)
```

⚠️ `companies.get_company` обязан отдавать `parent_slug`. Если его в
`_serialize` нет — добавить там (аддитивно) и покрыть тестом в
`apps/companies/tests/test_interface.py`.

- [ ] **Шаг 4: Прогнать тесты**

Run: `../.venv/Scripts/python.exe -m pytest apps/access -q`
Expected: PASS

- [ ] **Шаг 5: Коммит**

```bash
git add backend/apps/access backend/apps/companies
git commit -m "feat(access): подчинённые компании из дерева владения"
```

---

## Задача 6: Сервисы каталога и назначений (спека A2/A6, доменная часть)

**Files:**
- Create: `backend/apps/access/services/catalog.py`,
  `backend/apps/access/services/assignment.py`,
  `backend/apps/access/tests/test_catalog.py`,
  `backend/apps/access/tests/test_assignment.py`

**Interfaces:**
- Produces:
  - `catalog.create_role(code, title) -> Role` (бросает `RoleConflict` на дубле)
  - `catalog.delete_role(role_id) -> None` (бросает `RoleInUse(positions, users)`,
    `RoleIsSystem`)
  - `catalog.set_permissions(role_id, items: list[dict]) -> None` — замена целиком
  - `assignment.set_position_roles(company, position_id, role_ids) -> None`
  - `assignment.set_user_assignments(company, user_id, items) -> None`
  - Исключения: `RoleConflict`, `RoleInUse`, `RoleIsSystem`, `UnknownRole`,
    `ScopeInvalid` — все из `apps.access.services.errors`.

- [ ] **Шаг 1: Тесты каталога**

```python
import pytest

from apps.access.models import Level, PositionRole, Role, RoleModulePermission
from apps.access.services import catalog
from apps.access.services.errors import RoleInUse, RoleIsSystem


@pytest.mark.django_db
def test_delete_refuses_when_role_is_in_use():
    role = Role.objects.create(code="used", title="Занятая")
    PositionRole.objects.create(company_slug="htq-kz", position_id=1, role=role)
    with pytest.raises(RoleInUse) as exc:
        catalog.delete_role(role.id)
    assert exc.value.positions == 1
    assert exc.value.users == 0


@pytest.mark.django_db
def test_delete_refuses_system_role():
    role = Role.objects.create(code="sys", title="Системная", is_system=True)
    with pytest.raises(RoleIsSystem):
        catalog.delete_role(role.id)


@pytest.mark.django_db
def test_set_permissions_replaces_whole_set():
    """Отсутствующий в списке модуль становится none — спека §4.2."""
    role = Role.objects.create(code="r", title="Роль")
    catalog.set_permissions(role.id, [{"module": "hr", "level": Level.WRITE},
                                      {"module": "tasks", "level": Level.READ}])
    catalog.set_permissions(role.id, [{"module": "hr", "level": Level.READ}])
    rows = {p.module: p.level for p in RoleModulePermission.objects.filter(role=role)}
    assert rows == {"hr": Level.READ}


@pytest.mark.django_db
def test_unknown_module_is_rejected():
    role = Role.objects.create(code="r2", title="Роль")
    with pytest.raises(ValueError):
        catalog.set_permissions(role.id, [{"module": "нет-такого", "level": Level.READ}])
```

- [ ] **Шаг 2: Тесты назначений**

```python
import pytest

from apps.access.models import PositionRole, Role, RoleAssignment, ScopeKind
from apps.access.services import assignment
from apps.access.services.errors import ScopeInvalid, UnknownRole


@pytest.mark.django_db
def test_set_position_roles_replaces_whole_set():
    a = Role.objects.create(code="a", title="A")
    b = Role.objects.create(code="b", title="B")
    assignment.set_position_roles("htq-kz", 5, [a.id, b.id])
    assignment.set_position_roles("htq-kz", 5, [b.id])
    assert list(PositionRole.objects.filter(company_slug="htq-kz", position_id=5)
               .values_list("role_id", flat=True)) == [b.id]


@pytest.mark.django_db
def test_position_roles_of_other_company_are_untouched():
    a = Role.objects.create(code="a", title="A")
    assignment.set_position_roles("kurly-kg", 5, [a.id])
    assignment.set_position_roles("htq-kz", 5, [])
    assert PositionRole.objects.filter(company_slug="kurly-kg", position_id=5).count() == 1


@pytest.mark.django_db
def test_unknown_role_is_rejected():
    with pytest.raises(UnknownRole):
        assignment.set_position_roles("htq-kz", 5, [99999])


@pytest.mark.django_db
def test_company_scope_with_scope_id_is_rejected():
    role = Role.objects.create(code="r", title="R")
    with pytest.raises(ScopeInvalid):
        assignment.set_user_assignments("htq-kz", 1, [
            {"role_id": role.id, "scope_kind": ScopeKind.COMPANY, "scope_id": 3}])


@pytest.mark.django_db
def test_department_scope_without_scope_id_is_rejected():
    role = Role.objects.create(code="r2", title="R")
    with pytest.raises(ScopeInvalid):
        assignment.set_user_assignments("htq-kz", 1, [
            {"role_id": role.id, "scope_kind": ScopeKind.DEPARTMENT, "scope_id": None}])
```

- [ ] **Шаг 3: Прогнать — обязаны упасть**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_catalog.py apps/access/tests/test_assignment.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Шаг 4: Реализовать сервисы**

`backend/apps/access/services/errors.py`:

```python
class AccessError(Exception):
    """Общий предок доменных отказов аппки."""


class RoleConflict(AccessError):
    """Код роли занят."""


class RoleIsSystem(AccessError):
    """Служебную роль удалять нельзя."""


class RoleInUse(AccessError):
    def __init__(self, positions: int, users: int):
        self.positions = positions
        self.users = users
        super().__init__(f"роль назначена: должностей {positions}, пользователей {users}")


class UnknownRole(AccessError):
    """В наборе есть несуществующая роль."""


class ScopeInvalid(AccessError):
    """scope_id не соответствует scope_kind."""
```

`backend/apps/access/services/catalog.py`:

```python
"""Каталог ролей — операции платформенного уровня (спека §4.1, §4.2)."""

from __future__ import annotations

from django.db import IntegrityError, transaction

from apps.access.models import Role, RoleModulePermission
from apps.access.services.errors import RoleConflict, RoleInUse, RoleIsSystem


def create_role(code: str, title: str) -> Role:
    try:
        return Role.objects.create(code=code, title=title)
    except IntegrityError as exc:
        raise RoleConflict(code) from exc


def rename_role(role_id: int, title: str) -> Role:
    role = Role.objects.get(id=role_id)
    role.title = title
    role.save(update_fields=["title", "updated_at"])
    return role


def delete_role(role_id: int) -> None:
    """Отказ вместо тихого снятия прав у неизвестного числа людей."""
    role = Role.objects.get(id=role_id)
    if role.is_system:
        raise RoleIsSystem(role.code)
    positions = role.position_links.count()
    users = role.assignments.count()
    if positions or users:
        raise RoleInUse(positions=positions, users=users)
    role.delete()


def set_permissions(role_id: int, items: list[dict]) -> None:
    """Замена набора ЦЕЛИКОМ: отсутствующий модуль становится none.

    Частичная правка означала бы, что «забыли прислать модуль» тихо
    равносильно «оставить как было» — спека §4.2.
    """
    from apps.core.models import KNOWN_SERVICES

    unknown = [i["module"] for i in items if i["module"] not in KNOWN_SERVICES]
    if unknown:
        raise ValueError(f"нет таких модулей: {unknown}")
    with transaction.atomic():
        RoleModulePermission.objects.filter(role_id=role_id).delete()
        RoleModulePermission.objects.bulk_create([
            RoleModulePermission(role_id=role_id, module=i["module"], level=i["level"])
            for i in items if i["level"] != "none"
        ])
```

`assignment.py` — `set_position_roles(company, position_id, role_ids)` и
`set_user_assignments(company, user_id, items)` устроены так же: проверка
существования ролей (`UnknownRole`), проверка соответствия `scope_id` и
`scope_kind` (`ScopeInvalid`), затем `delete()` + `bulk_create()` в одной
транзакции. ⚠️ Каждый `filter()` и `delete()` обязан нести `company_slug=` —
без него замена набора в одной компании сотрёт назначения соседней (риск 3
спеки; ловится сторожем задачи 10).

- [ ] **Шаг 5: Прогнать тесты**

Run: `../.venv/Scripts/python.exe -m pytest apps/access -q`
Expected: PASS

- [ ] **Шаг 6: Коммит**

```bash
git add backend/apps/access
git commit -m "feat(access): сервисы каталога ролей и назначений"
```

---

## Задача 7: API по контракту §4 (спека A6) — ТОЧКА СИНХРОНИЗАЦИИ

**Files:**
- Create: `backend/apps/access/schemas.py`, `backend/apps/access/tests/test_api.py`
- Modify: `backend/apps/access/views.py`, `backend/apps/access/urls.py`

**Interfaces:**
- Produces: ручки §4.1–§4.4 спеки в обоих написаниях пути.

- [ ] **Шаг 1: Тесты API по кодам ответов контракта**

Обязательный минимум (каждый пункт — отдельный тест):
`403` на `POST roles` не суперпользователем; `409 in_use` на удалении
назначенной роли; `409` на `is_system`; `422` на дубль `code`; `404` на
`PUT positions/<id>/roles` для чужой компании; `422` на несуществующую роль;
`422` на `scope_id` при `company`; оба написания пути (`roles` и `roles/`)
отвечают одинаково.

Пример одного:

```python
@pytest.mark.django_db
def test_delete_used_role_returns_409_with_counts(admin_client, used_role):
    resp = admin_client.delete(f"/api/access/v1/roles/{used_role.id}")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "in_use", "positions": 1, "users": 0}
```

- [ ] **Шаг 2: Прогнать — обязаны упасть**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_api.py -q`
Expected: FAIL (404/405 вместо ожидаемых кодов)

- [ ] **Шаг 3: Схемы**

`backend/apps/access/schemas.py` — Pydantic-модели `RoleIn`, `RolePatchIn`,
`PermissionItem` (валидирует `module` по `KNOWN_SERVICES` и `level` по `Level`),
`PositionRolesIn` (`role_ids: list[int]`), `AssignmentItem`.

- [ ] **Шаг 4: Вьюхи**

CBV на `htqweb.http.ApiView`, `api_view` навешивается **пометодно** через
`method_decorator` — режим авторизации у методов разный: `GET` — `auth="jwt"`,
мутации каталога — `admin=True`. Доменные исключения переводятся в коды:
`RoleConflict` → 422, `RoleInUse` → 409 с телом из счётчиков, `RoleIsSystem`
→ 409, `UnknownRole`/`ScopeInvalid` → 422.

Компания берётся из контекста запроса
(`htqweb.tenancy.context.current_company_or_none()`), а не из тела и не из
query — иначе слаг компании становится параметром, который можно подставить.

- [ ] **Шаг 5: Маршруты**

В `urls.py` — все пути §4 в обоих написаниях; вложенные (`roles/<id>/permissions`,
`positions/<id>/roles`) регистрируются **раньше** одиночных.

- [ ] **Шаг 6: Прогнать тесты**

Run: `../.venv/Scripts/python.exe -m pytest apps/access -q`
Expected: PASS

- [ ] **Шаг 7: Коммит и сигнал исполнителю B**

```bash
git add backend/apps/access
git commit -m "feat(access): API каталога ролей, ролей должностей и назначений"
```

**Сообщить исполнителю B: контракт §4 поднят, фикстуру можно менять на живой
API.** Это единственная обязательная точка синхронизации плана.

---

## Задача 8: `/me` и карта прав в профиле (спека A7)

**Files:**
- Modify: `backend/apps/access/views.py`, `urls.py`,
  `backend/apps/users/services/profile_service.py`
- Test: `backend/apps/access/tests/test_me.py`

**Interfaces:**
- Produces: `GET /api/access/v1/me` по §4.5 и те же три ключа в ответе
  `users/v1/profile/me`.

- [ ] **Шаг 1: Тесты**

```python
@pytest.mark.django_db
def test_me_without_company_is_not_an_error(client_jwt):
    resp = client_jwt.get("/api/access/v1/me")
    assert resp.status_code == 200
    assert resp.json() == {"company": None, "permissions": {}, "subordinate_companies": []}


@pytest.mark.django_db
def test_profile_carries_the_same_permission_map(client_jwt, company_context):
    me = client_jwt.get("/api/access/v1/me").json()
    profile = client_jwt.get("/api/users/v1/profile/me").json()
    assert profile["permissions"] == me["permissions"]


@pytest.mark.django_db
def test_roles_for_still_returns_three_values(user):
    """Снимать их до задачи B4 значит уронить вход — спека A7."""
    from apps.users.services.profile_service import roles_for
    assert roles_for(user) == ["user"]
```

- [ ] **Шаг 2: Прогнать — обязаны упасть**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_me.py -q`

- [ ] **Шаг 3: Реализовать**

Вьюха `MeView` (`auth="jwt"`) вызывает `permissions_for` и
`subordinate_companies`. В `profile_service.build_response` добавляются ключи
`permissions`, `subordinate_companies`, `company` — **ленивым импортом
`apps.access.interface` внутри функции** (аппки не импортируют друг друга на
уровне модуля). `roles_for` не трогается.

- [ ] **Шаг 4: Прогнать тесты**

Run: `../.venv/Scripts/python.exe -m pytest apps/access apps/users -q`
Expected: PASS

- [ ] **Шаг 5: Коммит**

```bash
git add backend/apps/access backend/apps/users
git commit -m "feat(access): ручка /me и карта прав в ответе профиля"
```

---

## Задача 9: Гейт в `api_view` (спека A8)

**Files:**
- Modify: `backend/htqweb/http.py:74-115`
- Test: `backend/apps/access/tests/test_gate.py`

**Interfaces:**
- Produces: `api_view(..., module="hr", level="write")`. Ни на одну
  существующую ручку в этой стадии **не навешивается**.

- [ ] **Шаг 1: Тесты**

```python
def test_gate_allows_equal_and_higher_level(...):
    """write пропускает write и admin, отвергает read и none — 403."""


def test_gate_without_module_changes_nothing(...):
    """Ручки без module= ведут себя ровно как раньше — регресс всего API."""


def test_gate_import_is_lazy():
    """apps.access сама декорирована api_view: импорт на уровне модуля даст цикл."""
    import htqweb.http as http
    assert "apps.access" not in "".join(
        l for l in open(http.__file__, encoding="utf-8").read().splitlines()
        if l.startswith(("import ", "from ")))
```

- [ ] **Шаг 2: Прогнать — обязаны упасть**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_gate.py -q`

- [ ] **Шаг 3: Реализовать**

В сигнатуру `api_view` добавляются `module: str | None = None`,
`level: str = "read"`. Проверка выполняется **после** аутентификации и сверки
компании, импорт `apps.access.interface` — внутри функции.

- [ ] **Шаг 4: Прогнать весь набор**

Run: `../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — гейт не должен изменить поведение ни одной существующей ручки.

- [ ] **Шаг 5: Коммит**

```bash
git add backend/htqweb/http.py backend/apps/access
git commit -m "feat(http): необязательный гейт module/level в api_view"
```

---

## Задача 10: Сторожевые тесты и метрики (спека A9)

**Files:**
- Create: `backend/apps/access/metrics.py`,
  `backend/apps/access/tests/test_guards.py`

- [ ] **Шаг 1: Сторож фильтра по компании**

Тест читает исходники `apps/access/services/*.py` и требует, чтобы **каждый**
`objects.filter(` над `PositionRole` и `RoleAssignment` содержал
`company_slug=`. Это не стилистика: таблицы лежат в `public`, `search_path` их
не изолирует, и забытый фильтр отдаёт права соседней компании, не выглядя
ошибкой (риск 3 спеки).

```python
import pathlib
import re

SERVICES = pathlib.Path(__file__).resolve().parents[1] / "services"
_QUERY = re.compile(r"(PositionRole|RoleAssignment)\.objects\.(filter|get|exclude)\(([^)]*)")


def test_every_tenant_query_carries_company():
    offenders = []
    for path in SERVICES.glob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _QUERY.search(line)
            if m and "company_slug" not in m.group(3):
                offenders.append(f"{path.name}:{lineno}")
    assert offenders == [], f"выборка без фильтра по компании: {offenders}"
```

- [ ] **Шаг 2: Метрики аппки**

`metrics.py` с `collect()` — число ролей, назначений и должностей с ролями.
Обнаруживается `apps/core/metrics.py` автоматически, межаппных импортов не
добавляет.

- [ ] **Шаг 3: Прогнать весь набор и изоляцию**

Run: `../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, в том числе `apps/core/tests/test_app_isolation.py`

- [ ] **Шаг 4: Коммит**

```bash
git add backend/apps/access
git commit -m "test(access): сторож фильтра по компании и метрики аппки"
```

---

## Определение готовности

- [ ] Весь набор зелёный: `../.venv/Scripts/python.exe -m pytest -q`
- [ ] `apps/core/tests/test_app_isolation.py` зелёный — `apps.access` доступна
      соседям только через `interface`, и сама импортирует соседей только так же
- [ ] `makemigrations --check --dry-run` не находит несгенерированных миграций
- [ ] Ни один файл `frontend/**` не изменён: `git diff --name-only origin/structure-refactoring -- frontend | wc -l` → `0`
- [ ] Исполнителю B отправлен сигнал из задачи 7
