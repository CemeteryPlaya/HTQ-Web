# Ядро мультикомпанейности — план реализации

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ СУБ-СКИЛЛ: используйте
> `superpowers:subagent-driven-development` (рекомендуется) или
> `superpowers:executing-plans` для выполнения задача-за-задачей. Шаги
> размечены чекбоксами (`- [ ]`).

**Цель:** ввести компанию как сквозное измерение платформы — отдельная схема
Postgres на компанию, выбор компании по поддомену, живое сводное чтение
холдинга через представления.

**Архитектура:** реестр компаний и всё, что не является предметными данными,
остаётся в схеме `public`. Аппки `hr`, `tasks`, `contracts`, `signoff`
переезжают в схему компании `co_<slug>`; их модели при этом **не меняются** —
разводит их `search_path`, выставляемый middleware на входе в запрос. Холдинг
читает схему `holding` с `UNION ALL`-представлениями поверх всех активных схем.

**Стек:** Django 5.2.7, Python 3.14, psycopg 3, Postgres, Celery, pytest-django,
React + Vite, nginx.

**Спека:** [docs/multi-company-tenancy-design.md](../multi-company-tenancy-design.md)

## Глобальные ограничения

- **Межаппный доступ только через `apps.<x>.interface`.** Прямой импорт
  `apps.<other>.models` / `.services` запрещён и ловится
  `apps/core/tests/test_app_isolation.py`. Исключение — `apps.core`.
- **Межаппных ForeignKey нет.** Ссылка на чужую аппку — обычный
  `IntegerField` (образец: `apps.hr.models.Employee.user_id`).
- **Никаких новых микросервисов.** Всё внутри существующего Django-бэкенда.
- **`APPEND_SLASH = False`** — в `urls.py` регистрируются оба написания пути,
  со слэшем и без.
- **Конверт ошибки всегда `{"detail": ...}`** (401/403/404/422/500/503).
- **Тесты идут против настоящего Postgres** на `:55432`. Поднять один раз:
  `docker compose -f docker-compose.test-local.yml up -d db`. **НЕ**
  `docker restart` — это роняет проброс порта.
- **Python-окружение:** `backend/.venv/Scripts/python.exe`, все команды
  запускаются из `backend/` (то есть `./.venv/Scripts/python.exe`).
  ⚠️ В репозитории есть ВТОРОЙ, корневой `.venv` с Django 6.0.2 — это НЕ
  окружение проекта. Запуск через него даёт 155 ошибок `ImproperlyConfigured`
  на этапе collection, что выглядит как сломанный набор тестов, а не как
  неверный интерпретатор. Проверка: `./.venv/Scripts/python.exe -c "import
  django; print(django.__version__)"` обязан напечатать `5.2.7`.
- **Режим подмен в тестах — `strict`** (`htqweb/settings/test.py`). Пустой
  контекст компании обязан падать, а не подставлять `public`.
- **Ветка `structure-refactoring`.** Новые ветки не создавать.
- **Имя схемы компании:** `co_` + slug с заменой `-` на `_`. Схема
  сводных представлений: `holding`. Список tenant-аппок:
  `("hr", "tasks", "contracts", "signoff")`.
- **Expand/contract обязателен**: миграция, удаляющая или переименовывающая
  столбец, не совмещается в одном шаге с кодом, переставшим его использовать.

---

## Структура файлов

**Создаются:**

| Файл | Ответственность |
|---|---|
| `backend/htqweb/tenancy/__init__.py` | реэкспорт публичных имён пакета |
| `backend/htqweb/tenancy/context.py` | `contextvar` текущей компании, имя схемы |
| `backend/htqweb/tenancy/db.py` | установка `search_path`, менеджер `use_company` |
| `backend/htqweb/tenancy/celery.py` | декоратор `@company_task` |
| `backend/htqweb/middleware/company_context.py` | резолв поддомена → контекст |
| `backend/apps/companies/models.py` | реестр компаний (5 моделей) |
| `backend/apps/companies/interface.py` | публичный API аппки для соседей |
| `backend/apps/companies/services/schema_service.py` | создание/удаление схемы |
| `backend/apps/companies/services/migration_service.py` | прогон миграций по схемам |
| `backend/apps/companies/services/holding_views.py` | сборка `UNION ALL`-представлений |
| `backend/apps/companies/management/commands/company_create.py` | создать компанию |
| `backend/apps/companies/management/commands/migrate_companies.py` | мигрировать схемы |
| `backend/apps/companies/management/commands/tenancy_bootstrap.py` | перенос боевых данных |
| `backend/apps/<domain>/holding.py` | список сводимых моделей аппки (4 файла) |

**Изменяются:**

| Файл | Что |
|---|---|
| `backend/htqweb/settings/base.py` | `INSTALLED_APPS`, `MIDDLEWARE`, `TENANT_APPS` |
| `backend/htqweb/authn/jwt.py:14-24` | claim `company` в `_base_claims` |
| `backend/htqweb/authn/payload.py:20-31` | поле `company` в `TokenPayload` |
| `backend/htqweb/http.py:86-101` | сверка компании токена с компанией запроса |
| `backend/apps/core/services.py` | `require_service` спрашивает `CompanyModule` |
| `backend/conftest.py` | фикстуры компаний-схем |
| `infra/nginx/default.conf:52-54` | `server_name` с регуляркой поддомена |
| `frontend/src/lib/auth/profileStorage.ts` | refresh-cookie на родительском домене |

---

## Задача 1: Аппка `apps.companies` и модели реестра

**Файлы:**
- Создать: `backend/apps/companies/__init__.py`, `apps.py`, `models.py`,
  `migrations/__init__.py`, `tests/__init__.py`
  (`admin.py` появится в задаче 17 — вместе со страницей версий схем)
- Изменить: `backend/htqweb/settings/base.py` (INSTALLED_APPS),
  `backend/apps/core/models.py` (KNOWN_SERVICES)
- Тест: `backend/apps/companies/tests/test_models.py`

**Интерфейсы:**
- Потребляет: ничего (первая задача).
- Производит: модели `Company`, `CompanyServiceLink`, `CompanyMembership`,
  `CompanyModule`, `CompanySchemaVersion`; константы
  `CompanyKind`, `CompanyStatus`.

- [ ] **Шаг 1: Написать падающий тест**

`backend/apps/companies/tests/test_models.py`:

```python
import pytest
from django.db import IntegrityError

from apps.companies.models import (
    Company, CompanyKind, CompanyServiceLink, CompanyStatus,
)


@pytest.mark.django_db
def test_holding_has_no_parent():
    holding = Company.objects.create(
        slug="htq", name="Hi-Tech Group LTD", kind=CompanyKind.HOLDING,
    )
    assert holding.parent is None
    assert holding.status == CompanyStatus.ACTIVE


@pytest.mark.django_db
def test_regional_company_points_at_holding():
    holding = Company.objects.create(
        slug="htq", name="Hi-Tech Group LTD", kind=CompanyKind.HOLDING,
    )
    kz = Company.objects.create(
        slug="htq-kz", name="Hi-Tech Qazaqstan",
        kind=CompanyKind.REGIONAL, parent=holding, country="KZ",
    )
    assert list(holding.children.all()) == [kz]


@pytest.mark.django_db
def test_slug_is_unique():
    Company.objects.create(slug="htq-kz", name="A", kind=CompanyKind.REGIONAL)
    with pytest.raises(IntegrityError):
        Company.objects.create(slug="htq-kz", name="B", kind=CompanyKind.REGIONAL)


@pytest.mark.django_db
def test_service_link_is_many_to_many_across_regions():
    """Одна сервисная компания обслуживает несколько региональных.

    Это перекрёстные стрелки ТМЗ с исходной схемы: граф услуг не совпадает
    с деревом владения, поэтому он и вынесен в отдельную модель.
    """
    kup = Company.objects.create(slug="kup", name="КУП", kind=CompanyKind.SERVICE)
    kz = Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    kg = Company.objects.create(slug="kurly-kg", name="KG", kind=CompanyKind.REGIONAL)

    CompanyServiceLink.objects.create(provider=kup, consumer=kz)
    CompanyServiceLink.objects.create(provider=kup, consumer=kg)

    assert kup.provided_services.count() == 2
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_models.py -q
```

Ожидается: `ModuleNotFoundError: No module named 'apps.companies'`.

- [ ] **Шаг 3: Создать `apps.py`**

`backend/apps/companies/apps.py`:

```python
from django.apps import AppConfig


class CompaniesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.companies"
    verbose_name = "Компании"
    # URL-автодискавери (htqweb/urls.py) смонтирует аппку по этому префиксу
    # без правки htqweb/urls.py. Имя сервиса в реестре совпадает с app_label,
    # поэтому запись в APP_LABEL_TO_SERVICE не нужна.
    API_PREFIX = "api/companies/v1/"
```

- [ ] **Шаг 4: Создать `models.py`**

`backend/apps/companies/models.py`:

```python
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Now

# slug одновременно служит поддоменом и суффиксом имени схемы, поэтому набор
# символов сужен до того, что безопасно и там, и там: DNS-метка не допускает
# подчёркиваний и заглавных, идентификатор Postgres не допускает дефисов
# (замена на "_" делается в htqweb.tenancy.context.schema_for).
SLUG_VALIDATOR = RegexValidator(
    r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$",
    "Только строчные латинские буквы, цифры и дефис; не начинается и не "
    "заканчивается дефисом; до 32 символов.",
)


class CompanyKind(models.TextChoices):
    HOLDING = "holding", "Холдинг"
    REGIONAL = "regional", "Региональная"
    SERVICE = "service", "Сервисная"


class CompanyStatus(models.TextChoices):
    ACTIVE = "active", "Действует"
    ARCHIVED = "archived", "В архиве"


class Company(models.Model):
    """Юридическое лицо группы. Владеет собственной схемой Postgres.

    Дерево владения (``parent``) и граф оказания услуг
    (``CompanyServiceLink``) — РАЗНЫЕ структуры и намеренно не сведены в
    одну: сервисная компания подчинена холдингу, но обслуживает несколько
    региональных сразу.
    """

    slug = models.CharField(max_length=32, unique=True, validators=[SLUG_VALIDATOR])
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=CompanyKind.choices)
    country = models.CharField(max_length=2, blank=True, default="", db_default="")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="children",
    )
    status = models.CharField(
        max_length=16, choices=CompanyStatus.choices,
        default=CompanyStatus.ACTIVE, db_default=CompanyStatus.ACTIVE.value,
        db_index=True,
    )
    # Заполняется при банкротстве (подпроект 4). Здесь только объявлено,
    # чтобы схема не менялась вторично, когда до него дойдут руки.
    successor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="predecessors",
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Компания"
        verbose_name_plural = "Компании"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class CompanyServiceLink(models.Model):
    """«Кто кому оказывает услуги» — граф ТМЗ, отдельный от дерева владения."""

    provider = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="provided_services",
    )
    consumer = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="consumed_services",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Связь по услугам"
        verbose_name_plural = "Связи по услугам"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "consumer"], name="uniq_service_link",
            ),
            models.CheckConstraint(
                condition=~models.Q(provider=models.F("consumer")),
                name="service_link_not_self",
            ),
        ]


class CompanyMembership(models.Model):
    """Право пользователя работать в компании.

    ``user_id`` — обычный int, а НЕ FK: межаппные ForeignKey запрещены
    инвариантом платформы (образец — apps.hr.models.Employee.user_id).
    """

    user_id = models.IntegerField(db_index=True)
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="memberships",
    )
    is_default = models.BooleanField(default=False, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Членство в компании"
        verbose_name_plural = "Членство в компаниях"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "company"], name="uniq_membership",
            ),
        ]


class CompanyModule(models.Model):
    """Второй, независимый слой рубильника поверх apps.core.ServiceStatus.

    ServiceStatus гасит аппку на ВСЕЙ платформе; эта таблица — в одной
    компании. Семантика объединения (см. apps.core.services.require_service):
    глобально выключено -> 503 везде; глобально включено, у компании
    выключено -> 503 только там. Отсутствие строки означает «включено».
    """

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="modules",
    )
    app_label = models.CharField(max_length=32)
    enabled = models.BooleanField(default=True, db_default=True)
    message = models.CharField(
        max_length=200, default="Модуль недоступен для этой компании",
        db_default="Модуль недоступен для этой компании",
    )
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Модуль компании"
        verbose_name_plural = "Модули компаний"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "app_label"], name="uniq_company_module",
            ),
        ]


class CompanySchemaVersion(models.Model):
    """Фактическая и целевая версия миграций схемы компании по каждой аппке.

    Существует, чтобы отставание схемы было видно ДО того, как проявится
    500-й ошибкой: разные компании обновляются с разной скоростью, и это
    штатный режим, а не авария.
    """

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="schema_versions",
    )
    app_label = models.CharField(max_length=32)
    applied_migration = models.CharField(max_length=255, blank=True, default="", db_default="")
    target_migration = models.CharField(max_length=255, blank=True, default="", db_default="")
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="", db_default="")

    class Meta:
        verbose_name = "Версия схемы компании"
        verbose_name_plural = "Версии схем компаний"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "app_label"], name="uniq_schema_version",
            ),
        ]
```

- [ ] **Шаг 5: Создать пустые `__init__.py`**

```bash
cd backend
touch apps/companies/__init__.py apps/companies/migrations/__init__.py apps/companies/tests/__init__.py
```

- [ ] **Шаг 6: Зарегистрировать аппку**

В `backend/htqweb/settings/base.py`, в `INSTALLED_APPS` сразу после
`"apps.core",` (реестр компаний — такой же фундамент, как реестр сервисов):

```python
    "apps.core",
    # Реестр компаний группы. Живёт в public и обязателен для всех: именно
    # он резолвит поддомен в схему Postgres, поэтому стоит до доменных аппок.
    "apps.companies",
```

В `backend/apps/core/models.py` добавить `"companies"` в `KNOWN_SERVICES`:

```python
KNOWN_SERVICES = ["users", "hr", "tasks", "approvals", "cms",
                  "media", "mail", "messenger", "conference", "contracts",
                  "signoff", "companies"]
```

- [ ] **Шаг 7: Сгенерировать миграцию**

```bash
cd backend
./.venv/Scripts/python.exe manage.py makemigrations companies
```

Ожидается: `companies/migrations/0001_initial.py` с пятью моделями.

- [ ] **Шаг 8: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_models.py -q
```

Ожидается: 4 passed.

- [ ] **Шаг 9: Прогнать тест изоляции аппок**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/core/tests/test_app_isolation.py -q
```

Ожидается: passed. Новая аппка ничего чужого не импортирует.

- [ ] **Шаг 10: Коммит**

```bash
git add backend/apps/companies backend/htqweb/settings/base.py backend/apps/core/models.py
git commit -m "feat(companies): реестр компаний группы"
```

---

## Задача 2: Контекст компании и имя схемы

**Файлы:**
- Создать: `backend/htqweb/tenancy/__init__.py`, `context.py`
- Тест: `backend/htqweb/tenancy/tests/test_context.py`

**Интерфейсы:**
- Потребляет: ничего.
- Производит:
  - `schema_for(slug: str) -> str`
  - `current_company() -> str` (поднимает `NoCompanyContext`, если не задан)
  - `current_company_or_none() -> str | None`
  - `set_company(slug: str | None) -> contextvars.Token`
  - `reset_company(token: contextvars.Token) -> None`
  - `class NoCompanyContext(RuntimeError)`
  - `HOLDING_SCHEMA = "holding"`

- [ ] **Шаг 1: Написать падающий тест**

`backend/htqweb/tenancy/tests/test_context.py`:

```python
import pytest

from htqweb.tenancy.context import (
    NoCompanyContext, current_company, current_company_or_none,
    reset_company, schema_for, set_company,
)


def test_schema_name_replaces_dashes():
    """Дефис допустим в DNS-метке, но не в идентификаторе Postgres."""
    assert schema_for("htq-kz") == "co_htq_kz"
    assert schema_for("kup") == "co_kup"


def test_no_context_raises():
    """Пустой контекст — ошибка, а не молчаливый public.

    Это тот же принцип, что и FALLBACK_MODE=strict: подмена, которой
    никто не закладывал, обязана быть падающим тестом.
    """
    assert current_company_or_none() is None
    with pytest.raises(NoCompanyContext):
        current_company()


def test_set_and_reset_are_symmetric():
    token = set_company("htq-kz")
    assert current_company() == "htq-kz"
    reset_company(token)
    assert current_company_or_none() is None


def test_nesting_restores_outer_value():
    outer = set_company("htq-kz")
    inner = set_company("htq-uz")
    assert current_company() == "htq-uz"
    reset_company(inner)
    assert current_company() == "htq-kz"
    reset_company(outer)
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_context.py -q
```

Ожидается: `ModuleNotFoundError: No module named 'htqweb.tenancy'`.

- [ ] **Шаг 3: Реализовать**

`backend/htqweb/tenancy/context.py`:

```python
"""Текущая компания запроса и вычисление имени её схемы.

Хранение — contextvars, а не threading.local, намеренно: под ASGI
(backend-asgi обслуживает SSE и WebSocket) в одном потоке живёт много
корутин, и thread-local утёк бы между ними. ContextVar копируется в каждую
задачу asyncio, поэтому изоляция сохраняется и там.

Значение — slug, а не объект Company: контекст обязан быть дешёвым и
сериализуемым (он же уходит аргументом в задачи Celery, см.
htqweb/tenancy/celery.py). Резолв slug -> строка реестра делает
apps.companies.interface с собственным кэшем.
"""

from __future__ import annotations

import contextvars

# Префикс схемы компании. Отдельный префикс, а не голый slug, чтобы схемы
# компаний нельзя было спутать с public/holding/служебными схемами Postgres
# при ручном разборе в psql.
SCHEMA_PREFIX = "co_"

# Схема со сводными UNION ALL-представлениями поверх всех активных компаний.
HOLDING_SCHEMA = "holding"


class NoCompanyContext(RuntimeError):
    """Обращение к компании там, где контекст не установлен."""


_current: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "htq_company_slug", default=None,
)


def schema_for(slug: str) -> str:
    """Имя схемы Postgres для компании.

    Дефис допустим в DNS-метке (slug — поддомен), но в неэкранированном
    идентификаторе Postgres он бы разобрался как минус, поэтому заменяется.
    """
    return SCHEMA_PREFIX + slug.replace("-", "_")


def current_company() -> str:
    slug = _current.get()
    if slug is None:
        raise NoCompanyContext(
            "Контекст компании не установлен. В HTTP-запросе его ставит "
            "CompanyContextMiddleware, в задаче Celery — декоратор "
            "@company_task, в тесте — фикстура company_context."
        )
    return slug


def current_company_or_none() -> str | None:
    return _current.get()


def set_company(slug: str | None) -> contextvars.Token:
    return _current.set(slug)


def reset_company(token: contextvars.Token) -> None:
    _current.reset(token)
```

`backend/htqweb/tenancy/__init__.py`:

```python
from .context import (  # noqa: F401
    HOLDING_SCHEMA, NoCompanyContext, current_company, current_company_or_none,
    reset_company, schema_for, set_company,
)
```

- [ ] **Шаг 4: Создать пакет тестов**

```bash
cd backend
touch htqweb/tenancy/tests/__init__.py
```

- [ ] **Шаг 5: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_context.py -q
```

Ожидается: 4 passed.

- [ ] **Шаг 6: Коммит**

```bash
git add backend/htqweb/tenancy
git commit -m "feat(tenancy): контекст текущей компании и имя схемы"
```

---

## Задача 3: Установка `search_path`

**Файлы:**
- Создать: `backend/htqweb/tenancy/db.py`
- Тест: `backend/htqweb/tenancy/tests/test_db.py`

**Интерфейсы:**
- Потребляет: `schema_for`, `set_company`, `reset_company`, `HOLDING_SCHEMA`
  из задачи 2.
- Производит:
  - `apply_search_path(slug: str | None, *, include_public: bool = True) -> None`
  - `use_company(slug: str, *, include_public: bool = True)` — контекстный менеджер
  - `use_holding()` — контекстный менеджер для чтения сводных представлений

- [ ] **Шаг 1: Написать падающий тест**

`backend/htqweb/tenancy/tests/test_db.py`:

```python
import pytest
from django.db import connection

from htqweb.tenancy.context import current_company_or_none
from htqweb.tenancy.db import apply_search_path, use_company, use_holding


def _search_path() -> str:
    with connection.cursor() as cur:
        cur.execute("SHOW search_path")
        return cur.fetchone()[0]


@pytest.mark.django_db
def test_apply_puts_company_schema_first():
    apply_search_path("htq-kz")
    assert _search_path().startswith("co_htq_kz")
    apply_search_path(None)


@pytest.mark.django_db
def test_public_can_be_excluded_for_migrations():
    """Во время миграции public исключается намеренно.

    Иначе Django находит public.django_migrations и все компании начинают
    считать себя мигрированными вместе.
    """
    apply_search_path("htq-kz", include_public=False)
    assert "public" not in _search_path()
    apply_search_path(None)


@pytest.mark.django_db
def test_use_company_restores_previous_state():
    with use_company("htq-kz"):
        assert current_company_or_none() == "htq-kz"
        assert _search_path().startswith("co_htq_kz")
    assert current_company_or_none() is None
    assert _search_path().startswith("public")


@pytest.mark.django_db
def test_use_company_restores_on_exception():
    with pytest.raises(ValueError):
        with use_company("htq-kz"):
            raise ValueError("боом")
    assert current_company_or_none() is None
    assert _search_path().startswith("public")


@pytest.mark.django_db
def test_use_holding_selects_holding_schema():
    with use_holding():
        assert _search_path().startswith("holding")
    assert _search_path().startswith("public")
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_db.py -q
```

Ожидается: `ImportError: cannot import name 'apply_search_path'`.

- [ ] **Шаг 3: Реализовать**

`backend/htqweb/tenancy/db.py`:

```python
"""Перевод соединения БД в схему компании.

Почему это безопасно именно здесь: CONN_MAX_AGE=0 (htqweb/settings/base.py),
то есть соединение живёт ровно один запрос и не возвращается в пул с чужим
search_path. Сброс в finally всё равно делается — чтобы поведение не зависело
от настройки, которую кто-нибудь однажды поменяет.

Имя схемы НЕ параметризуется через плейсхолдер: идентификатор в SET нельзя
передать значением. Экранирование делает psycopg-3 sql.Identifier, а набор
символов в slug дополнительно сужен валидатором в apps.companies.models.
"""

from __future__ import annotations

from contextlib import contextmanager

from django.db import connection
from psycopg import sql

from .context import (
    HOLDING_SCHEMA, current_company_or_none, reset_company, schema_for,
    set_company,
)

_PUBLIC_ONLY = sql.SQL("SET search_path TO public")


def apply_search_path(slug: str | None, *, include_public: bool = True) -> None:
    """Перевести текущее соединение в схему компании.

    ``slug=None`` возвращает соединение к чистому ``public``.
    ``include_public=False`` нужен ТОЛЬКО прогону миграций — см. докстринг
    apps.companies.services.migration_service.
    """
    if slug is None:
        statement = _PUBLIC_ONLY
    else:
        parts = [sql.Identifier(schema_for(slug))]
        if include_public:
            parts.append(sql.Identifier("public"))
        statement = sql.SQL("SET search_path TO {}").format(sql.SQL(", ").join(parts))
    with connection.cursor() as cur:
        cur.execute(statement)


@contextmanager
def use_company(slug: str, *, include_public: bool = True):
    """Выполнить блок в схеме компании, восстановив прежнее состояние.

    Восстанавливается именно ПРЕЖНЯЯ компания, а не public: вложенные
    use_company встречаются (задача обходит несколько компаний подряд), и
    выход из внутреннего блока не должен ронять внешний в public.
    """
    previous = current_company_or_none()
    token = set_company(slug)
    try:
        apply_search_path(slug, include_public=include_public)
        yield
    finally:
        reset_company(token)
        apply_search_path(previous)


@contextmanager
def use_holding():
    """Выполнить блок в схеме сводных представлений.

    Контекст компании при этом НЕ ставится: сводное чтение по определению
    находится над компаниями, и код, который его выполняет, не должен
    случайно считать себя работающим внутри одной из них.
    """
    with connection.cursor() as cur:
        cur.execute(
            sql.SQL("SET search_path TO {}, public").format(
                sql.Identifier(HOLDING_SCHEMA),
            )
        )
    try:
        yield
    finally:
        with connection.cursor() as cur:
            cur.execute(_PUBLIC_ONLY)
```

- [ ] **Шаг 4: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_db.py -q
```

Ожидается: 5 passed. Схем `co_htq_kz` и `holding` в тестовой БД ещё нет —
`SET search_path` на несуществующую схему Postgres не отвергает, он лишь
не найдёт в ней таблиц. Это ожидаемо: тест проверяет установку пути, а не
наличие схемы.

- [ ] **Шаг 5: Коммит**

```bash
git add backend/htqweb/tenancy/db.py backend/htqweb/tenancy/tests/test_db.py
git commit -m "feat(tenancy): перевод соединения в схему компании"
```

---

## Задача 4: `interface` аппки companies

**Файлы:**
- Создать: `backend/apps/companies/interface.py`
- Тест: `backend/apps/companies/tests/test_interface.py`

**Интерфейсы:**
- Потребляет: модели из задачи 1.
- Производит:
  - `get_company(slug: str) -> dict | None` — `{id, slug, name, kind, status, parent_slug, country}`
  - `active_company_slugs() -> list[str]`
  - `user_company_slugs(user_id: int) -> list[str]`
  - `default_company_slug(user_id: int) -> str | None`
  - `module_enabled(slug: str, app_label: str) -> tuple[bool, str]`

- [ ] **Шаг 1: Написать падающий тест**

`backend/apps/companies/tests/test_interface.py`:

```python
import pytest

from apps.companies import interface
from apps.companies.models import (
    Company, CompanyKind, CompanyMembership, CompanyModule, CompanyStatus,
)


@pytest.fixture
def kz(db):
    return Company.objects.create(
        slug="htq-kz", name="Hi-Tech Qazaqstan", kind=CompanyKind.REGIONAL,
    )


@pytest.mark.django_db
def test_get_company_returns_plain_dict(kz):
    """Наружу отдаётся dict, а не ORM-объект: сосед не должен иметь
    возможности мутировать чужую модель напрямую."""
    data = interface.get_company("htq-kz")
    assert data["slug"] == "htq-kz"
    assert data["kind"] == "regional"
    assert not hasattr(data, "save")


@pytest.mark.django_db
def test_get_company_unknown_slug_is_none(kz):
    assert interface.get_company("нет-такой") is None


@pytest.mark.django_db
def test_archived_company_is_not_in_active_list(kz):
    Company.objects.create(
        slug="dead", name="Банкрот", kind=CompanyKind.SERVICE,
        status=CompanyStatus.ARCHIVED,
    )
    assert interface.active_company_slugs() == ["htq-kz"]


@pytest.mark.django_db
def test_user_company_slugs_lists_only_own(kz):
    other = Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    CompanyMembership.objects.create(user_id=7, company=kz, is_default=True)
    assert interface.user_company_slugs(7) == ["htq-kz"]
    assert interface.default_company_slug(7) == "htq-kz"
    assert interface.user_company_slugs(8) == []


@pytest.mark.django_db
def test_module_without_row_is_enabled(kz):
    """Отсутствие строки означает «включено» — так же, как у ServiceStatus."""
    assert interface.module_enabled("htq-kz", "tasks") == (True, "")


@pytest.mark.django_db
def test_module_can_be_disabled_per_company(kz):
    CompanyModule.objects.create(
        company=kz, app_label="tasks", enabled=False, message="Не оплачено",
    )
    assert interface.module_enabled("htq-kz", "tasks") == (False, "Не оплачено")
    assert interface.module_enabled("htq-kz", "contracts") == (True, "")
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_interface.py -q
```

Ожидается: `ModuleNotFoundError: No module named 'apps.companies.interface'`.

- [ ] **Шаг 3: Реализовать**

`backend/apps/companies/interface.py`:

```python
"""Публичный API аппки companies для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к реестру
компаний. Прямой импорт apps.companies.models из другой аппки запрещён и
ловится apps/core/tests/test_app_isolation.py.

Отличие от остальных interface-модулей платформы: здесь НЕ вызывается
require_service("companies"). Реестр компаний — фундамент, а не отключаемый
домен: без него нельзя ни зарезолвить поддомен, ни выбрать схему, поэтому
его выключение означало бы отказ всей платформы, а не деградацию одного
сервиса. Строка ServiceStatus для него всё равно заводится (KNOWN_SERVICES),
чтобы админка и метрики видели полный список.

Кэш на 5 секунд — тот же приём и тот же TTL, что у
apps.core.services.service_status: резолв дёргается на КАЖДЫЙ запрос
(CompanyContextMiddleware), и ходить за ним в БД каждый раз незачем.
Fail-open по кэшу: недоступный Redis не должен ронять весь трафик.
"""

from __future__ import annotations

import logging

from django.core.cache import cache

from .models import Company, CompanyMembership, CompanyModule, CompanyStatus

logger = logging.getLogger(__name__)

_CACHE_TTL = 5


def _cached(key: str, producer):
    try:
        hit = cache.get(key)
    except Exception:
        logger.warning("cache.get failed for key %s; falling back to DB", key,
                       exc_info=True)
        hit = None
    if hit is None:
        hit = producer()
        try:
            cache.set(key, hit, _CACHE_TTL)
        except Exception:
            logger.warning("cache.set failed for key %s; continuing without cache",
                           key, exc_info=True)
    return hit


def _serialize(company: Company) -> dict:
    return {
        "id": company.id,
        "slug": company.slug,
        "name": company.name,
        "kind": company.kind,
        "status": company.status,
        "country": company.country,
        "parent_slug": company.parent.slug if company.parent_id else None,
    }


def get_company(slug: str) -> dict | None:
    """Строка реестра по slug, или None если такой компании нет."""
    def produce():
        company = Company.objects.select_related("parent").filter(slug=slug).first()
        return _serialize(company) if company else {}

    found = _cached(f"company:{slug}", produce)
    return found or None


def active_company_slugs() -> list[str]:
    """Slug'и всех действующих компаний, в алфавитном порядке.

    Порядок стабильный намеренно: этот список задаёт порядок веток в
    UNION ALL-представлениях схемы holding, и его дрожание заставляло бы
    представления пересоздаваться без причины.
    """
    return _cached(
        "company:active",
        lambda: sorted(
            Company.objects.filter(status=CompanyStatus.ACTIVE)
            .values_list("slug", flat=True)
        ),
    )


def user_company_slugs(user_id: int) -> list[str]:
    """Компании, в которых пользователь имеет право работать."""
    return _cached(
        f"company:member:{user_id}",
        lambda: sorted(
            CompanyMembership.objects.filter(user_id=user_id)
            .values_list("company__slug", flat=True)
        ),
    )


def default_company_slug(user_id: int) -> str | None:
    """Компания, куда пользователя пускать сразу после входа."""
    row = (CompanyMembership.objects
           .filter(user_id=user_id)
           .order_by("-is_default", "company__slug")
           .values_list("company__slug", flat=True)
           .first())
    return row


def module_enabled(slug: str, app_label: str) -> tuple[bool, str]:
    """Включён ли модуль у компании. Отсутствие строки означает «включён»."""
    def produce():
        row = (CompanyModule.objects
               .filter(company__slug=slug, app_label=app_label)
               .values("enabled", "message")
               .first())
        if row is None:
            return (True, "")
        return (row["enabled"], row["message"] if not row["enabled"] else "")

    return _cached(f"company:module:{slug}:{app_label}", produce)
```

- [ ] **Шаг 4: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_interface.py -q
```

Ожидается: 6 passed.

- [ ] **Шаг 5: Коммит**

```bash
git add backend/apps/companies/interface.py backend/apps/companies/tests/test_interface.py
git commit -m "feat(companies): interface реестра для соседних аппок"
```

---

## Задача 5: Создание схемы компании

**Файлы:**
- Создать: `backend/apps/companies/services/__init__.py`, `schema_service.py`
- Изменить: `backend/htqweb/settings/base.py` (добавить `TENANT_APPS`)
- Тест: `backend/apps/companies/tests/test_schema_service.py`

**Интерфейсы:**
- Потребляет: `schema_for` (задача 2), `apply_search_path` (задача 3).
- Производит:
  - `create_schema(slug: str) -> None` — идемпотентна
  - `drop_schema(slug: str) -> None`
  - `schema_exists(slug: str) -> bool`
  - `settings.TENANT_APPS == ("hr", "tasks", "contracts", "signoff")`

- [ ] **Шаг 1: Написать падающий тест**

`backend/apps/companies/tests/test_schema_service.py`:

```python
import pytest

from apps.companies.services import schema_service


@pytest.mark.django_db
def test_create_then_exists():
    schema_service.create_schema("t-alpha")
    assert schema_service.schema_exists("t-alpha") is True
    schema_service.drop_schema("t-alpha")
    assert schema_service.schema_exists("t-alpha") is False


@pytest.mark.django_db
def test_create_is_idempotent():
    """Повторный вызов не падает: создание компании должно переживать
    повтор после сетевого сбоя, как и остальные internal-ручки платформы."""
    schema_service.create_schema("t-beta")
    schema_service.create_schema("t-beta")
    assert schema_service.schema_exists("t-beta") is True
    schema_service.drop_schema("t-beta")


@pytest.mark.django_db
def test_drop_is_idempotent():
    schema_service.drop_schema("t-never-existed")


@pytest.mark.django_db
def test_tenant_apps_are_the_four_domain_apps(settings):
    assert settings.TENANT_APPS == ("hr", "tasks", "contracts", "signoff")
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_schema_service.py -q
```

Ожидается: `ModuleNotFoundError: No module named 'apps.companies.services'`.

- [ ] **Шаг 3: Добавить `TENANT_APPS` в настройки**

В `backend/htqweb/settings/base.py`, сразу после блока `INSTALLED_APPS`:

```python
# Аппки, чьи таблицы живут в схеме КОМПАНИИ, а не в public. Всё остальное
# (users, cms, media_files, mail, messenger, conference, core, companies)
# общее для группы — см. docs/multi-company-tenancy-design.md §3.
#
# Кортеж, а не список: набор фиксирован архитектурным решением, и случайный
# .append() в чужом модуле не должен его расширять.
TENANT_APPS = ("hr", "tasks", "contracts", "signoff")
```

- [ ] **Шаг 4: Реализовать сервис**

`backend/apps/companies/services/schema_service.py`:

```python
"""Создание и удаление схемы Postgres под компанию.

Только DDL самой схемы. Наполнение её таблицами — задача
migration_service.migrate_company: разделены потому, что схему создают один
раз, а мигрируют многократно.
"""

from __future__ import annotations

from django.db import connection
from psycopg import sql

from htqweb.tenancy.context import schema_for


def schema_exists(slug: str) -> bool:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
            [schema_for(slug)],
        )
        return cur.fetchone() is not None


def create_schema(slug: str) -> None:
    """Создать схему компании. Идемпотентна."""
    with connection.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(schema_for(slug)),
            )
        )


def drop_schema(slug: str) -> None:
    """Удалить схему компании со всем содержимым. Идемпотентна.

    Штатным закрытием компании НЕ является: закрытие — это архив с переносом
    активов (подпроект 4), данные при нём сохраняются. Эта функция нужна для
    отката неудавшегося создания и для уборки в тестах.
    """
    with connection.cursor() as cur:
        cur.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema_for(slug)),
            )
        )
```

`backend/apps/companies/services/__init__.py` — пустой файл.

- [ ] **Шаг 5: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_schema_service.py -q
```

Ожидается: 4 passed.

- [ ] **Шаг 6: Коммит**

```bash
git add backend/apps/companies/services backend/htqweb/settings/base.py backend/apps/companies/tests/test_schema_service.py
git commit -m "feat(companies): создание и удаление схемы компании"
```

---

## Задача 6: Прогон миграций по схемам компаний

**Файлы:**
- Создать: `backend/apps/companies/services/migration_service.py`,
  `backend/apps/companies/management/__init__.py`,
  `backend/apps/companies/management/commands/__init__.py`,
  `backend/apps/companies/management/commands/migrate_companies.py`
- Тест: `backend/apps/companies/tests/test_migration_service.py`

**Интерфейсы:**
- Потребляет: `create_schema`, `schema_exists` (задача 5),
  `apply_search_path` (задача 3), `CompanySchemaVersion` (задача 1),
  `settings.TENANT_APPS` (задача 5).
- Производит:
  - `migrate_company(slug: str, *, app_label: str | None = None, target: str | None = None, plan: bool = False) -> dict`
    — возвращает `{"slug": str, "applied": {app_label: migration_name}, "planned": [str]}`
  - `ADVISORY_LOCK_KEY: int`

- [ ] **Шаг 1: Написать падающий тест**

`backend/apps/companies/tests/test_migration_service.py`:

```python
import pytest
from django.db import connection

from apps.companies.models import Company, CompanyKind, CompanySchemaVersion
from apps.companies.services import migration_service, schema_service


@pytest.fixture
def alpha(db):
    company = Company.objects.create(
        slug="t-alpha", name="Alpha", kind=CompanyKind.SERVICE,
    )
    schema_service.create_schema("t-alpha")
    yield company
    schema_service.drop_schema("t-alpha")


def _tables_in(schema: str) -> set[str]:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            [schema],
        )
        return {row[0] for row in cur.fetchall()}


@pytest.mark.django_db(transaction=True)
def test_migrate_creates_tenant_tables_in_company_schema(alpha):
    migration_service.migrate_company("t-alpha")
    tables = _tables_in("co_t_alpha")
    assert "hr_employee" in tables
    assert "tasks_task" in tables


@pytest.mark.django_db(transaction=True)
def test_each_schema_gets_its_own_migration_state(alpha):
    """Ключевая деталь всей задачи.

    Если во время миграции в search_path остаётся public, Django находит
    public.django_migrations и записывает туда состояние — после чего ВСЕ
    компании считают себя мигрированными вместе, а их схемы остаются пустыми.
    """
    migration_service.migrate_company("t-alpha")
    assert "django_migrations" in _tables_in("co_t_alpha")


@pytest.mark.django_db(transaction=True)
def test_migrate_does_not_touch_shared_apps(alpha):
    """users/cms/media_files живут в public и в схему компании не копируются."""
    migration_service.migrate_company("t-alpha")
    tables = _tables_in("co_t_alpha")
    assert not any(t.startswith("users_") for t in tables)
    assert not any(t.startswith("cms_") for t in tables)


@pytest.mark.django_db(transaction=True)
def test_migrate_records_version(alpha):
    migration_service.migrate_company("t-alpha")
    rows = CompanySchemaVersion.objects.filter(company=alpha)
    assert rows.count() == 4
    assert all(r.applied_migration for r in rows)
    assert all(r.last_error == "" for r in rows)


@pytest.mark.django_db(transaction=True)
def test_plan_mode_changes_nothing(alpha):
    result = migration_service.migrate_company("t-alpha", plan=True)
    assert result["planned"]
    assert "hr_employee" not in _tables_in("co_t_alpha")


@pytest.mark.django_db(transaction=True)
def test_second_run_is_a_noop(alpha):
    migration_service.migrate_company("t-alpha")
    result = migration_service.migrate_company("t-alpha")
    assert result["planned"] == []
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_migration_service.py -q
```

Ожидается: `ImportError: cannot import name 'migration_service'`.

- [ ] **Шаг 3: Реализовать сервис**

`backend/apps/companies/services/migration_service.py`:

```python
"""Прогон миграций Django по схемам компаний.

ГЛАВНОЕ, ради чего этот модуль существует отдельно от штатной команды
migrate: во время прогона search_path ставится ТОЛЬКО в схему компании, БЕЗ
public. Иначе Django находит public.django_migrations, пишет состояние туда,
и все компании начинают считать себя мигрированными вместе — при полностью
пустых схемах. Ошибка молчаливая и проявляется только на первом запросе к
несуществующей таблице, поэтому она закреплена тестом
test_each_schema_gets_its_own_migration_state.

Блокировка — advisory lock на уровне сессии Postgres, а не строка в таблице:
одновременная выкатка двух контейнеров backend-web — обычное дело, а
advisory lock снимается автоматически при обрыве соединения, тогда как
строка-семафор осталась бы висеть навсегда.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from htqweb.tenancy.db import apply_search_path

from ..models import Company, CompanySchemaVersion

# Произвольная, но фиксированная константа: два процесса должны выбирать
# один и тот же ключ, иначе блокировка не блокирует.
ADVISORY_LOCK_KEY = 0x48545143  # "HTQC"


def _acquire_lock() -> None:
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", [ADVISORY_LOCK_KEY])


def _release_lock() -> None:
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])


def _pending(app_labels: tuple[str, ...]) -> list[str]:
    """Непринятые миграции в ТЕКУЩЕЙ схеме (search_path уже выставлен)."""
    executor = MigrationExecutor(connection)
    targets = [t for t in executor.loader.graph.leaf_nodes() if t[0] in app_labels]
    plan = executor.migration_plan(targets)
    return [f"{migration.app_label}.{migration.name}" for migration, _ in plan]


def _record(company: Company, app_label: str, applied: str, error: str = "") -> None:
    CompanySchemaVersion.objects.update_or_create(
        company=company, app_label=app_label,
        defaults={
            "applied_migration": applied,
            "target_migration": applied,
            "last_run_at": timezone.now(),
            "last_error": error,
        },
    )


def migrate_company(slug: str, *, app_label: str | None = None,
                    target: str | None = None, plan: bool = False) -> dict:
    """Довести схему компании до целевой версии.

    ``app_label`` сужает прогон до одной аппки, ``target`` — до конкретной
    миграции (для отката вперёд-назад в expand/contract). ``plan=True`` даёт
    сухой прогон: возвращает список того, что применилось бы, ничего не меняя.
    """
    company = Company.objects.get(slug=slug)
    app_labels = (app_label,) if app_label else tuple(settings.TENANT_APPS)

    _acquire_lock()
    try:
        # БЕЗ public — см. докстринг модуля.
        apply_search_path(slug, include_public=False)
        planned = _pending(app_labels)
        if plan:
            return {"slug": slug, "applied": {}, "planned": planned}

        applied: dict[str, str] = {}
        for label in app_labels:
            args = [label] + ([target] if target else [])
            call_command("migrate", *args, verbosity=0, interactive=False)
            executor = MigrationExecutor(connection)
            executor.loader.build_graph()
            names = sorted(n for a, n in executor.loader.applied_migrations if a == label)
            applied[label] = names[-1] if names else ""
    finally:
        apply_search_path(None)
        _release_lock()

    # Запись версий — уже в public, поэтому после сброса search_path.
    for label, name in applied.items():
        _record(company, label, name)

    return {"slug": slug, "applied": applied, "planned": planned}
```

- [ ] **Шаг 4: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_migration_service.py -q
```

Ожидается: 6 passed.

- [ ] **Шаг 5: Написать команду**

`backend/apps/companies/management/commands/migrate_companies.py`:

```python
from django.core.management.base import BaseCommand, CommandError

from apps.companies.interface import active_company_slugs
from apps.companies.services import migration_service


class Command(BaseCommand):
    help = ("Довести схемы компаний до текущей версии миграций. "
            "Без --company обрабатывает все действующие компании.")

    def add_arguments(self, parser):
        parser.add_argument("--company", help="slug одной компании")
        parser.add_argument("--app", help="только эта аппка (hr/tasks/contracts/signoff)")
        parser.add_argument("--to", help="целевая миграция, напр. 0042")
        parser.add_argument("--plan", action="store_true",
                            help="сухой прогон: показать, что применилось бы")

    def handle(self, *args, **opts):
        slugs = [opts["company"]] if opts["company"] else active_company_slugs()
        if not slugs:
            raise CommandError("Нет действующих компаний.")

        for slug in slugs:
            result = migration_service.migrate_company(
                slug, app_label=opts["app"], target=opts["to"], plan=opts["plan"],
            )
            if opts["plan"]:
                pending = result["planned"] or ["— всё применено"]
                self.stdout.write(f"{slug}: " + ", ".join(pending))
            else:
                summary = ", ".join(f"{a}={m or '—'}"
                                    for a, m in sorted(result["applied"].items()))
                self.stdout.write(self.style.SUCCESS(f"{slug}: {summary}"))
```

Создать пустые `backend/apps/companies/management/__init__.py` и
`backend/apps/companies/management/commands/__init__.py`.

- [ ] **Шаг 6: Проверить команду вручную**

```bash
cd backend
./.venv/Scripts/python.exe manage.py migrate_companies --plan
```

Ожидается: `CommandError: Нет действующих компаний.` — компаний в базе
разработки ещё нет, и это корректное поведение.

- [ ] **Шаг 7: Коммит**

```bash
git add backend/apps/companies/services/migration_service.py backend/apps/companies/management backend/apps/companies/tests/test_migration_service.py
git commit -m "feat(companies): migrate_companies — миграции по схемам компаний"
```

---

## Задача 7: Middleware контекста компании

**Файлы:**
- Создать: `backend/htqweb/middleware/company_context.py`
- Изменить: `backend/htqweb/settings/base.py` (MIDDLEWARE)
- Тест: `backend/htqweb/tenancy/tests/test_middleware.py`

**Интерфейсы:**
- Потребляет: `get_company` (задача 4), `set_company`/`reset_company`
  (задача 2), `apply_search_path` (задача 3).
- Производит: `CompanyContextMiddleware`, `COMPANY_HEADER = "X-HTQ-Company"`;
  атрибут `request.company` (dict или None).

- [ ] **Шаг 1: Написать падающий тест**

`backend/htqweb/tenancy/tests/test_middleware.py`:

```python
import pytest
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyStatus
from htqweb.tenancy.context import current_company_or_none


@pytest.fixture
def kz(db):
    return Company.objects.create(
        slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL,
    )


@pytest.mark.django_db
def test_health_works_without_company_header():
    """Служебные роуты не требуют компании: /health/ и /metrics/ должны
    отвечать и тогда, когда реестр пуст, иначе оркестратор не сможет
    поднять стек с нуля."""
    assert Client().get("/health/").status_code == 200


@pytest.mark.django_db
def test_unknown_company_is_404(kz):
    response = Client().get("/api/users/v1/me", HTTP_X_HTQ_COMPANY="нет-такой")
    assert response.status_code == 404
    assert response.json()["detail"]


@pytest.mark.django_db
def test_archived_company_is_404():
    Company.objects.create(
        slug="dead", name="Банкрот", kind=CompanyKind.SERVICE,
        status=CompanyStatus.ARCHIVED,
    )
    response = Client().get("/api/users/v1/me", HTTP_X_HTQ_COMPANY="dead")
    assert response.status_code == 404


@pytest.mark.django_db
def test_context_is_cleared_after_response(kz):
    Client().get("/api/users/v1/me", HTTP_X_HTQ_COMPANY="htq-kz")
    assert current_company_or_none() is None


@pytest.mark.django_db
def test_context_is_cleared_even_when_view_raises(kz, rf):
    """Утёкший контекст — худший из возможных дефектов этой архитектуры:
    следующий запрос в том же процессе прочитал бы чужую схему.

    Middleware вызывается напрямую, а не через Client: тестовый клиент
    Django ловит исключения вьюхи и превращает их в 500, то есть скрыл бы
    именно тот путь, который здесь проверяется.
    """
    from htqweb.middleware.company_context import CompanyContextMiddleware

    def boom(request):
        raise RuntimeError("боом")

    middleware = CompanyContextMiddleware(boom)
    request = rf.get("/api/tasks/v1/", HTTP_X_HTQ_COMPANY="htq-kz")
    with pytest.raises(RuntimeError):
        middleware(request)
    assert current_company_or_none() is None
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_middleware.py -q
```

Ожидается: `test_unknown_company_is_404` падает — сейчас middleware нет и
заголовок игнорируется.

- [ ] **Шаг 3: Реализовать**

`backend/htqweb/middleware/company_context.py`:

```python
"""Резолв компании запроса и перевод соединения в её схему.

Регистрируется ПЕРЕД ServiceGateMiddleware: тот гасит домены по URL-префиксу
и должен уже знать компанию, чтобы спросить не только глобальный рубильник
(ServiceStatus), но и компанейский (CompanyModule).

Middleware, а не api_view: контекст нужен также /django-admin/ и /ws/, а они
через api_view не проходят.

Сброс в finally безусловен. CONN_MAX_AGE=0 уже гарантирует, что соединение
не переживёт запрос, но contextvar под ASGI переживает — и утёкшее значение
означало бы чтение чужой схемы следующим запросом в том же процессе.
"""

from __future__ import annotations

from django.http import JsonResponse

from apps.companies.interface import get_company
from apps.companies.models import CompanyStatus
from htqweb.tenancy.context import reset_company, set_company
from htqweb.tenancy.db import apply_search_path

COMPANY_HEADER = "X-HTQ-Company"

# Пути, которым компания не нужна и которые обязаны отвечать при пустом
# реестре: без них нельзя ни поднять стек с нуля, ни снять метрики.
_EXEMPT_PREFIXES = ("/health", "/metrics", "/static/", "/django-admin/login")


class CompanyContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(_EXEMPT_PREFIXES):
            request.company = None
            return self.get_response(request)

        slug = request.headers.get(COMPANY_HEADER, "").strip().lower()
        if not slug:
            # Компания не указана — запрос обслуживается в public. Это режим
            # общих доменов (users/cms/media) и переходный период до полного
            # перевода фронта на поддомены.
            request.company = None
            return self.get_response(request)

        company = get_company(slug)
        if company is None or company["status"] != CompanyStatus.ACTIVE:
            # 404, а не 403: существование компании — само по себе сведение,
            # которое незачем подтверждать анонимному запросу.
            return JsonResponse({"detail": "Компания не найдена"}, status=404)

        request.company = company
        token = set_company(slug)
        try:
            apply_search_path(slug)
            return self.get_response(request)
        finally:
            reset_company(token)
            apply_search_path(None)
```

- [ ] **Шаг 4: Зарегистрировать в настройках**

В `backend/htqweb/settings/base.py`, в `MIDDLEWARE`, СТРОГО перед
`ServiceGateMiddleware`:

```python
    "htqweb.middleware.request_id.RequestIDMiddleware",
    # Ставится ДО ServiceGateMiddleware: тот гейтит домены и должен уже
    # знать компанию, чтобы спросить и глобальный рубильник, и компанейский.
    "htqweb.middleware.company_context.CompanyContextMiddleware",
    "htqweb.middleware.service_gate.ServiceGateMiddleware",
```

- [ ] **Шаг 5: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_middleware.py -q
```

Ожидается: 5 passed.

- [ ] **Шаг 6: Прогнать весь набор — проверить, что ничего не сломалось**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest -q
```

Ожидается: количество упавших тестов не выросло относительно состояния до
задачи. Запишите базовое число ДО начала работы — в репозитории есть
известные заранее падающие тесты.

- [ ] **Шаг 7: Коммит**

```bash
git add backend/htqweb/middleware/company_context.py backend/htqweb/settings/base.py backend/htqweb/tenancy/tests/test_middleware.py
git commit -m "feat(tenancy): middleware контекста компании"
```

---

## Задача 8: Claim `company` в JWT и сверка в `api_view`

**Файлы:**
- Изменить: `backend/htqweb/authn/payload.py:20-31`,
  `backend/htqweb/authn/jwt.py:14-24`, `backend/htqweb/http.py:86-101`
- Тест: `backend/htqweb/tenancy/tests/test_token_company.py`

**Интерфейсы:**
- Потребляет: `request.company` (задача 7).
- Производит: `TokenPayload.company: str | None`; claim `company` в
  access-токене; 403 при расхождении.

- [ ] **Шаг 1: Написать падающий тест**

`backend/htqweb/tenancy/tests/test_token_company.py`:

```python
import pytest
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import decode_token, issue_token_pair


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="ivan", email="ivan@htq.kz", password="pw",
        status=UserStatus.ACTIVE,
    )


@pytest.fixture
def companies(db):
    kz = Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    uz = Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    return kz, uz


@pytest.mark.django_db
def test_access_token_carries_default_company(user, companies):
    kz, _ = companies
    CompanyMembership.objects.create(user_id=user.id, company=kz, is_default=True)
    pair = issue_token_pair(user)
    assert decode_token(pair["access"]).company == "htq-kz"


@pytest.mark.django_db
def test_token_without_membership_has_no_company(user, companies):
    pair = issue_token_pair(user)
    assert decode_token(pair["access"]).company is None


@pytest.mark.django_db
def test_token_of_one_company_is_rejected_on_another(user, companies):
    """Вторая линия обороны поддоменной схемы.

    Без неё токен, полученный на kz.htqweb.kz, работал бы и на uz.htqweb.kz —
    поддомен подменяется тривиально, подпись токена нет.
    """
    kz, _ = companies
    CompanyMembership.objects.create(user_id=user.id, company=kz, is_default=True)
    access = issue_token_pair(user)["access"]

    ok = Client().get("/api/users/v1/me",
                      HTTP_AUTHORIZATION=f"Bearer {access}",
                      HTTP_X_HTQ_COMPANY="htq-kz")
    assert ok.status_code == 200

    denied = Client().get("/api/users/v1/me",
                          HTTP_AUTHORIZATION=f"Bearer {access}",
                          HTTP_X_HTQ_COMPANY="htq-uz")
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Forbidden"}
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_token_company.py -q
```

Ожидается: `AttributeError: 'TokenPayload' object has no attribute 'company'`.

- [ ] **Шаг 3: Добавить поле в `TokenPayload`**

В `backend/htqweb/authn/payload.py`, в класс `TokenPayload`, после
`email: str | None = None`:

```python
    # Компания, для которой выпущен токен. None у токенов, выданных до
    # введения мультикомпанейности, и у пользователей без членства — такой
    # токен работает только на общих доменах (users/cms/media).
    company: str | None = None
```

- [ ] **Шаг 4: Класть claim при выпуске токена**

В `backend/htqweb/authn/jwt.py` заменить `_base_claims` на:

```python
def _base_claims(user) -> dict:
    # Локальный импорт: htqweb.authn грузится очень рано, а apps.companies —
    # обычная аппка, чьи модели к тому моменту ещё не готовы.
    from apps.companies.interface import default_company_slug

    return {
        "sub": str(user.id),
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "is_admin": user.is_staff or user.is_superuser,
        # Компания по умолчанию. При переключении компании фронт получает
        # новый access-токен обменом refresh-cookie — см. задачу 13.
        "company": default_company_slug(user.id),
        "iss": settings.JWT_ISSUER,
    }
```

- [ ] **Шаг 5: Сверять компанию в `api_view`**

В `backend/htqweb/http.py`, внутри `view`, сразу после
`request.token = payload` и ПЕРЕД проверкой `admin`:

```python
                request.token = payload
                # Поддомен подменяется тривиально, подпись токена — нет.
                # Токен, выпущенный для одной компании, не должен работать
                # в другой, даже если у пользователя есть членство в обеих:
                # переключение обязано пройти через выдачу нового токена.
                current = getattr(request, "company", None)
                if current is not None and payload.company != current["slug"]:
                    return json_error("Forbidden", 403)
```

- [ ] **Шаг 6: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_token_company.py -q
```

Ожидается: 3 passed.

- [ ] **Шаг 7: Коммит**

```bash
git add backend/htqweb/authn backend/htqweb/http.py backend/htqweb/tenancy/tests/test_token_company.py
git commit -m "feat(tenancy): claim company в токене и сверка с компанией запроса"
```

---

## Задача 9: Гейт модулей на уровне компании

**Файлы:**
- Изменить: `backend/apps/core/services.py`
- Тест: `backend/apps/core/tests/test_company_module_gate.py`

**Интерфейсы:**
- Потребляет: `module_enabled` (задача 4), `current_company_or_none` (задача 2).
- Производит: `require_service` и `service_status` учитывают `CompanyModule`;
  `CORE_MODULES: frozenset[str]`.

- [ ] **Шаг 1: Написать падающий тест**

`backend/apps/core/tests/test_company_module_gate.py`:

```python
import pytest

from apps.companies.models import Company, CompanyKind, CompanyModule
from apps.core.services import CORE_MODULES, ServiceDisabled, require_service
from htqweb.tenancy.db import use_company


@pytest.fixture
def kz(db):
    return Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)


@pytest.mark.django_db
def test_module_disabled_for_company_raises(kz):
    CompanyModule.objects.create(
        company=kz, app_label="tasks", enabled=False, message="Не подключён",
    )
    with use_company("htq-kz"):
        with pytest.raises(ServiceDisabled) as exc:
            require_service("tasks")
    assert exc.value.message == "Не подключён"


@pytest.mark.django_db
def test_module_disabled_for_company_does_not_affect_others(kz):
    Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    CompanyModule.objects.create(company=kz, app_label="tasks", enabled=False)
    with use_company("htq-uz"):
        require_service("tasks")  # не должно поднять исключение


@pytest.mark.django_db
def test_core_module_cannot_be_disabled_per_company(kz):
    """Ядро одинаково у всех — это прямое требование заказчика.

    Строку в CompanyModule для ядра завести можно (форму никто не
    ограничивает), но гейт её игнорирует, иначе компания осталась бы без
    входа или без кадров.
    """
    assert "hr" in CORE_MODULES
    CompanyModule.objects.create(company=kz, app_label="hr", enabled=False)
    with use_company("htq-kz"):
        require_service("hr")


@pytest.mark.django_db
def test_without_company_context_only_global_switch_applies(kz):
    CompanyModule.objects.create(company=kz, app_label="tasks", enabled=False)
    require_service("tasks")  # вне контекста компании — не падает
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/core/tests/test_company_module_gate.py -q
```

Ожидается: `ImportError: cannot import name 'CORE_MODULES'`.

- [ ] **Шаг 3: Реализовать**

В `backend/apps/core/services.py` добавить после `_CACHE_TTL`:

```python
# Обязательное ядро платформы: эти домены есть у КАЖДОЙ компании и на уровне
# компании не выключаются (требование заказчика — «основной монолит функций,
# который точно будет у всех»). Глобальный рубильник ServiceStatus на них
# по-прежнему действует: он гасит домен на всей платформе, а не у одной
# компании, и нужен для регламентных работ.
CORE_MODULES = frozenset({"users", "companies", "core", "hr", "messenger",
                          "media", "cms"})
```

И заменить `require_service` на:

```python
def require_service(name: str) -> None:
    enabled, message = service_status(name)
    if not enabled:
        raise ServiceDisabled(name, message)
    _require_company_module(name)


def _require_company_module(name: str) -> None:
    """Второй, независимый слой рубильника — на уровне компании.

    Импорт локальный: apps.core грузится раньше apps.companies, а на уровне
    модуля это была бы циклическая зависимость фундамента от реестра.

    Вне контекста компании (Celery без company_slug, служебные роуты,
    общие домены) проверка не выполняется — там компанейского рубильника
    просто нет, и подставлять вместо него какой-либо дефолт было бы
    молчаливой подменой.
    """
    if name in CORE_MODULES:
        return
    from apps.companies.interface import module_enabled
    from htqweb.tenancy.context import current_company_or_none

    slug = current_company_or_none()
    if slug is None:
        return
    enabled, message = module_enabled(slug, name)
    if not enabled:
        raise ServiceDisabled(name, message)
```

- [ ] **Шаг 4: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/core/tests/test_company_module_gate.py -q
```

Ожидается: 4 passed.

- [ ] **Шаг 5: Прогнать тест изоляции аппок**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/core/tests/test_app_isolation.py -q
```

Ожидается: passed — импорт идёт через `apps.companies.interface`, что
правило разрешает.

- [ ] **Шаг 6: Коммит**

```bash
git add backend/apps/core/services.py backend/apps/core/tests/test_company_module_gate.py
git commit -m "feat(core): рубильник модулей на уровне компании"
```

---

## Задача 10: Задачи Celery с компанией

**Файлы:**
- Создать: `backend/htqweb/tenancy/celery.py`
- Тест: `backend/htqweb/tenancy/tests/test_celery.py`

**Интерфейсы:**
- Потребляет: `use_company` (задача 3).
- Производит: `company_task(fn)` — декоратор; `MissingCompanyArgument`.

- [ ] **Шаг 1: Написать падающий тест**

`backend/htqweb/tenancy/tests/test_celery.py`:

```python
import pytest

from htqweb.tenancy.celery import MissingCompanyArgument, company_task
from htqweb.tenancy.context import current_company_or_none


@company_task
def _echo_company():
    return current_company_or_none()


@pytest.mark.django_db
def test_company_is_taken_from_kwarg():
    assert _echo_company(company_slug="htq-kz") == "htq-kz"


@pytest.mark.django_db
def test_missing_company_raises_instead_of_defaulting_to_public():
    """Молчаливый public здесь — самый дорогой из возможных дефектов:
    задача отработала бы «успешно», ничего не найдя, и никто бы не заметил.
    Тот же принцип, что и FALLBACK_MODE=strict."""
    with pytest.raises(MissingCompanyArgument):
        _echo_company()


@pytest.mark.django_db
def test_context_is_cleared_after_task():
    _echo_company(company_slug="htq-kz")
    assert current_company_or_none() is None
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_celery.py -q
```

Ожидается: `ModuleNotFoundError: No module named 'htqweb.tenancy.celery'`.

- [ ] **Шаг 3: Реализовать**

`backend/htqweb/tenancy/celery.py`:

```python
"""Компания в задачах Celery.

У задачи нет HTTP-запроса, поэтому CompanyContextMiddleware до неё не
достаёт, а contextvar в воркере пуст. Компания передаётся ЯВНЫМ аргументом
``company_slug`` — и её отсутствие является ошибкой, а не поводом взять
public.

Почему именно так: молчаливый откат на public означал бы, что задача
отработала «успешно», не найдя ни одной строки в пустой схеме. Такой дефект
не даёт ни ошибки, ни записи в лог, и обнаруживается через недели по
отсутствию результата. Это ровно тот класс подмен, ради которого на
платформе введён FALLBACK_MODE=strict.

Порядок декораторов при использовании:

    @shared_task
    @company_task
    def rebuild_something(company_slug: str, item_id: int):
        ...

company_task идёт БЛИЖЕ к функции, чтобы Celery сериализовал уже обёрнутый
вызов вместе с company_slug.
"""

from __future__ import annotations

from functools import wraps

from .db import use_company


class MissingCompanyArgument(RuntimeError):
    """Задача с @company_task вызвана без company_slug."""


def company_task(fn):
    """Развернуть kwarg ``company_slug`` в контекст компании на время задачи."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        slug = kwargs.pop("company_slug", None)
        if not slug:
            raise MissingCompanyArgument(
                f"{fn.__module__}.{fn.__qualname__} требует company_slug. "
                "Задача, работающая с данными компании, обязана получать её "
                "явно: контекста запроса в воркере нет."
            )
        with use_company(slug):
            return fn(*args, **kwargs)

    return wrapper
```

- [ ] **Шаг 4: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_celery.py -q
```

Ожидается: 3 passed.

- [ ] **Шаг 5: Коммит**

```bash
git add backend/htqweb/tenancy/celery.py backend/htqweb/tenancy/tests/test_celery.py
git commit -m "feat(tenancy): компания в задачах Celery"
```

---

## Задача 11: Сводные представления схемы `holding`

**Файлы:**
- Создать: `backend/apps/companies/services/holding_views.py`,
  `backend/apps/hr/holding.py`, `backend/apps/tasks/holding.py`,
  `backend/apps/contracts/holding.py`, `backend/apps/signoff/holding.py`
- Тест: `backend/apps/companies/tests/test_holding_views.py`

**Интерфейсы:**
- Потребляет: `active_company_slugs` (задача 4), `schema_for` и
  `HOLDING_SCHEMA` (задача 2), `settings.TENANT_APPS` (задача 5).
  `use_holding` из задачи 3 здесь НЕ нужен: DDL пишет имена схем явно, а
  `use_holding` понадобится потребителям представлений — читающим вьюхам
  холдинга, которые строятся в подпроектах 2-3.
- Производит:
  - `holding_models() -> list[type[Model]]`
  - `rebuild_holding_views() -> list[str]` — имена созданных представлений
  - соглашение: `apps/<domain>/holding.py` объявляет `HOLDING_MODELS: tuple[str, ...]`

- [ ] **Шаг 1: Написать падающий тест**

`backend/apps/companies/tests/test_holding_views.py`:

```python
import pytest
from django.db import connection

from apps.companies.models import Company, CompanyKind, CompanyStatus
from apps.companies.services import holding_views, migration_service, schema_service


@pytest.fixture
def two_companies(db):
    for slug in ("t-alpha", "t-beta"):
        Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE)
        schema_service.create_schema(slug)
        migration_service.migrate_company(slug)
    yield
    for slug in ("t-alpha", "t-beta"):
        schema_service.drop_schema(slug)


def _view_columns(name: str) -> list[str]:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'holding' AND table_name = %s "
            "ORDER BY ordinal_position",
            [name],
        )
        return [row[0] for row in cur.fetchall()]


@pytest.mark.django_db(transaction=True)
def test_rebuild_creates_view_with_company_column(two_companies):
    holding_views.rebuild_holding_views()
    columns = _view_columns("tasks_task")
    assert columns[0] == "company_slug"
    assert "id" in columns


@pytest.mark.django_db(transaction=True)
def test_view_unions_all_active_companies(two_companies):
    holding_views.rebuild_holding_views()
    with connection.cursor() as cur:
        cur.execute("SELECT DISTINCT company_slug FROM holding.tasks_task")
        # Таблицы пусты, но план запроса обязан быть валидным по обеим веткам.
        assert cur.fetchall() == []
    with connection.cursor() as cur:
        cur.execute("SELECT pg_get_viewdef('holding.tasks_task'::regclass, true)")
        definition = cur.fetchone()[0]
    assert "co_t_alpha" in definition
    assert "co_t_beta" in definition


@pytest.mark.django_db(transaction=True)
def test_archived_company_drops_out_of_view(two_companies):
    holding_views.rebuild_holding_views()
    Company.objects.filter(slug="t-beta").update(status=CompanyStatus.ARCHIVED)
    holding_views.rebuild_holding_views()
    with connection.cursor() as cur:
        cur.execute("SELECT pg_get_viewdef('holding.tasks_task'::regclass, true)")
        definition = cur.fetchone()[0]
    assert "co_t_alpha" in definition
    assert "co_t_beta" not in definition


@pytest.mark.django_db(transaction=True)
def test_rebuild_is_idempotent(two_companies):
    first = holding_views.rebuild_holding_views()
    second = holding_views.rebuild_holding_views()
    assert first == second


@pytest.mark.django_db(transaction=True)
def test_view_columns_match_the_model(two_companies):
    """Ловит забытый rebuild после миграции, добавившей столбец."""
    from apps.tasks.models import Task

    holding_views.rebuild_holding_views()
    model_columns = {f.column for f in Task._meta.concrete_fields}
    view_columns = set(_view_columns("tasks_task")) - {"company_slug"}
    assert view_columns == model_columns


@pytest.mark.django_db(transaction=True)
def test_no_active_companies_means_no_views(db):
    """Схема holding существует, но представлений нет — а не битые вьюхи
    поверх несуществующих схем."""
    assert holding_views.rebuild_holding_views() == []
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_holding_views.py -q
```

Ожидается: `ImportError: cannot import name 'holding_views'`.

- [ ] **Шаг 3: Объявить сводимые модели в аппках**

`backend/apps/tasks/holding.py`:

```python
"""Модели tasks, попадающие в сводные представления схемы holding.

Соглашение автообнаружения — то же, что у apps/<domain>/metrics.py и
AppConfig.API_PREFIX: apps.companies находит этот модуль сам, межаппных
импортов не возникает и test_app_isolation остаётся зелёным.

Список намеренно КОРОТКИЙ. Сводить все ~40 моделей аппки незачем: каждое
представление — это UNION ALL по числу компаний, и стоимость их
пересоздания растёт произведением. Здесь только то, что реально нужно
дашборду холдинга.
"""

HOLDING_MODELS = ("Project", "Site", "Task", "DailyReport", "ProjectStaffReport")
```

`backend/apps/hr/holding.py`:

```python
"""Модели hr для сводных представлений холдинга. См. apps/tasks/holding.py."""

HOLDING_MODELS = ("Employee", "Department", "Position")
```

`backend/apps/contracts/holding.py`:

```python
"""Модели contracts для сводных представлений холдинга.

Именно ради этих цифр (бюджеты и договоры по всей группе) заказчик выбрал
живое сводное чтение вместо предрассчитанной витрины.
"""

HOLDING_MODELS = ("Budget", "Agreement", "Invoice", "Counterparty")
```

`backend/apps/signoff/holding.py`:

```python
"""Модели signoff для сводных представлений холдинга.

Нужны, чтобы холдинг видел зависшие согласования по всем компаниям сразу —
это главный источник срыва сроков.
"""

HOLDING_MODELS = ("ApprovalProcess", "ApprovalTask")
```

- [ ] **Шаг 4: Реализовать сборку представлений**

`backend/apps/companies/services/holding_views.py`:

```python
"""Сводные UNION ALL-представления поверх схем всех действующих компаний.

Почему представления, а не склейка в Python: склейка ломает сортировку и
пагинацию — чтобы отдать третью страницу списка, отсортированного по сроку,
пришлось бы вытащить по три страницы из каждой схемы, слить в памяти и
отрезать. Postgres на UNION ALL строит план Append и проталкивает условия
внутрь веток, поэтому фильтр по дате не читает лишние схемы целиком.

Ограничение, принятое сознательно: в представление попадают только столбцы
модели. Компания, отставшая по миграциям и не имеющая нового столбца,
сломала бы представление — поэтому новое поле становится видно холдингу
только после того, как мигрированы все. Ловится тестом
test_view_columns_match_the_model.
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.conf import settings
from django.db import connection
from django.utils.module_loading import module_has_submodule
from psycopg import sql

from htqweb.tenancy.context import HOLDING_SCHEMA, schema_for

from ..interface import active_company_slugs


def holding_models() -> list[type]:
    """Модели tenant-аппок, объявленные в apps/<domain>/holding.py.

    Автообнаружение, а не список в одном месте: иначе добавление сводимой
    модели правило бы файл в чужой аппке — та же точка конфликта, которую
    сняло автомонтирование URL по API_PREFIX.
    """
    found: list[type] = []
    for config in django_apps.get_app_configs():
        if config.label not in settings.TENANT_APPS:
            continue
        if not module_has_submodule(config.module, "holding"):
            continue
        module = __import__(f"{config.name}.holding", fromlist=["HOLDING_MODELS"])
        for model_name in getattr(module, "HOLDING_MODELS", ()):
            found.append(django_apps.get_model(config.label, model_name))
    return found


def _branch(slug: str, model: type) -> sql.Composed:
    columns = [sql.Identifier(f.column) for f in model._meta.concrete_fields]
    return sql.SQL("SELECT {slug} AS company_slug, {cols} FROM {schema}.{table}").format(
        slug=sql.Literal(slug),
        cols=sql.SQL(", ").join(columns),
        schema=sql.Identifier(schema_for(slug)),
        table=sql.Identifier(model._meta.db_table),
    )


def rebuild_holding_views() -> list[str]:
    """Пересоздать все сводные представления. Идемпотентна.

    Вызывается ровно в трёх событиях: компанию создали, заархивировали,
    восстановили. Возвращает имена созданных представлений в стабильном
    порядке — на него опирается тест идемпотентности.
    """
    slugs = active_company_slugs()
    created: list[str] = []

    with connection.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(HOLDING_SCHEMA),
            )
        )
        for model in sorted(holding_models(), key=lambda m: m._meta.db_table):
            table = model._meta.db_table
            cur.execute(
                sql.SQL("DROP VIEW IF EXISTS {}.{}").format(
                    sql.Identifier(HOLDING_SCHEMA), sql.Identifier(table),
                )
            )
            if not slugs:
                # Ни одной действующей компании — представление не над чем
                # строить. Пустая вьюха с фиктивной веткой была бы хуже:
                # она бы притворялась работающей.
                continue
            body = sql.SQL(" UNION ALL ").join(_branch(s, model) for s in slugs)
            cur.execute(
                sql.SQL("CREATE VIEW {}.{} AS {}").format(
                    sql.Identifier(HOLDING_SCHEMA), sql.Identifier(table), body,
                )
            )
            created.append(table)

    return created
```

- [ ] **Шаг 5: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_holding_views.py -q
```

Ожидается: 6 passed.

- [ ] **Шаг 6: Прогнать тест изоляции аппок**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/core/tests/test_app_isolation.py -q
```

Ожидается: passed. `holding_models()` берёт модели через
`django_apps.get_model`, а не импортом чужого модуля.

- [ ] **Шаг 7: Коммит**

```bash
git add backend/apps/companies/services/holding_views.py backend/apps/hr/holding.py backend/apps/tasks/holding.py backend/apps/contracts/holding.py backend/apps/signoff/holding.py backend/apps/companies/tests/test_holding_views.py
git commit -m "feat(companies): сводные представления схемы holding"
```

---

## Задача 12: Команда создания компании

**Файлы:**
- Создать: `backend/apps/companies/management/commands/company_create.py`
- Тест: `backend/apps/companies/tests/test_company_create.py`

**Интерфейсы:**
- Потребляет: `create_schema` (5), `migrate_company` (6),
  `rebuild_holding_views` (11).
- Производит: команда `manage.py company_create <slug> --name "..." --kind ... [--parent ...]`.

- [ ] **Шаг 1: Написать падающий тест**

`backend/apps/companies/tests/test_company_create.py`:

```python
import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from apps.companies.models import Company, CompanyKind
from apps.companies.services import schema_service


@pytest.fixture(autouse=True)
def cleanup():
    yield
    schema_service.drop_schema("t-new")


@pytest.mark.django_db(transaction=True)
def test_creates_row_schema_and_tables():
    call_command("company_create", "t-new", name="Новая", kind="service")

    assert Company.objects.filter(slug="t-new").exists()
    assert schema_service.schema_exists("t-new")
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'co_t_new' AND table_name = 'tasks_task'"
        )
        assert cur.fetchone() is not None


@pytest.mark.django_db(transaction=True)
def test_rejects_invalid_slug():
    with pytest.raises(CommandError):
        call_command("company_create", "Плохой_Slug", name="X", kind="service")


@pytest.mark.django_db(transaction=True)
def test_rejects_duplicate_slug():
    Company.objects.create(slug="t-new", name="Уже есть", kind=CompanyKind.SERVICE)
    with pytest.raises(CommandError):
        call_command("company_create", "t-new", name="Дубль", kind="service")
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_company_create.py -q
```

Ожидается: `CommandError: Unknown command: 'company_create'`.

- [ ] **Шаг 3: Реализовать**

`backend/apps/companies/management/commands/company_create.py`:

```python
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.companies.models import Company, CompanyKind
from apps.companies.services import holding_views, migration_service, schema_service


class Command(BaseCommand):
    help = "Завести компанию: строка реестра, схема Postgres, миграции, представления."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--name", required=True)
        parser.add_argument("--kind", required=True, choices=[c.value for c in CompanyKind])
        parser.add_argument("--parent", help="slug вышестоящей компании")
        parser.add_argument("--country", default="")

    def handle(self, *args, **opts):
        slug = opts["slug"]
        if Company.objects.filter(slug=slug).exists():
            raise CommandError(f"Компания {slug} уже существует.")

        parent = None
        if opts["parent"]:
            parent = Company.objects.filter(slug=opts["parent"]).first()
            if parent is None:
                raise CommandError(f"Вышестоящая компания {opts['parent']} не найдена.")

        company = Company(slug=slug, name=opts["name"], kind=opts["kind"],
                          parent=parent, country=opts["country"])
        try:
            company.full_clean()
        except ValidationError as exc:
            raise CommandError("; ".join(
                f"{field}: {' '.join(msgs)}" for field, msgs in exc.message_dict.items()
            ))

        # Строка реестра и схема создаются в одной транзакции, а миграции —
        # после её фиксации: DDL сотни таблиц в открытой транзакции держал бы
        # блокировки всё время прогона.
        with transaction.atomic():
            company.save()
            schema_service.create_schema(slug)

        try:
            migration_service.migrate_company(slug)
        except Exception:
            # Схема без таблиц опаснее её отсутствия: компания выглядела бы
            # заведённой и падала бы на первом же запросе.
            schema_service.drop_schema(slug)
            company.delete()
            raise

        holding_views.rebuild_holding_views()
        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug} создана, схема co_{slug.replace('-', '_')} готова."
        ))
```

- [ ] **Шаг 4: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_company_create.py -q
```

Ожидается: 3 passed.

- [ ] **Шаг 5: Коммит**

```bash
git add backend/apps/companies/management/commands/company_create.py backend/apps/companies/tests/test_company_create.py
git commit -m "feat(companies): команда создания компании"
```

---

## Задача 13: Перенос боевых данных в схему первой компании

**Файлы:**
- Создать: `backend/apps/companies/management/commands/tenancy_bootstrap.py`
- Тест: `backend/apps/companies/tests/test_tenancy_bootstrap.py`

**Интерфейсы:**
- Потребляет: `create_schema` (5), `rebuild_holding_views` (11),
  `settings.TENANT_APPS` (5).
- Производит: команда
  `manage.py tenancy_bootstrap --slug <slug> --name "..." --kind holding [--dry-run]`.

- [ ] **Шаг 1: Написать падающий тест**

`backend/apps/companies/tests/test_tenancy_bootstrap.py`:

```python
import pytest
from django.core.management import call_command
from django.db import connection

from apps.companies.models import Company
from apps.companies.services import schema_service


@pytest.fixture(autouse=True)
def cleanup():
    yield
    schema_service.drop_schema("t-root")


def _schema_of(table: str) -> str | None:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = %s",
            [table],
        )
        row = cur.fetchone()
        return row[0] if row else None


@pytest.mark.django_db(transaction=True)
def test_dry_run_changes_nothing():
    call_command("tenancy_bootstrap", slug="t-root", name="Корень",
                 kind="holding", dry_run=True)
    assert not Company.objects.filter(slug="t-root").exists()
    assert _schema_of("tasks_task") == "public"


@pytest.mark.django_db(transaction=True)
def test_moves_tenant_tables_out_of_public():
    call_command("tenancy_bootstrap", slug="t-root", name="Корень", kind="holding")
    assert _schema_of("tasks_task") == "co_t_root"
    assert _schema_of("hr_employee") == "co_t_root"


@pytest.mark.django_db(transaction=True)
def test_leaves_shared_tables_in_public():
    call_command("tenancy_bootstrap", slug="t-root", name="Корень", kind="holding")
    assert _schema_of("users_user") == "public"
    assert _schema_of("companies_company") == "public"


@pytest.mark.django_db(transaction=True)
def test_migration_state_travels_with_the_tables():
    """Строки django_migrations для перенесённых аппок обязаны оказаться в
    схеме компании, иначе migrate_companies решит, что схема пуста, и
    попробует создать таблицы поверх уже существующих."""
    call_command("tenancy_bootstrap", slug="t-root", name="Корень", kind="holding")
    with connection.cursor() as cur:
        cur.execute("SELECT DISTINCT app FROM co_t_root.django_migrations")
        apps_in_schema = {row[0] for row in cur.fetchall()}
    assert apps_in_schema == {"hr", "tasks", "contracts", "signoff"}
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_tenancy_bootstrap.py -q
```

Ожидается: `CommandError: Unknown command: 'tenancy_bootstrap'`.

- [ ] **Шаг 3: Реализовать**

`backend/apps/companies/management/commands/tenancy_bootstrap.py`:

```python
"""Одноразовый перевод существующей базы в мультикомпанейный режим.

Все текущие данные сводятся в ОДНУ компанию: расщепление на реальные
юридические лица делается позже средствами платформы, когда структура
устоится.

Перенос — ALTER TABLE ... SET SCHEMA, а не копирование: это правка
системного каталога, данные физически не двигаются, поэтому команда
отрабатывает мгновенно независимо от объёма, а простой равен длительности
блокировки. Обратная операция симметрична.
"""

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from psycopg import sql

from apps.companies.models import Company, CompanyKind
from apps.companies.services import holding_views, schema_service
from htqweb.tenancy.context import schema_for


class Command(BaseCommand):
    help = ("Одноразово перенести существующие данные hr/tasks/contracts/signoff "
            "из public в схему первой компании.")

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--kind", default=CompanyKind.HOLDING,
                            choices=[c.value for c in CompanyKind])
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def _tenant_tables(self) -> list[str]:
        tables = []
        for label in settings.TENANT_APPS:
            for model in django_apps.get_app_config(label).get_models():
                tables.append(model._meta.db_table)
        return sorted(tables)

    def handle(self, *args, **opts):
        slug, schema = opts["slug"], schema_for(opts["slug"])
        tables = self._tenant_tables()

        if opts["dry_run"]:
            self.stdout.write(f"Сухой прогон. Схема: {schema}")
            self.stdout.write(f"Таблиц к переносу: {len(tables)}")
            for table in tables:
                self.stdout.write(f"  {table}")
            return

        if Company.objects.filter(slug=slug).exists():
            raise CommandError(f"Компания {slug} уже существует — bootstrap одноразовый.")

        with transaction.atomic():
            company = Company(slug=slug, name=opts["name"], kind=opts["kind"])
            company.full_clean()
            company.save()
            schema_service.create_schema(slug)

            with connection.cursor() as cur:
                for table in tables:
                    cur.execute(
                        sql.SQL("ALTER TABLE IF EXISTS public.{} SET SCHEMA {}").format(
                            sql.Identifier(table), sql.Identifier(schema),
                        )
                    )

                # Состояние миграций обязано переехать вместе с таблицами:
                # иначе migrate_companies сочтёт схему пустой и попробует
                # создать таблицы поверх уже существующих.
                cur.execute(
                    sql.SQL(
                        "CREATE TABLE {}.django_migrations "
                        "(LIKE public.django_migrations INCLUDING ALL)"
                    ).format(sql.Identifier(schema))
                )
                cur.execute(
                    sql.SQL(
                        "INSERT INTO {}.django_migrations (app, name, applied) "
                        "SELECT app, name, applied FROM public.django_migrations "
                        "WHERE app = ANY(%s)"
                    ).format(sql.Identifier(schema)),
                    [list(settings.TENANT_APPS)],
                )
                cur.execute(
                    "DELETE FROM public.django_migrations WHERE app = ANY(%s)",
                    [list(settings.TENANT_APPS)],
                )

        holding_views.rebuild_holding_views()
        self.stdout.write(self.style.SUCCESS(
            f"Перенесено {len(tables)} таблиц в {schema}. Компания {slug} создана."
        ))
```

- [ ] **Шаг 4: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_tenancy_bootstrap.py -q
```

Ожидается: 4 passed.

- [ ] **Шаг 5: Отключить автомиграцию tenant-аппок при старте контейнера**

В `backend/entrypoint.sh` (или там, где выполняется `migrate` под
`RUN_MIGRATIONS=1` — найдите его `grep -rn "RUN_MIGRATIONS" backend/ docker-compose.yml`)
заменить безусловный `manage.py migrate` на прогон только общих аппок:

```bash
# Схемы компаний при старте НЕ мигрируются: их N, прогон занимает минуты и
# уронил бы контейнер по таймауту. Для них есть отдельная команда, которая
# запускается выкаткой осознанно:
#   manage.py migrate_companies
python manage.py migrate --skip-checks
```

Django мигрирует только то, что найдёт в `search_path`, а он при старте
равен `public` — то есть tenant-аппки останутся нетронутыми автоматически.
Добавьте следом информационную строку:

```bash
echo "Схемы компаний не мигрированы. Запустите: manage.py migrate_companies"
```

- [ ] **Шаг 6: Коммит**

```bash
git add backend/apps/companies/management/commands/tenancy_bootstrap.py backend/apps/companies/tests/test_tenancy_bootstrap.py backend/entrypoint.sh
git commit -m "feat(companies): перенос существующих данных в схему первой компании"
```

---

## Задача 14: Фикстуры компаний для тестов

**Файлы:**
- Изменить: `backend/conftest.py`
- Тест: `backend/apps/companies/tests/test_fixtures.py`

**Интерфейсы:**
- Потребляет: всё из задач 1-11.
- Производит: фикстуры `company_schema`, `company_context`, `two_company_schemas`.

- [ ] **Шаг 1: Написать падающий тест**

`backend/apps/companies/tests/test_fixtures.py`:

```python
import pytest

from htqweb.tenancy.context import current_company_or_none


@pytest.mark.django_db(transaction=True)
def test_company_context_fixture_sets_context(company_context):
    assert current_company_or_none() == company_context["slug"]


@pytest.mark.django_db(transaction=True)
def test_data_written_in_one_company_is_invisible_in_another(two_company_schemas):
    """Главный тест всей архитектуры: изоляция обеспечивается СУБД."""
    from apps.hr.models import Department
    from htqweb.tenancy.db import use_company

    alpha, beta = two_company_schemas

    with use_company(alpha):
        Department.objects.create(name="Отдел A", path="a")
        assert Department.objects.count() == 1

    with use_company(beta):
        assert Department.objects.count() == 0
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_fixtures.py -q
```

Ожидается: `fixture 'company_context' not found`.

- [ ] **Шаг 3: Добавить фикстуры**

В конец `backend/conftest.py`:

```python
@pytest.fixture
def company_schema(db):
    """Одна компания с полностью мигрированной схемой.

    transaction=True на тесте обязателен: CREATE SCHEMA и прогон миграций —
    DDL, и внутри отката транзакции pytest-django они бы не сохранились.
    """
    from apps.companies.models import Company, CompanyKind
    from apps.companies.services import migration_service, schema_service

    slug = "t-fixture"
    company = Company.objects.create(slug=slug, name="Фикстура",
                                     kind=CompanyKind.SERVICE)
    schema_service.create_schema(slug)
    migration_service.migrate_company(slug)
    yield {"slug": slug, "id": company.id}
    schema_service.drop_schema(slug)


@pytest.fixture
def company_context(company_schema):
    """Компания из company_schema, установленная как текущая."""
    from htqweb.tenancy.db import use_company

    with use_company(company_schema["slug"]):
        yield company_schema


@pytest.fixture
def two_company_schemas(db):
    """Две мигрированные схемы — для проверок изоляции между компаниями."""
    from apps.companies.models import Company, CompanyKind
    from apps.companies.services import migration_service, schema_service

    slugs = ("t-alpha", "t-beta")
    for slug in slugs:
        Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE)
        schema_service.create_schema(slug)
        migration_service.migrate_company(slug)
    yield slugs
    for slug in slugs:
        schema_service.drop_schema(slug)
```

- [ ] **Шаг 4: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_fixtures.py -q
```

Ожидается: 2 passed.

- [ ] **Шаг 5: Прогнать весь набор**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest -q
```

Ожидается: число падений не выросло относительно базового.

- [ ] **Шаг 6: Коммит**

```bash
git add backend/conftest.py backend/apps/companies/tests/test_fixtures.py
git commit -m "test: фикстуры компаний-схем"
```

---

## Задача 15: nginx — поддомен компании

**Файлы:**
- Изменить: `infra/nginx/default.conf:52-54`
- Тест: ручная проверка (конфигурация nginx юнит-тестами не покрывается)

**Интерфейсы:**
- Потребляет: `COMPANY_HEADER` (задача 7).
- Производит: заголовок `X-HTQ-Company` во всех проксируемых запросах.

- [ ] **Шаг 1: Изменить `server_name` и добавить проброс заголовка**

В `infra/nginx/default.conf` заменить блок `server_name _;` на:

```nginx
    # Компания определяется поддоменом: kz.example.kz -> компания "kz".
    # Именованная группа $company попадает в заголовок, который читает
    # htqweb.middleware.company_context.CompanyContextMiddleware.
    #
    # Регулярка не покрывает обращение по голому домену и по IP — там
    # $company пуст, запрос обслуживается в public, и это штатный режим
    # общих доменов (users/cms/media).
    server_name ~^(?<company>[a-z0-9-]+)\.(?<root>.+)$;

    # Заголовок ставится ЖЁСТКО, затирая присланный клиентом: иначе любой
    # желающий выбирал бы себе компанию сам, отправив свой X-HTQ-Company.
    proxy_set_header X-HTQ-Company $company;
```

Найдите все блоки `location`, содержащие `proxy_pass`, и убедитесь, что
директива `proxy_set_header X-HTQ-Company $company;` действует на каждый —
в nginx `proxy_set_header` не наследуется в `location`, если внутри него
объявлен хотя бы один свой `proxy_set_header`. Продублируйте её в таких
блоках.

- [ ] **Шаг 2: Проверить синтаксис**

```bash
docker compose -f docker-compose.test-local.yml run --rm --no-deps nginx nginx -t
```

Ожидается: `syntax is ok`, `test is successful`.

- [ ] **Шаг 3: Проверить проброс вручную**

```bash
docker compose -f docker-compose.test-local.yml up -d
curl -s -H "Host: kz.example.kz" http://localhost/api/users/v1/me
```

Ожидается: 404 с телом `{"detail": "Компания не найдена"}` — компании `kz` в
базе разработки нет, значит заголовок дошёл и был обработан middleware.
Признак того, что заголовок НЕ пробрасывается: приходит 401
(`{"detail": "Not authenticated"}`) — запрос дошёл до `api_view` мимо
проверки компании. В этом случае вернитесь к шагу 1 и проверьте, не
перекрыт ли `proxy_set_header` внутри `location`.

- [ ] **Шаг 4: Коммит**

```bash
git add infra/nginx/default.conf
git commit -m "feat(nginx): компания из поддомена в заголовок X-HTQ-Company"
```

---

## Задача 16: Вход и переключение компании на фронте

**Файлы:**
- Изменить: `frontend/src/lib/auth/profileStorage.ts`
- Создать: `frontend/src/lib/auth/companySwitch.ts`,
  `frontend/src/lib/auth/companySwitch.test.ts`

**Интерфейсы:**
- Потребляет: claim `company` (задача 8).
- Производит:
  - `REFRESH_COOKIE_DOMAIN: string`
  - `switchCompany(slug: string): void`
  - `companyFromHost(host: string): string | null`

- [ ] **Шаг 1: Написать падающий тест**

`frontend/src/lib/auth/companySwitch.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';

import { companyFromHost, parentDomain } from './companySwitch';

describe('companyFromHost', () => {
  it('извлекает компанию из поддомена', () => {
    expect(companyFromHost('kz.example.kz')).toBe('kz');
    expect(companyFromHost('htq-uz.example.kz')).toBe('htq-uz');
  });

  it('возвращает null для голого домена', () => {
    expect(companyFromHost('example.kz')).toBeNull();
  });

  it('возвращает null для localhost без поддомена', () => {
    expect(companyFromHost('localhost')).toBeNull();
  });

  it('работает с localhost-поддоменами в разработке', () => {
    expect(companyFromHost('kz.localhost')).toBe('kz');
  });

  it('игнорирует порт', () => {
    expect(companyFromHost('kz.localhost:3000')).toBe('kz');
  });
});

describe('parentDomain', () => {
  it('отбрасывает поддомен компании', () => {
    // Домен refresh-cookie: он обязан быть общим для всех компаний,
    // иначе переключение выглядит как разлогин.
    expect(parentDomain('kz.example.kz')).toBe('.example.kz');
  });

  it('оставляет голый домен как есть', () => {
    expect(parentDomain('example.kz')).toBe('.example.kz');
  });

  it('не ставит точку перед localhost', () => {
    expect(parentDomain('kz.localhost')).toBe('localhost');
  });
});
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd frontend
npx vitest run src/lib/auth/companySwitch.test.ts
```

Ожидается: `Failed to resolve import "./companySwitch"`.

- [ ] **Шаг 3: Реализовать**

`frontend/src/lib/auth/companySwitch.ts`:

```typescript
/**
 * Компания определяется поддоменом, поэтому переключение компании — это
 * навигация, а не запрос к API.
 *
 * Главная сложность: localStorage привязан к origin, поэтому access-токен,
 * сохранённый на kz.example.kz, недоступен на uz.example.kz. Чтобы переход
 * не выглядел разлогином, refresh-токен живёт в cookie на РОДИТЕЛЬСКОМ
 * домене — cookie, в отличие от localStorage, общая для всех поддоменов.
 * На новом поддомене SPA не находит access-токен, обменивает refresh-cookie
 * на новый и продолжает работу.
 */

/** Компания из имени хоста, или null если поддомена нет. */
export const companyFromHost = (host: string): string | null => {
  const withoutPort = host.split(':')[0];
  const labels = withoutPort.split('.');
  // 'example.kz' -> 2 метки, поддомена нет. 'localhost' -> 1 метка.
  if (labels.length < 2) {
    return null;
  }
  if (labels.length === 2 && labels[1] !== 'localhost') {
    return null;
  }
  return labels[0];
};

/**
 * Домен для refresh-cookie: общий для всех компаний.
 *
 * localhost — особый случай: браузеры отвергают cookie с Domain=.localhost,
 * поэтому там домен указывается без ведущей точки.
 */
export const parentDomain = (host: string): string => {
  const withoutPort = host.split(':')[0];
  const labels = withoutPort.split('.');
  const tail = labels.length > 2 ? labels.slice(1) : labels;
  const joined = tail.join('.');
  return joined.endsWith('localhost') ? 'localhost' : `.${joined}`;
};

/** Перейти в другую компанию, сохранив текущий путь. */
export const switchCompany = (slug: string): void => {
  const { host, pathname, search, protocol } = window.location;
  const tail = parentDomain(host).replace(/^\./, '');
  const port = host.includes(':') ? `:${host.split(':')[1]}` : '';
  window.location.assign(`${protocol}//${slug}.${tail}${port}${pathname}${search}`);
};
```

- [ ] **Шаг 4: Прогнать тест**

```bash
cd frontend
npx vitest run src/lib/auth/companySwitch.test.ts
```

Ожидается: 8 passed.

- [ ] **Шаг 5: Использовать родительский домен для refresh-cookie**

В `frontend/src/lib/auth/profileStorage.ts`, в функции записи cookie
(строка 82, где формируется `document.cookie`), добавить атрибут `Domain`:

```typescript
import { parentDomain } from './companySwitch';

// ...в функции записи cookie, к существующей строке:
const domainAttr = `; Domain=${parentDomain(window.location.host)}`;
document.cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; Expires=${expiresAt}; Path=/${domainAttr}; SameSite=Lax${secureAttr}`;
```

Ту же правку внести в функцию удаления cookie (строка 91) — cookie
удаляется только тем же набором атрибутов, которым была поставлена, иначе
останется висеть.

- [ ] **Шаг 6: Проверить типы и весь набор тестов**

```bash
cd frontend
npx tsc --noEmit -p tsconfig.json
npm test
```

Ожидается: типы чисты, число падающих тестов не выросло.

- [ ] **Шаг 7: Коммит**

```bash
git add frontend/src/lib/auth/companySwitch.ts frontend/src/lib/auth/companySwitch.test.ts frontend/src/lib/auth/profileStorage.ts
git commit -m "feat(frontend): переключение компании по поддомену"
```

---

## Задача 17: Видимость отставания схем — админка и метрика

**Файлы:**
- Создать: `backend/apps/companies/admin.py`, `backend/apps/companies/metrics.py`
- Тест: `backend/apps/companies/tests/test_metrics.py`

**Интерфейсы:**
- Потребляет: `CompanySchemaVersion`, `Company` (задача 1),
  `settings.TENANT_APPS` (задача 5).
- Производит: `collect() -> dict` по соглашению `apps/<domain>/metrics.py`;
  регистрация моделей в `/django-admin/`.

**Контракт сборщика — проверен по `apps/conference/metrics.py`, не выдуман.**
Возвращается `dict[str, dict]`, где значение имеет форму
`{"help": str, "labels": [str] (необязательно), "values": [(кортеж_меток, число)]}`.
Имена метрик **без** префикса `htqweb_` — его навешивает `apps.core.metrics`
при экспорте. Плоский `dict[str, float]` собрался бы без ошибки и молча не
попал бы в экспорт.

Спека требует, чтобы отставание схемы было видно **до** того, как проявится
500-й ошибкой. Разные версии у разных компаний — штатный режим, поэтому
отставание нельзя показывать как аварию, но и молчать о нём нельзя.

- [ ] **Шаг 1: Написать падающий тест**

`backend/apps/companies/tests/test_metrics.py`:

```python
import pytest

from apps.companies import metrics
from apps.companies.models import (
    Company, CompanyKind, CompanySchemaVersion, CompanyStatus,
)


def _single(result: dict, name: str) -> float:
    """Значение метрики без меток. Форма values — [(кортеж_меток, число)]."""
    return result[name]["values"][0][1]


@pytest.mark.django_db
def test_active_companies_are_grouped_by_kind():
    Company.objects.create(slug="htq", name="Холдинг", kind=CompanyKind.HOLDING)
    Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    Company.objects.create(slug="dead", name="Банкрот", kind=CompanyKind.SERVICE,
                           status=CompanyStatus.ARCHIVED)

    result = metrics.collect()
    by_kind = dict(result["companies_active_by_kind"]["values"])
    assert by_kind[("holding",)] == 1
    assert by_kind[("regional",)] == 1
    assert ("service",) not in by_kind  # архивная не считается действующей
    assert _single(result, "companies_archived") == 1


@pytest.mark.django_db
def test_metric_names_carry_no_prefix():
    """Префикс htqweb_ навешивает apps.core.metrics при экспорте.

    Вшитый здесь префикс дал бы htqweb_htqweb_* и метрику, которую не
    найдёт ни один дашборд.
    """
    assert all(not name.startswith("htqweb_") for name in metrics.collect())


@pytest.mark.django_db
def test_counts_schemas_behind_target():
    kz = Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    CompanySchemaVersion.objects.create(
        company=kz, app_label="tasks",
        applied_migration="0039_x", target_migration="0042_y",
    )
    CompanySchemaVersion.objects.create(
        company=kz, app_label="hr",
        applied_migration="0012_z", target_migration="0012_z",
    )
    assert _single(metrics.collect(), "company_schemas_behind") == 1


@pytest.mark.django_db
def test_counts_schemas_with_error():
    kz = Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    CompanySchemaVersion.objects.create(
        company=kz, app_label="tasks", last_error="relation does not exist",
    )
    assert _single(metrics.collect(), "company_schema_errors") == 1


@pytest.mark.django_db
def test_empty_registry_reports_zeros_not_nothing():
    """Здесь ноль — настоящий ноль, а не «сборщик умер»: строк в реестре
    просто нет, и это отличается от случая пустого кэша в apps.core.metrics.
    """
    result = metrics.collect()
    assert result["companies_active_by_kind"]["values"] == []
    assert _single(result, "companies_archived") == 0
```

- [ ] **Шаг 2: Убедиться, что тест падает**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_metrics.py -q
```

Ожидается: `ModuleNotFoundError: No module named 'apps.companies.metrics'`.

- [ ] **Шаг 3: Реализовать метрики**

`backend/apps/companies/metrics.py`:

```python
"""Бизнес-метрики реестра компаний.

Соглашение то же, что у остальных apps/<domain>/metrics.py: apps.core.metrics
находит и сливает этот collect() сам, межаппных импортов не возникает.
Считается Celery-beat'ом раз в 60 секунд в кэш, а не на скрейп.

Отставание схемы — не авария: разные компании намеренно обновляются с разной
скоростью (см. expand/contract). Метрика нужна, чтобы отставание было ВИДНО;
порог алерта задаётся в Grafana, а не здесь.

Форма возврата — та же, что у apps/conference/metrics.py: словарь
{имя: {"help", "labels"?, "values": [(кортеж_меток, число)]}}, имена БЕЗ
префикса htqweb_ (его добавляет apps.core.metrics при экспорте).
"""

from django.db.models import Count, F

from .models import Company, CompanySchemaVersion, CompanyStatus


def collect() -> dict:
    by_kind = (Company.objects
               .filter(status=CompanyStatus.ACTIVE)
               .values("kind")
               .annotate(n=Count("id"))
               .order_by("kind"))
    archived = Company.objects.filter(status=CompanyStatus.ARCHIVED).count()

    # Пустая target_migration означает «прогона ещё не было» — это не
    # отставание, а отсутствие данных, и считать его отставанием значило бы
    # поднимать тревогу на каждой только что заведённой компании.
    behind = (CompanySchemaVersion.objects
              .exclude(target_migration="")
              .exclude(applied_migration=F("target_migration"))
              .count())
    errors = CompanySchemaVersion.objects.exclude(last_error="").count()

    return {
        "companies_active_by_kind": {
            "help": "Действующие компании по типу",
            "labels": ["kind"],
            "values": [((row["kind"],), row["n"]) for row in by_kind],
        },
        "companies_archived": {
            "help": "Компании в архиве",
            "values": [((), archived)],
        },
        "company_schemas_behind": {
            "help": "Схемы компаний, отставшие от целевой миграции",
            "values": [((), behind)],
        },
        "company_schema_errors": {
            "help": "Схемы компаний с ошибкой последнего прогона миграций",
            "values": [((), errors)],
        },
    }
```

- [ ] **Шаг 4: Прогнать тест**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies/tests/test_metrics.py -q
```

Ожидается: 4 passed.

- [ ] **Шаг 5: Зарегистрировать модели в админке**

`backend/apps/companies/admin.py`:

```python
from django.contrib import admin

from .models import (
    Company, CompanyMembership, CompanyModule, CompanySchemaVersion,
    CompanyServiceLink,
)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "kind", "status", "parent", "country")
    list_filter = ("kind", "status")
    search_fields = ("name", "slug")
    # slug задаёт имя схемы Postgres: после создания компании его смена
    # означала бы переименование схемы, чего эта форма не делает.
    readonly_fields = ("slug",)


@admin.register(CompanySchemaVersion)
class CompanySchemaVersionAdmin(admin.ModelAdmin):
    """Та самая страница «версии схем по компаниям».

    Нужна, чтобы отставание схемы обнаруживалось здесь, а не по 500-й
    ошибке в проде. Полностью только для чтения: версия меняется прогоном
    migrate_companies, и правка её руками сделала бы таблицу лживой.
    """

    list_display = ("company", "app_label", "applied_migration",
                    "target_migration", "last_run_at", "last_error")
    list_filter = ("app_label", "company")
    readonly_fields = tuple(f.name for f in CompanySchemaVersion._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CompanyModule)
class CompanyModuleAdmin(admin.ModelAdmin):
    list_display = ("company", "app_label", "enabled", "updated_at")
    list_filter = ("enabled", "app_label")


@admin.register(CompanyMembership)
class CompanyMembershipAdmin(admin.ModelAdmin):
    list_display = ("user_id", "company", "is_default")
    list_filter = ("company", "is_default")
    search_fields = ("user_id",)


@admin.register(CompanyServiceLink)
class CompanyServiceLinkAdmin(admin.ModelAdmin):
    list_display = ("provider", "consumer", "created_at")
    list_filter = ("provider", "consumer")
```

- [ ] **Шаг 6: Проверить, что админка рендерится**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest apps/companies -q
./.venv/Scripts/python.exe manage.py check
```

Ожидается: тесты зелёные, `System check identified no issues`.

- [ ] **Шаг 7: Коммит**

```bash
git add backend/apps/companies/metrics.py backend/apps/companies/admin.py backend/apps/companies/tests/test_metrics.py
git commit -m "feat(companies): метрики отставания схем и админка реестра"
```

---

## Задача 18: Документация

**Файлы:**
- Изменить: `CLAUDE.md`, `backend/README.md`, `STRUCTURE.md`

- [ ] **Шаг 1: Дописать раздел в `CLAUDE.md`**

После раздела «Postgres — direct connection now» добавить:

````markdown
## Мультикомпанейность — схема на компанию

Компании группы изолированы **схемами Postgres**: `hr`, `tasks`, `contracts`,
`signoff` (`settings.TENANT_APPS`) живут в `co_<slug>`, всё остальное — в
`public`. Разводит их `search_path`, который ставит
`htqweb.middleware.company_context.CompanyContextMiddleware` по заголовку
`X-HTQ-Company` (его подставляет nginx из поддомена). **Модели tenant-аппок
поэтому НЕ содержат поля компании — не добавляйте его.**

- **Контекст компании обязателен.** `htqweb.tenancy.current_company()`
  поднимает `NoCompanyContext`, если контекст не установлен. Это намеренно:
  молчаливый откат на `public` дал бы «успешно отработавший» код, не нашедший
  ни одной строки.
- **В Celery компания передаётся явно.** `@company_task` + kwarg
  `company_slug`; без него — `MissingCompanyArgument`.
- **Миграции НЕ идут при старте контейнера.** `RUN_MIGRATIONS=1` мигрирует
  только `public`. Схемы компаний — `manage.py migrate_companies` осознанно
  во время выкатки. Разные компании могут стоять на разных версиях — это
  штатный режим, поэтому **любое изменение схемы делается по expand/contract**:
  сначала обратно-совместимый шаг, разрушающий — отдельной миграцией позже.
- **Сводное чтение холдинга** — схема `holding` с `UNION ALL`-представлениями
  (`apps.companies.services.holding_views`). Сводимые модели объявляются в
  `apps/<domain>/holding.py`. После миграции, меняющей состав столбцов,
  представления надо пересобрать: `rebuild_holding_views()`.
- **Два рубильника, а не один.** `ServiceStatus` гасит домен на всей
  платформе, `CompanyModule` — у одной компании. `CORE_MODULES`
  (`apps/core/services.py`) на уровне компании не выключаются.

Полный дизайн: [docs/multi-company-tenancy-design.md](docs/multi-company-tenancy-design.md).
Команды: `company_create`, `migrate_companies`, `tenancy_bootstrap`.
````

- [ ] **Шаг 2: Дописать в `backend/README.md`**

В раздел про добавление домена добавить абзац:

```markdown
### Аппка в схеме компании или в public?

Решается один раз, при заведении аппки, и меняется потом только через
`ALTER TABLE ... SET SCHEMA`. Критерий: данные принадлежат одному
юридическому лицу группы (кадры, проекты, договоры, согласования) — аппка
идёт в `settings.TENANT_APPS` и её таблицы живут в `co_<slug>`. Данные
общие для всей группы (учётные записи, публичный сайт, чат, файлы, почта)
— аппка остаётся в `public`.

Аппка из `TENANT_APPS` обязана:
- не иметь поля компании в моделях (его роль выполняет схема);
- передавать `company_slug` в свои задачи Celery через `@company_task`;
- объявить `apps/<domain>/holding.py`, если её данные нужны в сводках холдинга.
```

- [ ] **Шаг 3: Дописать в `STRUCTURE.md`**

В список каталогов добавить `backend/htqweb/tenancy/` и `backend/apps/companies/`
с однострочным описанием каждого файла — по образцу соседних записей.

- [ ] **Шаг 4: Коммит**

```bash
git add CLAUDE.md backend/README.md STRUCTURE.md
git commit -m "docs: мультикомпанейность в CLAUDE.md, README и STRUCTURE"
```

---

## Внешняя зависимость — wildcard-сертификат

**Не входит в задачи плана, но блокирует прод-выкатку.**

Certbot в `docker-compose.yml` настроен на `--webroot`, то есть HTTP-01, а
он wildcard-сертификаты **не выдаёт**. Для `*.<домен>` нужен DNS-01, то есть
плагин под конкретного DNS-провайдера и токен его API.

Разработку это не блокирует: `*.localhost` резолвится браузером в 127.0.0.1
без записей в hosts-файле и без TLS.

Задача для того, кто владеет DNS: завести токен, добавить в compose
`certbot-dns-<провайдер>`, выпустить `*.<домен>`, продлевать по расписанию.

---

## Порядок выполнения

Задачи 1→14 строго последовательны: каждая опирается на интерфейсы
предыдущих. Задачи 15 (nginx) и 16 (фронт) зависят только от задачи 8 и
могут идти параллельно с 9-14. Задача 17 (метрики и админка) зависит от
задач 1 и 6. Задача 18 (документация) — последняя, она описывает уже
построенное.

Работающее ПО появляется после задачи 14: на этом рубеже платформа уже
разводит компании по схемам, мигрирует их отдельно и отдаёт сводку холдинга
— просто выбор компании ещё идёт заголовком, а не поддоменом. Задачи 15-16
доводят до поддоменного режима.
