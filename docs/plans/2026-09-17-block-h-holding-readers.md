# Блок H. Сводки холдинга — читатели для `hr` и `tasks`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** дать группе первый экран, читающий сводные представления `holding.*`: численность и штат по компаниям (`hr`) и ход работ по компаниям (`tasks`) — на одной странице, доступной только с поддомена холдинга.

**Architecture:** представления `holding.<таблица>` уже строятся (`apps/companies/services/holding_views.py`) и содержат все столбцы модели плюс `company_slug`. Блок добавляет **читателей**: `managed=False`-модели поверх этих представлений, живущие в той же аппке, что и исходная модель; сервис-сводку, считающую агрегаты одним запросом на домен; и по одной ручке на домен. Экран собирает фронт двумя запросами — межаппных вызовов на бэкенде не возникает вовсе.

**Tech Stack:** Django 5.2.7 (unmanaged models, `use_holding()`), Postgres UNION ALL-вьюхи, React + Vite + `@tanstack/react-query`.

**Spec:** `docs/plans/2026-09-14-group-structure-roadmap.md` §5.H («Сводки холдинга — читатели для `hr` и `tasks`»), §4 (строка «Сводки холдинга: строятся / никем не читаются»), `docs/multi-company-tenancy-design.md`.

## Global Constraints

Скопированы из проекта дословно; требования КАЖДОЙ задачи включают этот раздел неявно.

- **Модули `contracts` и `signoff` разрабатывает другой разработчик — их файлы не трогать вовсе** (`backend/apps/contracts/**`, `backend/apps/signoff/**`). Их `holding.py` уже объявляет модели, и представления по ним строятся; читателей к ним делает ОН.
- **Межаппное взаимодействие — только через `apps.<x>.interface`** (сторож `backend/apps/core/tests/test_app_isolation.py`; каталоги `tests/` он пропускает — в тестах нарушение надо ловить глазами).
- **НИКОГДА не создавать ветки и worktree.** Работа идёт в ветке, которую дал пользователь (`sanzhar`).
- **Не добавлять в коммит чужие незакоммиченные файлы** (`.codebase-memory/`, `.cursor/`, `.zed/`, `.github/copilot-instructions.md`, `.github/instructions/`); `git add -A` не использовать — только поимённо.
- **Трейлер коммита, дословно:** `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **`hr` и `tasks` — тенантные аппки: миграции только expand** (аддитивные). Изменение схемы тенантной аппки требует `migrate_companies` отдельным шагом выкатки.
- **Модели тенантных аппок НЕ содержат поля компании** — изоляция схемами. `company_slug` у читателей холдинга это правило не нарушает: столбец существует только в представлении, а не в таблице компании.
- **Интерпретатор — КОРНЕВОЙ `.venv`.** Из `backend/`: `../.venv/Scripts/python.exe -m pytest <path> -q`.
- **pytest — только в форграунде, с явным `timeout: 600000` у инструмента Bash.** Никогда в фоне и не через Monitor.
- `manage.py` без строки переменных окружения висит 120 с на недоступном PgBouncer:
  `DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py <команда>`
- Postgres для тестов — `docker compose -f docker-compose.test-local.yml up -d db` (порт `:55432`).
- **Фронтовые сторожа обязательны:** `src/lib/ux/__tests__/uxContract.test.ts` (обработчик ошибок обязан звать `reportApiError`/`explainedDetail` из `@/lib/apiError`; поля дат — `<DateInput>`), `translationKeys.test.ts` (каждый ключ перевода объявлен), `src/app/routing/routeDefinitions.test.ts`, `src/lib/auth/modules.test.ts`.
- Известные падения сьюта перечислены в `backend/ci-known-failures.txt` (8 шт.); ночью у разработчика в UTC+5 к ним добавляются два `test_board_defaults_to_today*` (расхождение `dt.date.today()` в тесте и `timezone.localdate()` во вьюхе при `TIME_ZONE="UTC"`) — к этому блоку отношения не имеют.

## Решения заказчика (приняты 17.09.2026, обязательны к исполнению)

1. **Состав первой версии** — люди и работы (моя зона) плюс плитки-заглушки «Бюджеты» и «Согласования» с честной подписью «данные подключит второй разработчик». Заглушка НЕ показывает нулей и НЕ притворяется загрузкой.
2. **Доступ** — экран и ручки открыты только на поддомене компании вида «холдинг» и только при праве на модуль; платформенный администратор — всегда. С поддомена дочернего общества сводка по группе недоступна даже его директору.
3. **Ручки — по доменам**, фронт собирает: `GET /api/hr/v1/holding/headcount` и `GET /api/tasks/v1/holding/projects`. Одной сводной ручки в `companies` нет намеренно: она заставила бы реестр компаний знать смысл кадровых и проектных цифр, а каждую новую плитку править в двух аппках.

## Решения, принятые при планировании (для проверки заказчиком)

4. **Читатель — отдельная `managed=False`-модель, а не повторное использование обычной.** У представления есть столбец `company_slug`, которого нет в таблице компании; обычная модель его не отдаст, а добавить его в неё нельзя (правило «в тенантных моделях нет поля компании»).
5. **Читатель падает, если его позвали вне `use_holding()`.** `db_table` у читателя совпадает с таблицей компании (`hr_employee`), поэтому без контекста холдинга он молча прочитал бы ОДНУ компанию и выдал её цифры за групповые. Ошибка дороже тишины, поэтому `use_holding()` обзаводится признаком, а менеджер читателя его требует.
6. **Штатное расписание добавляется в сводимые модели** (`StaffingPosition` в `hr/holding.py`): «штат против факта» — первая цифра, которую спрашивает директор, и без неё численность не с чем сравнивать. Цена — ещё одно представление и обязательный `migrate_companies` на выкатке.
7. **Архивные компании в сводку не попадают** — так устроен `rebuild_holding_views` (читает `active_company_slugs`). Это решение платформы, блок его не меняет; в тексте экрана оговаривается, что показаны действующие компании.
8. **Снесённые представления — это 503, а не 500 и не пустая таблица.** Во время выкатки `migrate_companies` сносит вьюхи; читатель в этот момент обязан сказать «сводки пересобираются», а не показать нули, которые директор примет за правду.
9. **Экран не кэшируется.** Живое чтение — ровно то, ради чего платформа выбрала представления вместо витрины; кэш добавил бы вопрос «на какой момент цифры» там, где сейчас ответа не требуется.

## Что уже есть (не переписывать)

- `apps/companies/services/holding_views.py` — сборка и снос представлений, автообнаружение `apps/<домен>/holding.py`; тесты `apps/companies/tests/test_holding_views.py`, включая сторожа совпадения колонок и их порядка.
- `htqweb/tenancy/db.py::use_holding()` — контекст-менеджер, переводящий соединение в схему `holding` и возвращающий прежний путь при выходе.
- Объявления сводимых моделей: `hr` — `Employee`, `Department`, `Position`; `tasks` — `Project`, `Site`, `Task`, `DailyReport`, `ProjectStaffReport`; `contracts` и `signoff` — свои (чужая зона).
- Гейт `api_view(module=…, level=…)` (`htqweb/http.py:115-122`), реестр функций `apps/<домен>/access_functions.py`, слой страниц `apps/access/pages.py`.
- Имена таблиц (проверено на стенде): `hr_employee`, `hr_department`, `hr_position`, `hr_staffingposition`, `tasks_project`, `tasks_site`, `tasks_task`, `tasks_dailyreport`, `tasks_projectstaffreport`.
- Представления, существующие сейчас: `hr_department`, `hr_employee`, `hr_position`, `tasks_*` (5 шт.), `contracts_*` (4 шт.), `signoff_*` (2 шт.). `hr_staffingposition` появится в задаче 2.

## Структура файлов

| Файл | Ответственность |
|---|---|
| `backend/htqweb/tenancy/db.py` | + `holding_active()` и признак, который ставит `use_holding()` |
| `backend/apps/hr/holding.py` | + `StaffingPosition` в `HOLDING_MODELS` |
| `backend/apps/hr/holding_models.py` | **новый** — `managed=False`-читатели четырёх представлений `hr` |
| `backend/apps/hr/services/holding_service.py` | **новый** — агрегаты по компаниям |
| `backend/apps/hr/{views,urls,schemas,access_functions}.py` | ручка `holding/headcount`, её гейт, схема ответа, узел прав `hr.holding` |
| `backend/apps/tasks/holding_models.py`, `services/holding_service.py`, `{views,urls,schemas,access_functions}.py` | то же для домена работ |
| `backend/apps/companies/interface.py` | + `is_holding(slug)` — единственный способ соседям спросить вид компании |
| `frontend/src/types/holding.ts`, `src/api/holding.ts` | типы и транспорт |
| `frontend/src/pages/holding/GroupSummary.tsx` (+ тест) | экран |
| `frontend/src/app/routing/*`, `src/components/profile/ProfileSidebar.tsx`, `src/i18n/*`, `backend/apps/access/pages.py` | маршрут, ссылка, переводы, узел страницы |

---

### Task 1: Контекст холдинга становится проверяемым

**Files:**
- Modify: `backend/htqweb/tenancy/db.py`
- Modify: `backend/htqweb/tenancy/__init__.py`
- Test: `backend/apps/companies/tests/test_holding_context.py` (создать)

**Interfaces:**
- Produces: `htqweb.tenancy.holding_active() -> bool` — True внутри `use_holding()`, False снаружи. Читатели задач 2 и 4 опираются на неё.

- [ ] **Step 1: Написать падающий тест**

```python
"""Признак «идёт чтение сводки холдинга».

Нужен не ради удобства: читатели холдинга объявляют тот же db_table, что и
таблица компании (``hr_employee``), поэтому вне схемы ``holding`` они молча
прочитали бы ОДНУ компанию и выдали её цифры за групповые. Признак
позволяет менеджеру читателя потребовать контекст и упасть громко.
"""

from __future__ import annotations

import pytest

from htqweb.tenancy.db import holding_active, use_company, use_holding


@pytest.mark.django_db
def test_holding_is_not_active_by_default():
    assert holding_active() is False


@pytest.mark.django_db
def test_holding_is_active_inside_use_holding():
    with use_holding():
        assert holding_active() is True
    assert holding_active() is False


@pytest.mark.django_db
def test_holding_flag_falls_back_even_when_the_block_raises():
    with pytest.raises(RuntimeError):
        with use_holding():
            raise RuntimeError("прерванное чтение сводки")
    assert holding_active() is False


@pytest.mark.django_db
def test_company_context_does_not_pretend_to_be_holding():
    """use_company — не сводка: признак обязан остаться выключенным."""
    with use_company("acme"):
        assert holding_active() is False


@pytest.mark.django_db
def test_holding_inside_a_company_block_restores_the_flag():
    """Сводное чтение допустимо внутри открытой компании (докстринг
    use_holding это прямо оговаривает) — и выход обязан вернуть False."""
    with use_company("acme"):
        with use_holding():
            assert holding_active() is True
        assert holding_active() is False
```

- [ ] **Step 2: Убедиться, что падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_holding_context.py -q`
Expected: FAIL — `ImportError: cannot import name 'holding_active'`.

- [ ] **Step 3: Реализация**

В `backend/htqweb/tenancy/db.py` к импортам добавить `from contextvars import ContextVar`, а ниже `_PUBLIC_ONLY`:

```python
#: «Соединение сейчас смотрит в схему сводок». Отдельный признак, а не
#: проверка search_path запросом: во-первых, это лишний round-trip на каждый
#: queryset, во-вторых, search_path меняют и миграции, и middleware, и
#: доверять ему как признаку НАМЕРЕНИЯ нельзя.
#:
#: Контекст компании при этом по-прежнему НЕ ставится (см. докстринг
#: use_holding): сводное чтение находится НАД компаниями, и код внутри него
#: не должен считать себя работающим внутри одной из них.
_holding: ContextVar[bool] = ContextVar("htqweb_holding", default=False)


def holding_active() -> bool:
    """Идёт ли сейчас чтение сводных представлений холдинга.

    Спрашивают читатели схемы holding: их модели объявляют тот же db_table,
    что и таблица компании, поэтому вызов вне use_holding() прочитал бы
    данные ОДНОЙ компании и выдал их за групповые — без ошибки и без следа.
    """
    return _holding.get()
```

Тело `use_holding()` обернуть так, чтобы признак снимался в `finally` вместе с путём:

```python
    previous = current_company_or_none()
    token = _holding.set(True)
    with connection.cursor() as cur:
        cur.execute(
            sql.SQL("SET search_path TO {}, public").format(
                sql.Identifier(HOLDING_SCHEMA),
            )
        )
    try:
        yield
    finally:
        _holding.reset(token)
        apply_search_path(previous)
```

- [ ] **Step 4: Экспорт**

В `backend/htqweb/tenancy/__init__.py` добавить `holding_active` к реэкспортам. ⚠️ Сейчас этот файл реэкспортирует только из `.context`; `db.py` импортирует `.context`, поэтому строка `from .db import holding_active  # noqa: F401` в `__init__.py` может замкнуть импорт. Если Django не стартует — оставить функцию доступной как `htqweb.tenancy.db.holding_active`, поправить импорт в тесте и НАПИСАТЬ ОБ ЭТОМ В ОТЧЁТЕ (последующие задачи импортируют её из `htqweb.tenancy.db` — этот путь работает в любом случае).

- [ ] **Step 5: Прогон**

Run: `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_holding_context.py apps/companies/tests/test_holding_views.py -q`
Expected: PASS (5 своих + существующие тесты представлений).

- [ ] **Step 6: Коммит**

```bash
git add backend/htqweb/tenancy/db.py backend/htqweb/tenancy/__init__.py backend/apps/companies/tests/test_holding_context.py
git commit -m "feat(tenancy): признак активного чтения сводок холдинга

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Читатели `hr` и сводка по численности

**Files:**
- Create: `backend/apps/hr/holding_models.py`
- Create: `backend/apps/hr/services/holding_service.py`
- Modify: `backend/apps/hr/holding.py`
- Create: миграция `backend/apps/hr/migrations/0036_holding_readers.py` (номер уточнить: `ls backend/apps/hr/migrations | tail -3`)
- Test: `backend/apps/hr/tests/test_holding_summary.py`

**Interfaces:**
- Consumes: `htqweb.tenancy.db.holding_active()`, `use_holding()` (задача 1).
- Produces: `apps.hr.services.holding_service.headcount_by_company() -> list[dict]` — по строке на действующую компанию, ключи ровно: `company_slug`, `employees_active`, `employees_total`, `departments_active`, `positions_active`, `staffing_headcount`, `staffing_payroll`.
- Produces: `apps.hr.holding_models.HoldingContextRequired`, `apps.hr.services.holding_service.HoldingViewsUnavailable` — их ловят вьюха задачи 3 и тесты.

- [ ] **Step 1: Написать падающие тесты**

Фикстуру «две компании со схемами и представлениями» собрать по образцу `apps/companies/tests/test_holding_views.py::two_companies` — прочитать его и повторить приём (эти тесты идут с `@pytest.mark.django_db(transaction=True)`, потому что схемы и вьюхи создаются DDL). Импортировать чужую фикстуру из чужого тестового модуля не надо — завести свою, минимальную: компании `alpha` и `beta`, в каждой свои отделы, должности, сотрудники и строки штатного расписания.

Обязательные проверки (каждая — отдельный тест):

```python
def test_headcount_counts_every_active_company(two_companies):
    """В сводке ровно столько строк, сколько действующих компаний."""

def test_headcount_separates_active_from_total(two_companies):
    """Уволенный остаётся в таблице (status="terminated") и обязан попасть в
    total, но не в active — иначе численность группы раздувается на всех,
    кто когда-либо работал."""

def test_headcount_ignores_soft_deleted_employees(two_companies):
    """is_deleted — мягкое удаление; его не должно быть НИ в active, НИ в total."""

def test_staffing_is_reported_next_to_the_headcount(two_companies):
    """Штат против факта — первая цифра, которую спрашивает директор.
    Числа в тесте посчитаны вручную, а не тем же выражением, что в сервисе."""

def test_keys_are_exactly_the_agreed_set(two_companies):
    """Точное сравнение множества ключей — контракт со схемой ручки."""

def test_numbers_are_plain_scalars(two_companies):
    """Decimal из БД обязан уехать наружу float'ом: JsonResponse Decimal не
    сериализует вовсе, а схема ручки объявляет float."""

def test_a_company_without_people_still_appears_with_zeros(two_companies):
    """Компания без сотрудников — это НОЛЬ в сводке, а не пропущенная строка:
    иначе исчезнувшая компания выглядит как отсутствующая, а не как пустая."""

def test_an_archived_company_disappears_from_the_summary(two_companies):
    """Архивную компанию rebuild_holding_views исключает из представлений —
    цифры группы обязаны это отражать."""

def test_reader_refuses_to_work_outside_the_holding_context():
    """Главный сторож задачи: db_table читателя совпадает с таблицей
    компании, поэтому вызов без use_holding() прочитал бы ОДНУ компанию и
    выдал её цифры за групповые. Ожидается HoldingContextRequired."""

def test_summary_says_so_when_the_views_are_gone(two_companies):
    """Во время выкатки migrate_companies сносит представления (позвать
    holding_views.drop_holding_views()). Читатель обязан поднять
    HoldingViewsUnavailable, а не вернуть нули и не упасть чем попало."""
```

- [ ] **Step 2: Убедиться, что падают** — ожидается `ModuleNotFoundError: apps.hr.holding_models`.

- [ ] **Step 3: Читатели**

`backend/apps/hr/holding_models.py`:

```python
"""Читатели сводных представлений холдинга для домена кадров.

Почему отдельные модели, а не обычные: у представления есть служебный
столбец ``company_slug``, которого в таблице компании нет и быть не может
(правило мультикомпанейности — в тенантных моделях поля компании нет,
изоляцию даёт схема). Обычная модель этот столбец не отдаст.

``managed = False``: таблицы под этими моделями создаёт не Django, а
``apps.companies.services.holding_views``. Миграция для них всё равно
появляется (Django записывает состояние), но DDL не выполняет.

⚠️ ``db_table`` СОВПАДАЕТ с таблицей компании — иначе и быть не может,
представление называется по таблице. Отсюда главная опасность: вызов вне
``use_holding()`` прочитал бы данные ОДНОЙ компании и выдал их за
групповые, без ошибки и без следа. Поэтому у читателей свой менеджер,
который требует контекста.

Поля объявлены НЕ все, а только нужные сводке: незаявленное поле Django
просто не выбирает, а короткий список честнее показывает, что читателю
нужно. Добавлять поле сюда можно свободно — представление содержит все
столбцы модели.
"""

from __future__ import annotations

from django.db import models

from htqweb.tenancy.db import holding_active


class HoldingContextRequired(RuntimeError):
    """Читателя холдинга позвали вне ``use_holding()``."""


class HoldingManager(models.Manager):
    def get_queryset(self):
        if not holding_active():
            raise HoldingContextRequired(
                f"{self.model.__name__} читает схему holding и требует "
                f"htqweb.tenancy.db.use_holding(); вне его он прочитал бы "
                f"одну компанию и выдал её цифры за групповые"
            )
        return super().get_queryset()


class HoldingRow(models.Model):
    """Общее у всех читателей: служебный столбец, менеджер, запрет записи."""

    company_slug = models.CharField(max_length=63)

    objects = HoldingManager()

    class Meta:
        abstract = True
        managed = False

    def save(self, *args, **kwargs):
        raise NotImplementedError("Сводка холдинга — чтение: представление не пишется")

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Сводка холдинга — чтение: представление не пишется")


class HoldingEmployee(HoldingRow):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20)
    is_deleted = models.BooleanField(default=False)
    department_id = models.IntegerField(null=True)
    position_id = models.IntegerField(null=True)

    class Meta(HoldingRow.Meta):
        db_table = "hr_employee"


class HoldingDepartment(HoldingRow):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta(HoldingRow.Meta):
        db_table = "hr_department"


class HoldingPosition(HoldingRow):
    title = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    level = models.IntegerField(default=2)

    class Meta(HoldingRow.Meta):
        db_table = "hr_position"


class HoldingStaffingPosition(HoldingRow):
    headcount = models.DecimalField(max_digits=5, decimal_places=2)
    salary = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta(HoldingRow.Meta):
        db_table = "hr_staffingposition"
```

⚠️ `department_id`/`position_id` объявлены как `IntegerField`, а не `ForeignKey`, намеренно: FK в сводке указывал бы на id внутри ЧУЖОЙ схемы — два разных отдела разных компаний имеют один и тот же id, и Django с радостью «разрешил» бы такую ссылку не туда. В сводке идентификаторы — просто числа.

- [ ] **Step 4: Штатное расписание — в сводимые модели**

`backend/apps/hr/holding.py`:

```python
"""Модели hr для сводных представлений холдинга. См. apps/tasks/holding.py."""

# StaffingPosition — ради «штата против факта»: численность не с чем
# сравнивать, а это первая цифра, которую спрашивает директор. Цена —
# ещё одно представление и обязательный migrate_companies на выкатке.
HOLDING_MODELS = ("Employee", "Department", "Position", "StaffingPosition")
```

- [ ] **Step 5: Сервис**

`backend/apps/hr/services/holding_service.py`:

```python
"""Сводка домена кадров по всей группе.

Считается агрегатами в БД, а не обходом компаний в Python: ради этого
платформа и выбрала UNION ALL-представления вместо склейки в памяти
(докстринг apps/companies/services/holding_views.py).
"""

from __future__ import annotations

from django.db import ProgrammingError, connection
from django.db.models import Count, Q, Sum

from htqweb.tenancy.context import HOLDING_SCHEMA
from htqweb.tenancy.db import use_holding

from ..holding_models import (
    HoldingDepartment, HoldingEmployee, HoldingPosition, HoldingStaffingPosition,
)
from ..models import EmployeeStatus


class HoldingViewsUnavailable(RuntimeError):
    """Представлений холдинга сейчас не существует.

    Состояние штатное, а не аварийное: ``migrate_companies`` сносит их на
    время прогона миграций. Вьюха обязана перевести это в 503 «сводки
    пересобираются» — нули на экране директор примет за правду.
    """


def _views_are_gone() -> bool:
    """Правда ли, что вьюх нет, — спрашивается ТОЛЬКО на ветке ошибки.

    ``ProgrammingError`` ловится широко (psycopg поднимает его и на опечатке
    в SQL), поэтому причина уточняется отдельным запросом: иначе настоящая
    ошибка запроса маскировалась бы под «идёт выкатка». ATOMIC_REQUESTS в
    проекте выключен, поэтому упавший запрос не отравляет соединение и
    второй запрос проходит.
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.views WHERE table_schema = %s",
            [HOLDING_SCHEMA],
        )
        (count,) = cur.fetchone()
    return count == 0


def _by_company(queryset, **aggregates) -> dict[str, dict]:
    grouped = queryset.values("company_slug").annotate(**aggregates)
    return {row.pop("company_slug"): row for row in grouped}


def headcount_by_company() -> list[dict]:
    """По строке на действующую компанию: люди, структура, штат.

    Архивных компаний в представлениях нет по построению
    (``rebuild_holding_views`` читает только действующие) — поэтому фильтра
    по статусу компании здесь нет и быть не должно.
    """
    try:
        with use_holding():
            people = _by_company(
                HoldingEmployee.objects.filter(is_deleted=False),
                employees_total=Count("id"),
                employees_active=Count("id", filter=Q(status=EmployeeStatus.ACTIVE)),
            )
            departments = _by_company(
                HoldingDepartment.objects.filter(is_active=True),
                departments_active=Count("id"),
            )
            positions = _by_company(
                HoldingPosition.objects.filter(is_active=True),
                positions_active=Count("id"),
            )
            staffing = _by_company(
                HoldingStaffingPosition.objects.all(),
                staffing_headcount=Sum("headcount"),
                staffing_payroll=Sum("salary"),
            )
    except ProgrammingError:
        if _views_are_gone():
            raise HoldingViewsUnavailable(
                "Сводные представления холдинга сейчас пересобираются"
            ) from None
        raise

    slugs = sorted(set(people) | set(departments) | set(positions) | set(staffing))
    return [
        {
            "company_slug": slug,
            "employees_active": int(people.get(slug, {}).get("employees_active") or 0),
            "employees_total": int(people.get(slug, {}).get("employees_total") or 0),
            "departments_active": int(
                departments.get(slug, {}).get("departments_active") or 0),
            "positions_active": int(
                positions.get(slug, {}).get("positions_active") or 0),
            # float, а не Decimal: JsonResponse Decimal не сериализует, а
            # схема ручки объявляет float. Приведение делается ЗДЕСЬ, чтобы у
            # вьюхи не было своей версии правды о типах.
            "staffing_headcount": float(
                staffing.get(slug, {}).get("staffing_headcount") or 0),
            "staffing_payroll": float(
                staffing.get(slug, {}).get("staffing_payroll") or 0),
        }
        for slug in slugs
    ]
```

⚠️ **Решение, которое принимает исполнитель и записывает в отчёт:** `Sum("salary")` даёт сумму ОКЛАДОВ строк расписания, а не фонд оплаты труда — ФОТ строки это оклад × число единиц (так он считается в `approval_hooks._staffing_facts`, ключ `payroll`). Если берёте ФОТ, считайте `Sum(F("salary") * F("headcount"), output_field=DecimalField())` и **переименуйте ключ** в `staffing_payroll_fund`, чтобы имя не врало; правка тянет за собой схему ручки, клиент и тест страницы. Выбранный вариант объяснить в отчёте одной фразой.

⚠️ Компания без единой строки в какой-либо из четырёх таблиц не попадёт в соответствующий словарь — поэтому список слагов собирается объединением, а недостающие значения дают 0 (тест `test_a_company_without_people_still_appears_with_zeros`). Компания, у которой пусто ВЕЗДЕ, в сводке не появится вовсе; если это окажется важно, список компаний надо брать из `apps.companies.interface`, а не из представлений — записать как наблюдение, не чинить в этой задаче.

- [ ] **Step 6: Миграция**

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 \
  ../.venv/Scripts/python.exe manage.py makemigrations hr -n holding_readers
```

Дописать в получившийся файл докстринг: операции `CreateModel` с `managed=False` **не выполняют DDL** — таблицы под читателями создаёт `holding_views`, а миграция лишь записывает состояние, чтобы `makemigrations --check` был чист. Проверить, что других операций в файле НЕТ; если Django сгенерировал что-то ещё — остановиться и написать об этом в отчёте.

- [ ] **Step 7: Прогон и коммит**

Run (форграундом, `timeout: 600000`):
`../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_holding_summary.py apps/companies/tests/test_holding_views.py apps/core/tests/test_app_isolation.py -q`

```bash
git add backend/apps/hr/holding_models.py backend/apps/hr/holding.py backend/apps/hr/services/holding_service.py backend/apps/hr/migrations/0036_holding_readers.py backend/apps/hr/tests/test_holding_summary.py
git commit -m "feat(hr): сводка по людям и штату для всей группы

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Ручка `hr` и правило «только поддомен холдинга»

**Files:**
- Modify: `backend/apps/companies/interface.py`
- Modify: `backend/apps/hr/views.py`, `backend/apps/hr/urls.py`, `backend/apps/hr/schemas.py`, `backend/apps/hr/access_functions.py`
- Test: `backend/apps/hr/tests/test_holding_api.py`

**Interfaces:**
- Consumes: `headcount_by_company()`, `HoldingViewsUnavailable` (задача 2).
- Produces: `apps.companies.interface.is_holding(slug: str) -> bool` — задача 4 зовёт её же.
- Produces: `GET /api/hr/v1/holding/headcount` → `{"companies": [{company_slug, company_name, employees_active, employees_total, departments_active, positions_active, staffing_headcount, staffing_payroll}], "totals": {employees_active, employees_total, staffing_headcount, staffing_payroll}}`.

- [ ] **Step 1: Написать падающие тесты**

Обязательные проверки (каждая — отдельный тест, образец формы — `apps/hr/tests/test_staffing_api.py`):
- на поддомене холдинга пользователь с правом получает 200 и список компаний;
- **на поддомене дочернего общества — 403**, даже когда право на модуль есть (главное правило блока);
- без права на модуль `hr` — 403;
- платформенный администратор получает 200 с любого поддомена;
- без токена — 401;
- `company_name` непуст — имена приезжают из реестра, а не только слаги;
- `totals` равны сумме строк (тест складывает сам, а не повторяет выражение сервиса);
- когда представления снесены (`holding_views.drop_holding_views()`) — **503** с телом `{"detail": …}`, не 500 и не 200 с нулями;
- оба написания пути (`holding/headcount` и `holding/headcount/`) отвечают не 404.

- [ ] **Step 2: Убедиться, что падают.**

- [ ] **Step 3: `is_holding` в интерфейсе реестра**

`backend/apps/companies/interface.py`, рядом с `get_company`:

```python
def is_holding(slug: str) -> bool:
    """Компания этого слага — холдинг (владеет долями остальных).

    Предикат, а не выдача ``kind`` наружу: ``CompanyKind`` — деталь модели, и
    её протечка за границу аппки ломает то же правило, что прямой импорт
    чужих моделей. Ровно та же причина, по которой рядом отдаётся готовый
    ``is_active``, а не сырой ``status``.

    Неизвестный слаг — False, а не исключение: спрашивающий уже получил
    компанию из контекста запроса, и «такой компании нет» значит для него
    ровно «не холдинг».
    """
    company = get_company(slug)
    return bool(company and company["kind"] == CompanyKind.HOLDING)
```

- [ ] **Step 4: Гейт и вьюха**

В `backend/apps/hr/views.py` рядом с прочими вспомогательными:

```python
def _deny_unless_holding(request):
    """Сводка по всей группе доступна только с поддомена холдинга.

    Гейт ``api_view(module=…)`` считает уровень в компании ВЫЗЫВАЮЩЕГО и про
    вид этой компании ничего не знает: без этой сверки директор дочернего
    общества, у которого есть право на модуль кадров, читал бы численность и
    ФОТ соседних компаний группы.

    Платформенный администратор проходит всегда — у него и так есть доступ к
    любой схеме через django-admin, и запрет здесь создал бы лишь
    впечатление защиты.
    """
    if request.token.is_superuser:
        return None
    slug = current_company_or_none()
    if slug and companies.is_holding(slug):
        return None
    return json_error("Сводка по группе доступна только на поддомене холдинга", 403)
```

Вьюха — тонкая, как все в проекте: гейт → сервис → форма ответа. `HoldingViewsUnavailable` переводится в **503** (`json_error(str(exc), 503)`): состояние временное и ожидаемое, клиенту осмысленно повторить запрос позже.

Имена компаний добавляются к строкам сводки из реестра. ⚠️ Проверьте по `apps/companies/interface.py`, есть ли готовая функция «отдай все компании»; если нет — добавьте её туда же, где `is_holding`, по образцу соседей. Напрямую модели `apps.companies` из `hr` не трогать.

Схемы ответа — в `backend/apps/hr/schemas.py` (Pydantic, как у соседних ручек): `HoldingCompanyRow`, `HoldingTotals`, `HoldingHeadcountOut`.

- [ ] **Step 5: Маршрут и узел прав**

`backend/apps/hr/urls.py` — оба написания:

```python
    path("holding/headcount", views.holding_headcount),
    path("holding/headcount/", views.holding_headcount),
```

`backend/apps/hr/access_functions.py` — строка в `FUNCTIONS`:

```python
    ("hr.holding", "Кадры: сводка по группе", ("view",)),
```

- [ ] **Step 6: Прогон и коммит**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_holding_api.py apps/hr/tests/test_holding_summary.py apps/access apps/core/tests/test_app_isolation.py -q`

```bash
git commit -m "feat(hr): ручка сводки по группе — только с поддомена холдинга

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Читатели `tasks` и сводка по работам

**Files:**
- Create: `backend/apps/tasks/holding_models.py`, `backend/apps/tasks/services/holding_service.py`
- Create: миграция `backend/apps/tasks/migrations/00NN_holding_readers.py` (номер уточнить: `ls backend/apps/tasks/migrations | tail -3`)
- Modify: `backend/apps/tasks/views.py`, `urls.py`, `schemas.py`, `access_functions.py`
- Test: `backend/apps/tasks/tests/test_holding_summary.py`

**Interfaces:**
- Consumes: `holding_active()`, `use_holding()` (задача 1), `apps.companies.interface.is_holding()` (задача 3).
- Produces: `GET /api/tasks/v1/holding/projects` → `{"companies": [{company_slug, company_name, projects_active, sites_active, tasks_open, tasks_overdue, reports_last_date}], "totals": {projects_active, sites_active, tasks_open, tasks_overdue}}`.

Форма — ровно как в задачах 2–3; прочитать оба готовых файла и повторить приёмы. ⚠️ Абстрактный `HoldingRow` из `apps/hr/holding_models.py` **не импортировать**: это межаппный импорт, он запрещён и ловится сторожом. Завести свой, такой же по смыслу — дублирование здесь дешевле нарушенной границы.

Читатели (`managed=False`, свой менеджер с проверкой контекста):
- `HoldingProject` — `tasks_project`: `name`, `status`;
- `HoldingSite` — `tasks_site`: `name`, `status`;
- `HoldingTask` — `tasks_task`: `status`, `due_date`, `is_deleted`;
- `HoldingDailyReport` — `tasks_dailyreport`: `work_date`, `is_deleted`.

Определения цифр (записать в докстринг сервиса — экран и API обязаны говорить одно и то же):
- `projects_active` — `status="active"` (`ProjectStatus.ACTIVE`);
- `sites_active` — `status="active"` (`SiteStatus.ACTIVE`);
- `tasks_open` — `is_deleted=False` и статус НЕ в `("done", "cancelled")`;
- `tasks_overdue` — открытые с `due_date__lt` сегодня;
- `reports_last_date` — `Max("work_date")` по неудалённым ежедневным отчётам; `None` у компании без отчётов, и это НЕ ноль.

⚠️ «Сегодня» брать **`django.utils.timezone.localdate()`**, а не `datetime.date.today()`: платформа живёт в UTC (`TIME_ZONE="UTC"`), хост разработчика — нет, и ровно на этом расхождении ночью падают два чужих теста в `apps/tasks`. В тестах этой задачи даты задавать относительно `timezone.localdate()`, а не константами.

Обязательные проверки: те же десять, что в задаче 2 (включая отказ читателя вне контекста и `HoldingViewsUnavailable` при снесённых вьюхах), плюс:
- задача со статусом `done` не попадает ни в `tasks_open`, ни в `tasks_overdue`;
- просроченной считается задача со вчерашним `due_date`, а сегодняшняя — нет (граница);
- задача без `due_date` не считается просроченной;
- компания без единого отчёта даёт `reports_last_date: None`, а не сегодняшнюю дату.

Ручка, гейт (`_deny_unless_holding` по образцу задачи 3 — свой, в `apps/tasks/views.py`), узел прав `("tasks.holding", "Задачи: сводка по группе", ("view",))`, оба написания пути.

- [ ] **Step 1: Тесты** — [ ] **Step 2: убедиться, что падают** — [ ] **Step 3: читатели** — [ ] **Step 4: сервис** — [ ] **Step 5: миграция** — [ ] **Step 6: ручка, маршрут, права** — [ ] **Step 7: прогон и коммит**

Run: `../.venv/Scripts/python.exe -m pytest apps/tasks/tests/test_holding_summary.py apps/core/tests/test_app_isolation.py -q`

```bash
git commit -m "feat(tasks): сводка по работам для всей группы

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Экран «Сводка группы»

**Files:**
- Create: `frontend/src/types/holding.ts`, `frontend/src/api/holding.ts`
- Create: `frontend/src/pages/holding/GroupSummary.tsx`, `frontend/src/pages/holding/GroupSummary.test.tsx`
- Modify: словари `frontend/src/i18n/` (посмотреть, как подключена соседняя страница `src/pages/companies/CompanyRegistry.tsx`)

**Interfaces:**
- Consumes: ручки задач 3 и 4.
- Produces: компонент страницы; маршрут подключает задача 6.

- [ ] **Step 1: Тест страницы** (vitest + Testing Library, образец — `frontend/src/pages/companies/CompanyRegistry.test.tsx`). Обязательные проверки:
- таблица показывает строку на компанию и строку «Итого по группе»;
- **плитки «Бюджеты» и «Согласования» подписаны «данные подключит второй разработчик»** — тест ищет именно этот текст, чтобы заглушку нельзя было принять за ноль;
- 403 от любой из ручек рисует объяснение «доступно только на поддомене холдинга», а не пустую таблицу;
- 503 рисует «сводки пересобираются, повторите позже» — ОТДЕЛЬНЫМ состоянием, не тем же, что 403;
- пока грузится — скелет, а не нули;
- компания без отчётов показывает прочерк в колонке «последний отчёт», а не сегодняшнюю дату.

- [ ] **Step 2: Убедиться, что падает.**

- [ ] **Step 3: Типы и клиент** — `frontend/src/api/holding.ts` по образцу `src/api/companies.ts`: `apiPath('hr', 'holding/headcount')`, пути без завершающего слэша, слой транспортный, никакой логики.

- [ ] **Step 4: Страница.** Требования сторожей:
- обработка ошибок ТОЛЬКО через `reportApiError`/`explainedDetail` из `@/lib/apiError` — свой текст ошибки запрещён (`uxContract.test.ts`);
- все подписи — через `t(...)`, ключи объявлены в словарях (`translationKeys.test.ts`);
- запросы через `@tanstack/react-query` — он в проекте основной.

- [ ] **Step 5: Прогон и коммит**

```bash
cd frontend
npx vitest run src/pages/holding src/lib/ux src/i18n
npx tsc --noEmit -p tsconfig.app.json   # базовый уровень 150 ошибок; НОВЫХ быть не должно
```

```bash
git commit -m "feat(frontend): экран сводки по группе

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Маршрут, права страницы, ссылка в меню

**Files:**
- Modify: `frontend/src/app/routing/lazyPages.ts`, `routeDefinitions.ts`, `routeDefinitions.test.ts`
- Modify: `frontend/src/components/profile/ProfileSidebar.tsx`
- Modify: `backend/apps/access/pages.py`

- [ ] **Step 1: Тест маршрута**

В `frontend/src/app/routing/routeDefinitions.test.ts`:

```typescript
    it('сводка группы закрыта гейтом кадрового модуля', () => {
        const byPath = new Map(protectedRoutes.map((r) => [r.path, r]));
        expect(byPath.get('/holding')?.requires).toEqual({ module: 'hr', level: 'read' });
        expect(byPath.get('/holding')?.requiresAuth).toBe(true);
    });
```

- [ ] **Step 2: Маршрут** — строка в `lazyPages.ts` и строка в `protectedRoutes`:

```typescript
  { path: '/holding', component: lazyPages.GroupSummary, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
```

⚠️ Рядом — комментарий, объясняющий, почему модуль один: `RouteRequirement` допускает ровно один модуль, страница собирает два домена, а настоящее ограничение («только поддомен холдинга») живёт на сервере и подделке через бандл не поддаётся. Без этого комментария следующий читатель решит, что гейт неполон по недосмотру.

- [ ] **Step 3: Узел страницы** — в `backend/apps/access/pages.py` добавить `("/holding", "Сводка по группе")`. Этот список — копия таблицы маршрутов фронта, и расхождение делает страницу ненастраиваемой в редакторе ролей.

- [ ] **Step 4: Ссылка в меню** — `ProfileSidebar.tsx`, блок `adminItems`, рядом с «Компании группы»: `id: 'holding'`, `to: '/holding'`, иконка из `lucide-react`, ключ перевода объявить в словарях.

- [ ] **Step 5: Прогон и коммит**

```bash
cd frontend && npx vitest run src/app/routing src/i18n
cd ../backend && ../.venv/Scripts/python.exe -m pytest apps/access -q
```

```bash
git commit -m "feat(frontend): маршрут и ссылка на сводку группы

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Сквозная проверка на стенде и документы

**Files:**
- Modify: `docs/plans/2026-09-14-group-structure-roadmap.md` (§4, §5.H, §7), `API.md`, `STRUCTURE.md`, `CLAUDE.md`

- [ ] **Step 1: Прогоны (гонит КОНТРОЛЛЕР).** Полный сьют — ожидается ровно 8 известных падений (`backend/ci-known-failures.txt`); отдельно `apps/companies` — представления не должны пострадать от нового читателя.

- [ ] **Step 2: Сквозная проверка на dev-базе.**

```bash
cd backend
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 \
  ../.venv/Scripts/python.exe manage.py migrate_companies
```

Через Bash (не PowerShell) убедиться, что в схеме `holding` появилось `hr_staffingposition` и что в нём есть `company_slug`:

```bash
docker exec htqweb-local-db-1 psql -U htqweb -d htqweb -At -c \
  "select table_name from information_schema.views where table_schema='holding' order by 1;"
docker exec htqweb-local-db-1 psql -U htqweb -d htqweb -At -c \
  "select column_name from information_schema.columns where table_schema='holding' and table_name='hr_staffingposition' order by ordinal_position limit 3;"
```

- [ ] **Step 3: Документы.**

**roadmap §4** — строку «Сводки холдинга | строятся | никем не читаются» заменить на «✅ читаются — экран «Сводка группы» (`/holding`), ручки `hr` и `tasks`» с оговоркой, что финансы и согласования остаются плитками-заглушками до читателей второго разработчика.

**roadmap §5.H** — «(выполнено)» плюс: какие представления читаются, где живут читатели, правило доступа (поддомен холдинга + модуль + платформенный админ всегда) и что `StaffingPosition` добавлен в сводимые модели, то есть выкатка требует `migrate_companies`.

**roadmap §7** — в шаг про блок H дописать: `migrate_companies` обязателен (новое представление); порядок «мигрировать все компании → пересобрать вьюхи» обеспечивает сама команда.

**API.md** — две строки в таблицах доменов: `GET /api/hr/v1/holding/headcount` и `GET /api/tasks/v1/holding/projects`, с правами (JWT + модуль + только поддомен холдинга) и кодами (403 с чужого поддомена, 503 при пересборке представлений).

**STRUCTURE.md** — в строках аппок `hr` и `tasks` упомянуть `holding_models.py` и `services/holding_service.py` одной фразой.

**CLAUDE.md**, в раздел «Мультикомпанейность», сразу после абзаца «Сводное чтение холдинга»:

```markdown
- **У сводок появились читатели.** `managed=False`-модели `apps/<домен>/holding_models.py` (`hr`, `tasks`) читают представления `holding.*` через `use_holding()`; экран «Сводка группы» (`/holding`) собирает две ручки — `hr/v1/holding/headcount` и `tasks/v1/holding/projects`. ⚠️ У читателя `db_table` СОВПАДАЕТ с таблицей компании (иначе и быть не может — представление называется по таблице), поэтому вызов вне `use_holding()` прочитал бы одну компанию и выдал её цифры за групповые. Чтобы это не случилось молча, `use_holding()` ставит признак `htqweb.tenancy.db.holding_active()`, а менеджер читателя без него поднимает `HoldingContextRequired`. Сводка отдаётся только на поддомене компании вида «холдинг» (`companies.interface.is_holding`): гейт `api_view(module=…)` считает уровень в компании ВЫЗЫВАЮЩЕГО и вид компании не проверяет. Во время `migrate_companies` представлений не существует — ручки отвечают 503 «сводки пересобираются», а не нулями.
```

- [ ] **Step 4: Коммит**

```bash
git commit -m "docs: блок H закрыт — у сводок холдинга появились читатели

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Что осталось за рамками (названо заранее)

- **Финансы и согласования в сводке.** `contracts` и `signoff` уже объявили свои модели в `holding.py`, и представления по ним строятся, но читателей к ним делает второй разработчик. На экране это две честные заглушки, а не нули.
- **Разрез глубже компании** (по подразделениям, по проектам внутри компании). Первая версия отвечает на вопрос «как дела у компаний группы», а не «где именно проблема».
- **Графики и динамика.** `recharts` в зависимостях есть, но динамика требует истории, которой в представлениях нет: они показывают состояние на сейчас.
- **Выгрузка в файл** — не заказана.
- **Кэш** (решение 9) — живое чтение. Если экран окажется медленным на реальных объёмах, это отдельная работа с явным ответом на вопрос «на какой момент цифры».
- **Компания, у которой пусто во всех четырёх таблицах**, в кадровую сводку не попадёт (список слагов собирается из представлений). Чинится взятием списка компаний из реестра — отмечено в задаче 2 как наблюдение.

## Self-review

**Покрытие спеки.** §5.H просит `managed=False`-модели поверх `holding.hr_*` и `holding.tasks_*` (задачи 2 и 4), экраны сводок (задачи 5 и 6) и `use_holding()` во вьюхах холдинга (задачи 2–4 — через сервисы, потому что вьюхи в проекте тонкие по архитектурному инварианту). §4 просит снять строку «никем не читаются» (задача 7). Решения заказчика 1–3 покрыты: заглушки — задача 5, доступ — задачи 3 и 4, ручки по доменам — задачи 3 и 4.

**Заглушек нет:** код читателей, сервиса, предиката `is_holding` и гейта приведён целиком. В задачах 4–6 форма задана перечнем обязательных проверок и точными определениями цифр, а не повторным кодом: их образец — задачи 2–3 того же блока, и копия того же кода в плане устарела бы раньше, чем её прочтут. Единственное место, где план сознательно оставляет решение исполнителю, — `staffing_payroll` против `staffing_payroll_fund` (шаг 5 задачи 2), и там сказано, как выбирать и что записать.

**Согласованность имён:** `holding_active()` (задача 1 → 2, 4); `HoldingContextRequired` и `HoldingViewsUnavailable` (задача 2 → 3, 4); `headcount_by_company()` (2 → 3); `is_holding()` (3 → 4); ключи ответа ручки совпадают между сервисом, схемой, клиентом и тестом страницы; `HoldingRow` намеренно дублируется в двух аппках, и это оговорено.

**Риски, названные заранее:** совпадение `db_table` читателя с таблицей компании — главный риск блока, закрыт признаком контекста и отдельным тестом; новое представление требует `migrate_companies` на выкатке; фикстура «две компании со схемами» требует `transaction=True` и потому медленная; гейт маршрута на фронте называет один модуль, хотя страница собирает два, и настоящее ограничение живёт на сервере; `ProgrammingError` ловится широко, поэтому причина уточняется отдельным запросом, чтобы настоящая ошибка SQL не маскировалась под «идёт выкатка».
