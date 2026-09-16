# Блок D «Уровни, дирекции, демо-данные» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Новая схема компании рождается с уровнями N-1…N-4 документа, а не с пустой таблицей порогов; «Дирекция» — законный вид подразделения; локальный стенд одной командой показывает ровно четыре утверждённые оргструктуры (12 + 4 + 4 + 4 штатных единиц) в четырёх компаниях группы.

**Architecture:** Три независимых слоя. (1) Data-миграция `hr` сеет `LevelThreshold` N-1…N-4 **только в схеме компании и только в пустую таблицу** — проходит через `migrate_companies` по каждой схеме, на HTQ с порогами от ETL — no-op, в `public` (pytest, dev до `tenancy_bootstrap`) — не срабатывает вовсе. (2) `UnitType.DIRECTORATE` — новое значение choices плюс подпись в оргструктуре фронта. (3) Демо-данные разносятся по схемам: справочник четырёх оргструктур — отдельный data-модуль `apps/hr/management/group_structures.py`; `seed_hr_demo --company <slug>` сеет структуру по `Company.kind` внутри `use_company`; `seed_employee_accounts` и `seed_tasks_demo` получают тот же `--company`; новая команда `seed_group_demo` в `apps.companies` заводит четыре компании, вызывает сиды по очереди, выдаёт членства своим сотрудникам и обслуживающим должностям холдинга (`serving_holders`, блок C) и наполняет задачи строительной компании.

**Tech Stack:** Django 5.2.7 / Python 3.13 (корневой `.venv`), pytest-django против Postgres `:55432`; React + Vite, vitest, i18next (`translatedMap` для словарей уровня модуля).

**Spec:** [2026-09-14-group-structure-roadmap.md](2026-09-14-group-structure-roadmap.md) §5.D, §3 (режим перехода), §7 шаг 2 и шаг 5. Документ руководства: «Обновленный проект Оргструктуры Группы — комменты Куаныш Садыев от 10.09.2026» (стр. 2–5 — четыре оргструктуры; перерисованы в §«Данные документа» ниже, чтобы исполнителю не нужен был PDF).

## Global Constraints

- Интерпретатор — **корневой** `.venv`. Из `backend/`: `../.venv/Scripts/python.exe -m pytest <path> -q`.
- **Один прогон pytest за раз, всегда в форграунде, никогда в фоне и не через монитор.** Параллельные сессии делят `test_htqweb` и пулы схем. Полный сьют ~42 мин, `apps/hr` ~9 мин, `apps/companies` ~6 мин, `apps/tasks` ~5 мин, `apps/users` ~2 мин.
- Межаппный доступ — только через `apps.<x>.interface` (`apps/core/tests/test_app_isolation.py`); межаппных FK нет; `apps.core` и `htqweb/*` — общий фундамент.
- `hr` и `tasks` — **тенантные** аппки: миграции доводит `manage.py migrate_companies` отдельным шагом выкатки; только expand. `companies`, `users`, `access` — общие (`public`).
- Режим перехода (roadmap §3): на бою одна действующая компания `hi-tech-qazaqstan`; **ни один шаг не переносит, не переименовывает и не удаляет таблицы**; остальные компании на бою не заводятся — `seed_group_demo` защищён от неместной БД тем же `_assert_local`, что и остальные сиды.
- **Зона:** `apps/contracts/**`, `apps/signoff/**`, `seed_contracts_demo` не трогаются.
- **Ветки не создавать** — работа в выданной ветке (`sanzhar`).
- Трейлер коммитов: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Фронт: настоящая проверка типов — `npx tsc --noEmit -p tsconfig.app.json` (базовая линия 150 ошибок в нетронутых файлах, новых быть не должно); `npx vitest run <файлы>`. Базовая линия тестов: 8 падений в `src/components/hr/__tests__/{EmployeeFormDialog,CardT2SectionDialog}.test.tsx`.
- Известные падения бэкенда — ровно `backend/ci-known-failures.txt` (8 штук). Девятое — наше.
- `test_positions_api.py:124` пинит ТОЧНЫЙ набор ключей `PositionOut` — в этом блоке сериализация должности не меняется, ломаться не должно.

---

## Решения, принятые при планировании (для проверки заказчиком)

1. **Уровни в новой схеме — четыре, N-1…N-4, `label` = «N-1»…«N-4».** Диапазоны весов: N-1 `0–99`, N-2 `100–299`, N-3 `300–599`, N-4 `600–1999`. Первые три совпадают со старым сидом, N-4 поглощает старые L4+L5, чтобы ни один вес не проваливался в запасной `_DEFAULT_LEVEL = 5`. Интерфейс рисует `L{n}: {label}` → «L1: N-1»; это честно и не требует правки фронта.
2. **Сид миграции работает только в схеме компании** (первый элемент `search_path` начинается с `SCHEMA_PREFIX`), и только если таблица пуста. Причина: `migrate_company` не ставит контекст компании, а `public` — это и pytest-база, и dev до `tenancy_bootstrap`, и боевая HTQ до переноса; засеять туда значило бы сломать 20+ тестов `test_positions_api` и подменить данные, пришедшие из ETL.
3. **Структура выбирается по `Company.kind`**, а не отдельным флагом: `holding` → холдинг, `construction` → HTQ, `it` → HTS, `service` → KEG. Для `regional` (legacy-значение первой редакции дизайна) — отказ с понятным текстом. Без `--company` команда сеет структуру HTQ в текущий `search_path` (режим перехода: единственная компания — HTQ; это сохраняет цепочку `seed_hr_demo && seed_employee_accounts && seed_tasks_demo` на dev-базе до `tenancy_bootstrap`).
4. **Отделы дочерних компаний документ не задаёт** — они придуманы для стенда минимально: `upr` «Руководство» + один профильный отдел (`stroy` «Строительство» у HTQ — путь сохранён ради `seed_tasks_demo`; `dev` «Разработка» у HTS; `ops` «Эксплуатация» у KEG). У холдинга три дирекции документа с `unit_type=directorate` и описаниями со стр. 1. В плане это помечено как демо-инвентарь, не как факт документа.
5. **Пунктирные связи — `ReportingRelation.functional`, по одной строке на пару, в порядке чтения документа слева направо** (superior = левая). Модель направленная, документ — нет; направление здесь — артефакт хранения, а не смысл. Видны в матрице подчинения (`get_subordination_matrix`), в дереве не рисуются: `get_org_tree` берёт одну входящую связь на должность и предпочитает `direct`.
6. **Признаки блоков B и C выставляет сид холдинга:** ГД и три директора — `is_manager=True, external_hierarchy=inherit` (стр. 1: дирекции «координируют и контролируют деятельность компаний группы»); восемь менеджеров — `serves_subsidiaries=True` (решение 2 блока C). Директора ДО — `is_manager=True, external_hierarchy=none`; руководитель проекта HTQ — `is_manager=True` (возглавляет `stroy`). Роли на должности (`PositionRole`) сид **не** назначает — их выдают через UI блока C.
7. **Незаявленные уровни сид убирает.** `seed_hr_demo` после upsert'а N-1…N-4 удаляет пороги с другими номерами и пересчитывает `Position.level` у всех должностей схемы — иначе на dev-базе со старым пятиуровневым сидом N-4 пересёкся бы с L5, а кэш уровня у старых должностей остался бы стар. Это локальная демо-команда; на бою её нет.
8. **`seed_group_demo` вызывает сиды соседних аппок через `call_command`.** Это композиция CLI, как shell-скрипт, а не обход `interface`: команда не импортирует ни моделей, ни сервисов `hr`/`users`/`tasks`; членства и заведение компаний — её собственные сервисы. Сторож `test_app_isolation` этого не запрещает; в докстринге причина названа.
9. **Slug холдинга — `hi-tech-group`, имя «Hi-Tech Group LTD»** (roadmap §7 шаг 5). Вопрос §8.1 (какое юрлицо — УК) открыт; slug сида — **предварительный**, при ответе руководства меняется одна строка в `GROUP`.
10. **Незаполненная оргструктура HTQ** (стр. 3: пустой блок на N-4, «Менеджеры —», «Всего —», курсив у «Начальник участка») сеется как есть: четыре именованные должности, пустой блок не сеется, курсив не трактуется. Вопрос §8.3 остаётся руководству.
11. **`seed_group_demo` проверяется по-настоящему только руками** на dev-базе (задача 7): заведение четырёх схем — ~4 минуты, автотест этого не гоняет; автотесты покрывают оркестрацию с подменёнными `provision_company`/`call_command`.

## Данные документа (стр. 2–5), перерисованные в таблицы

⚠️ Поправка заказчика от 16.09.2026: «Кадровый бухгалтер» читается как
«Бухгалтер», «Системный администратор» — как «Специалист технической
поддержки» (см. план блока E). Таблицы ниже сохраняют формулировки
документа.

**Холдинг ТОО «Hi-Tech Group LTD»** — руководители 4, менеджеры 8, всего 12. N-3 пропущен.

| Уровень | Должность | Подчинение (direct) | Подразделение |
|---|---|---|---|
| N-1 | Генеральный директор | — | Руководство |
| N-2 | Финансовый директор | Генеральный директор | Дирекция по финансам и экономике |
| N-2 | Технический директор | Генеральный директор | Проектно-техническая дирекция |
| N-2 | Операционный директор | Генеральный директор | Дирекция по операционной деятельности |
| N-4 | Главный бухгалтер | Финансовый директор | Дирекция по финансам и экономике |
| N-4 | Кадровый бухгалтер | Финансовый директор | Дирекция по финансам и экономике |
| N-4 | Экономист-аналитик | Финансовый директор | Дирекция по финансам и экономике |
| N-4 | ГИП | Технический директор | Проектно-техническая дирекция |
| N-4 | Менеджер ПТО и КК | Технический директор | Проектно-техническая дирекция |
| N-4 | Менеджер по кадрам | Операционный директор | Дирекция по операционной деятельности |
| N-4 | Менеджер по закупкам | Операционный директор | Дирекция по операционной деятельности |
| N-4 | Системный администратор | Операционный директор | Дирекция по операционной деятельности |

Пунктирные связи (стр. 2): Главный бухгалтер ↔ ГИП, ГИП ↔ Менеджер по кадрам, Менеджер ПТО и КК ↔ Менеджер по закупкам.

**ТОО «HI-TECH QAZAQSTAN»** (строительная) — «Генеральный» зачёркнуто → «Директор». N-3 пропущен. Директор → Руководитель проекта (N-2) → {Начальник участка, Инженер по ОТ и ТБ} (N-4) + пустой блок.

**ТОО «HI-TECH SYSTEMS»** (IT) — Директор (N-1); Senior Full-stack developer (N-2), Middle Full-stack developer (N-3), Junior Full-stack developer (N-4) — все три подчинены директору напрямую. Руководители 1, специалисты 3.

**ТОО «KAZAKHSTAN ENGINEERING GROUP»** (сервисная) — Директор (N-1); Диспетчер (N-3), Механик (N-4), Водитель-оператор (N-4) — все подчинены директору напрямую. N-2 пуст. Руководители 1, специалисты 3.

Каждая должность — «1 шт. ед.» → `StaffingPosition.headcount = 1`.

## Структура файлов

| Файл | Ответственность |
|---|---|
| `backend/apps/hr/models.py` | `UnitType.DIRECTORATE` |
| `backend/apps/hr/migrations/0023_alter_department_unit_type.py` | choices (DDL нет) |
| `backend/apps/hr/migrations/0024_seed_level_thresholds.py` | сид N-1…N-4 в схеме компании |
| `backend/apps/hr/management/group_structures.py` | **данные**: `LEVELS`, четыре `Structure`, `structure_for(kind)` |
| `backend/apps/hr/management/commands/seed_hr_demo.py` | сид одной структуры в текущую/указанную компанию |
| `backend/apps/companies/interface.py` | `+ schema_exists(slug)` |
| `backend/apps/users/management/commands/seed_employee_accounts.py` | `+ --company` |
| `backend/apps/tasks/management/commands/seed_tasks_demo.py` | `+ --company`; пути отделов → структура HTQ |
| `backend/apps/companies/management/commands/seed_group_demo.py` | оркестрация стенда группы |
| `frontend/src/components/hr/OrgChart/OrgChartNode.tsx`, `frontend/public/locales/{ru,en}/translation.json` | подпись «Дирекция» |
| `README.md`, `CLAUDE.md`, `docs/dev/infra-ops.md`, roadmap | документы |

---

### Task 1: `UnitType.DIRECTORATE` — модель, миграция, подпись на фронте

**Files:**
- Modify: `backend/apps/hr/models.py:31-34`
- Create: `backend/apps/hr/migrations/0023_alter_department_unit_type.py` (через `makemigrations`)
- Modify: `frontend/src/components/hr/OrgChart/OrgChartNode.tsx:36-41`
- Modify: `frontend/public/locales/ru/translation.json`, `frontend/public/locales/en/translation.json` (ключ `hr.orgChart.unit.directorate`)
- Test: `backend/apps/hr/tests/test_models_schema.py`, `frontend/src/components/hr/OrgChart/__tests__/unitLabels.test.ts`

**Interfaces:**
- Produces: `UnitType.DIRECTORATE == "directorate"` (подпись «Дирекция»); задача 3 использует строку `"directorate"` в данных структур.

- [ ] **Step 1: Падающий тест на choices**

В `backend/apps/hr/tests/test_models_schema.py` добавить:

```python
@pytest.mark.django_db
def test_directorate_is_a_unit_type():
    """Оргструктура холдинга (10.09.2026) — три ДИРЕКЦИИ; подпись в
    дереве не должна врать «Подразделение»."""
    from apps.hr.models import Department, UnitType

    assert UnitType.DIRECTORATE == "directorate"
    dep = Department.objects.create(
        name="Дирекция по финансам и экономике", path="fin",
        unit_type=UnitType.DIRECTORATE,
    )
    dep.refresh_from_db()
    assert dep.unit_type == "directorate"
    assert dep.get_unit_type_display() == "Дирекция"
```

- [ ] **Step 2: Убедиться, что падает**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_models_schema.py -q -k directorate`
Expected: FAIL — `AttributeError: DIRECTORATE`.

- [ ] **Step 3: Модель**

`backend/apps/hr/models.py`:

```python
class UnitType(models.TextChoices):
    DEPARTMENT = "department", "Отдел"
    DIVISION = "division", "Управление"
    GROUP = "group", "Группа"
    # Оргструктура группы (10.09.2026): три дирекции головной компании.
    DIRECTORATE = "directorate", "Дирекция"
```

- [ ] **Step 4: Миграция**

Run: `../.venv/Scripts/python.exe manage.py makemigrations hr -n alter_department_unit_type`
Expected: один файл `0023_alter_department_unit_type.py` с единственной операцией `AlterField(model_name='department', name='unit_type', ...)`. Добавить в начало файла докстринг:

```python
"""Expand-шаг без DDL: новое значение choices у ``Department.unit_type``.

``hr`` — тенантная аппка: миграция НЕ применяется стартом контейнера
(``migrate_shared``), схемы компаний доводит ``manage.py migrate_companies``.
Postgres-ограничения на столбце нет, поэтому шаг сводится к записи в
``django_migrations`` каждой схемы; старый код значение просто не видит.
"""
```

- [ ] **Step 5: Тест зелёный**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_models_schema.py -q`
Expected: PASS всех тестов файла (миграция применена pytest-django к тестовой БД автоматически).

- [ ] **Step 6: Фронт — подпись**

`frontend/src/components/hr/OrgChart/OrgChartNode.tsx`, словарь `UNIT_LABELS`:

```ts
const UNIT_LABELS: Record<string, string> = translatedMap({
  headquarters: 'hr.orgChart.unit.headquarters',
  division: 'hr.orgChart.unit.division',
  department: 'hr.orgChart.unit.department',
  directorate: 'hr.orgChart.unit.directorate',
  pmo: 'hr.orgChart.unit.pmo',
});
```

В `frontend/public/locales/ru/translation.json` внутри `hr.orgChart.unit` добавить `"directorate": "Дирекция"`; в `en` — `"directorate": "Directorate"`. Правку JSON делать точечно (файлы большие; сохранить UTF-8 без BOM, отступы как в файле).

- [ ] **Step 7: Статический тест словаря**

Создать `frontend/src/components/hr/OrgChart/__tests__/unitLabels.test.ts`:

```ts
/**
 * Подпись вида подразделения берётся из словаря уровня модуля
 * (`UNIT_LABELS` через `translatedMap`), поэтому проверяется статически:
 * ключ обязан существовать в обоих словарях и упоминаться в компоненте.
 * Тот же приём, что в src/lib/i18n/__tests__/translationKeys.test.ts.
 */
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, '../../../../..');

function unitLabels(lng: string): Record<string, string> {
  const file = path.join(FRONTEND, 'public', 'locales', lng, 'translation.json');
  const dict = JSON.parse(fs.readFileSync(file, 'utf-8'));
  return dict.hr.orgChart.unit;
}

describe('org chart unit labels', () => {
  it('names the directorate in both locales', () => {
    expect(unitLabels('ru').directorate).toBe('Дирекция');
    expect(unitLabels('en').directorate).toBe('Directorate');
  });

  it('OrgChartNode maps unit_type=directorate to that key', () => {
    const source = fs.readFileSync(path.join(HERE, '..', 'OrgChartNode.tsx'), 'utf-8');
    expect(source).toContain("directorate: 'hr.orgChart.unit.directorate'");
  });
});
```

Run (из `frontend/`): `npx vitest run src/components/hr/OrgChart/__tests__/unitLabels.test.ts src/lib/i18n/__tests__/translationKeys.test.ts`
Expected: PASS оба файла (второй — общий сторож «ключ есть в ru»).

- [ ] **Step 8: Типы и коммит**

Run: `npx tsc --noEmit -p tsconfig.app.json 2>&1 | tail -1` — число ошибок не выше базовой линии (150).

```bash
git add backend/apps/hr/models.py backend/apps/hr/migrations/0023_alter_department_unit_type.py backend/apps/hr/tests/test_models_schema.py frontend/src/components/hr/OrgChart/OrgChartNode.tsx frontend/src/components/hr/OrgChart/__tests__/unitLabels.test.ts frontend/public/locales/ru/translation.json frontend/public/locales/en/translation.json
git commit -m "feat(hr): «Дирекция» — вид подразделения по оргструктуре группы

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Сид уровней N-1…N-4 в схеме компании — data-миграция `hr/0024`

**Files:**
- Create: `backend/apps/hr/migrations/0024_seed_level_thresholds.py`
- Test: `backend/apps/hr/tests/test_level_seed_migration.py`

**Interfaces:**
- Produces: модуль миграции с константой `LEVELS: list[tuple[int, int, int, str, str]]` = `(level_number, weight_from, weight_to, label, color)` и функцией `seed(apps, schema_editor)`. Задача 3 держит копию `LEVELS` в `group_structures.py` и тестом сверяет с миграцией.

- [ ] **Step 1: Падающие тесты**

`backend/apps/hr/tests/test_level_seed_migration.py`:

```python
"""hr/0024: пороги N-1…N-4 появляются в НОВОЙ схеме компании и нигде больше.

Сид миграции — единственный способ дать новой компании уровни до того, как
кадровик откроет экран: без порогов каждая должность молча падает в
``_DEFAULT_LEVEL = 5`` и иерархия схлопывается в один ярус (roadmap §4).
Но ``public`` — это и pytest-база, и dev до tenancy_bootstrap, и боевая HTQ
до переноса: засеять туда значило бы подменить данные ETL и сломать тесты,
которые заводят уровень 1 с нуля.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import connection

from apps.hr.models import LevelThreshold

migration = importlib.import_module("apps.hr.migrations.0024_seed_level_thresholds")


def _search_path() -> str:
    with connection.cursor() as cur:
        cur.execute("SHOW search_path")
        return cur.fetchone()[0]


@pytest.mark.django_db
def test_public_is_never_seeded():
    assert "co_" not in _search_path()
    migration.seed(django_apps, None)
    assert LevelThreshold.objects.count() == 0


def test_company_schema_gets_the_four_document_levels(company_context):
    LevelThreshold.objects.all().delete()  # пул схем мог засеять при миграции
    migration.seed(django_apps, None)
    rows = list(LevelThreshold.objects.order_by("level_number")
                .values_list("level_number", "weight_from", "weight_to", "label"))
    assert rows == [(1, 0, 99, "N-1"), (2, 100, 299, "N-2"),
                    (3, 300, 599, "N-3"), (4, 600, 1999, "N-4")]


def test_existing_thresholds_are_left_alone(company_context):
    """HTQ с порогами от ETL — no-op: ни строки не добавлено, ни правлено."""
    LevelThreshold.objects.all().delete()
    LevelThreshold.objects.create(level_number=7, weight_from=0, weight_to=5000,
                                  label="из ETL")
    migration.seed(django_apps, None)
    assert list(LevelThreshold.objects.values_list("level_number", "label")) == [(7, "из ETL")]


def test_levels_do_not_overlap_and_cover_the_weight_axis():
    levels = sorted(migration.LEVELS)
    for (_, a_from, a_to, *_), (_, b_from, _b_to, *_) in zip(levels, levels[1:]):
        assert a_to + 1 == b_from
    assert levels[0][1] == 0
    assert levels[-1][2] >= 1999  # верх шкалы старого сида и next-weight
```

- [ ] **Step 2: Убедиться, что падают**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_level_seed_migration.py -q`
Expected: FAIL/ERROR — `ModuleNotFoundError: ...0024_seed_level_thresholds`.

- [ ] **Step 3: Миграция**

`backend/apps/hr/migrations/0024_seed_level_thresholds.py`:

```python
"""Сид уровней N-1…N-4 для НОВОЙ схемы компании (блок D, roadmap §5.D).

Без порогов ``position_service._compute_level`` отдаёт запасной уровень 5
каждой должности, и оргструктура новой компании схлопывается в один ярус.
Сид — единственное место, где уровни появляются раньше кадровика.

Два условия, оба обязательны:

* **только в схеме компании** — ``migrate_company`` не ставит контекст
  компании (только ``search_path`` без ``public``), поэтому «где я» читается
  из ``search_path``. ``public`` — это pytest-база, dev до
  ``tenancy_bootstrap`` и боевая HTQ до переноса; засеять туда значило бы
  подменить данные ETL и сломать тесты, заводящие уровень 1 с нуля;
* **только в пустую таблицу** — у HTQ пороги уже есть от ETL: no-op.

Обратной операции нет намеренно: ``migrate_companies`` откатов не делает
(«только ВПЕРЁД»), а отличить засеянные строки от правленных потом нельзя.

Копия ``LEVELS`` живёт в ``apps/hr/management/group_structures.py`` для
демо-сида; тест ``test_group_structures.py`` держит их равными. Миграция
не импортирует код аппки: её содержимое обязано быть заморожено.
"""

from django.db import connection, migrations

from htqweb.tenancy.context import SCHEMA_PREFIX

# (level_number, weight_from, weight_to, label, color)
# N-4 доходит до 1999: верх шкалы старого сида и next-weight — ни один вес не
# должен проваливаться в запасной уровень.
LEVELS = [
    (1, 0, 99, "N-1", "#7c3aed"),
    (2, 100, 299, "N-2", "#2563eb"),
    (3, 300, 599, "N-3", "#0891b2"),
    (4, 600, 1999, "N-4", "#059669"),
]


def _in_company_schema() -> bool:
    with connection.cursor() as cur:
        cur.execute("SHOW search_path")
        (path,) = cur.fetchone()
    first = path.split(",")[0].strip().strip('"')
    return first.startswith(SCHEMA_PREFIX)


def seed(apps, schema_editor):
    if not _in_company_schema():
        return
    LevelThreshold = apps.get_model("hr", "LevelThreshold")
    if LevelThreshold.objects.exists():
        return
    LevelThreshold.objects.bulk_create([
        LevelThreshold(level_number=number, weight_from=w_from, weight_to=w_to,
                       label=label, color=color)
        for number, w_from, w_to, label, color in LEVELS
    ])


class Migration(migrations.Migration):

    dependencies = [("hr", "0023_alter_department_unit_type")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
```

Проверить, что `SCHEMA_PREFIX` действительно экспортируется из `htqweb/tenancy/context.py` (используется `schema_for`); если имя другое — взять его.

- [ ] **Step 4: Тесты зелёные**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_level_seed_migration.py -q`
Expected: 4 passed (первый тест `company_context` заводит схему пула — ~1 мин на старте модуля).

- [ ] **Step 5: Смежные сторожа**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_positions_api.py apps/companies/tests/test_migration_service.py apps/core/tests/test_invariants.py -q`
Expected: как до задачи (в `public` сид не срабатывает, `test_positions_api` не видит чужих порогов).

- [ ] **Step 6: Коммит**

```bash
git add backend/apps/hr/migrations/0024_seed_level_thresholds.py backend/apps/hr/tests/test_level_seed_migration.py
git commit -m "feat(hr): новая схема компании рождается с уровнями N-1…N-4

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Справочник четырёх оргструктур — `group_structures.py`

**Files:**
- Create: `backend/apps/hr/management/group_structures.py`
- Test: `backend/apps/hr/tests/test_group_structures.py`

**Interfaces:**
- Produces (используют задачи 4 и 6):
  - `LEVELS` — та же форма, что в `hr/0024`;
  - `@dataclass(frozen=True) Unit(path, name, unit_type, description="")`;
  - `@dataclass(frozen=True) Post(title, unit, weight, grade, hr_level, reports_to=None, is_manager=False, external_hierarchy="none", serves_subsidiaries=False)`;
  - `@dataclass(frozen=True) Person(last, first, middle, post, phone)`;
  - `@dataclass(frozen=True) Structure(kind, company_name, units, posts, people, functional_links, managers)`;
  - `STRUCTURES: dict[str, Structure]` с ключами `"holding" | "construction" | "it" | "service"`;
  - `structure_for(kind: str) -> Structure` — `KeyError`-безопасный: `UnknownStructure(ValueError)` с текстом для CLI;
  - `level_for(weight: int) -> int | None`.

- [ ] **Step 1: Падающие тесты — данные против документа**

`backend/apps/hr/tests/test_group_structures.py`:

```python
"""Справочник оргструктур группы обязан совпадать с документом 10.09.2026.

Это не «тест на константы»: справочник сеется в четыре схемы и по нему
смотрят стенд глазами. Числа взяты со стр. 2–5 документа — «Руководители —
4, Менеджеры — 8, всего 12», «Руководители — 1, Специалисты — 3, всего 4».
"""

from __future__ import annotations

import importlib

import pytest

from apps.hr.management import group_structures as gs

migration = importlib.import_module("apps.hr.migrations.0024_seed_level_thresholds")

HOLDING = gs.STRUCTURES["holding"]
HTQ = gs.STRUCTURES["construction"]
HTS = gs.STRUCTURES["it"]
KEG = gs.STRUCTURES["service"]


def test_levels_match_the_migration_seed():
    assert gs.LEVELS == migration.LEVELS


def test_one_structure_per_company_kind():
    from apps.companies.models import CompanyKind  # тесты вне сторожа изоляции
    assert set(gs.STRUCTURES) == {k.value for k in CompanyKind} - {"regional"}
    with pytest.raises(gs.UnknownStructure, match="regional"):
        gs.structure_for("regional")


@pytest.mark.parametrize("structure, posts, people", [
    (HOLDING, 12, 12), (HTQ, 4, 4), (HTS, 4, 4), (KEG, 4, 4),
])
def test_headcount_matches_the_document(structure, posts, people):
    assert len(structure.posts) == posts
    assert len(structure.people) == people
    assert len({p.title for p in structure.posts}) == posts  # title unique в схеме
    assert len({p.weight for p in structure.posts}) == posts  # weight unique в схеме


def test_holding_has_four_managers_and_eight_serving_specialists():
    directors = [p for p in HOLDING.posts if p.is_manager]
    serving = [p for p in HOLDING.posts if p.serves_subsidiaries]
    assert len(directors) == 4 and len(serving) == 8
    assert not {p.title for p in directors} & {p.title for p in serving}
    assert all(p.external_hierarchy == "inherit" for p in directors)


@pytest.mark.parametrize("structure, levels", [
    (HOLDING, {1, 2, 4}),      # N-3 пропущен (стр. 2)
    (HTQ, {1, 2, 4}),          # N-3 пропущен (стр. 3)
    (HTS, {1, 2, 3, 4}),       # стр. 4
    (KEG, {1, 3, 4}),          # N-2 пуст (стр. 5)
])
def test_levels_used_by_each_structure(structure, levels):
    assert {gs.level_for(p.weight) for p in structure.posts} == levels


@pytest.mark.parametrize("structure", [HOLDING, HTQ, HTS, KEG])
def test_every_reference_resolves(structure):
    titles = {p.title for p in structure.posts}
    paths = {u.path for u in structure.units}
    heads = [p for p in structure.posts if p.reports_to is None]
    assert len(heads) == 1, "ровно одна должность без начальника — глава компании"
    for post in structure.posts:
        assert post.unit in paths
        assert post.reports_to is None or post.reports_to in titles
    for person in structure.people:
        assert person.post in titles
    for a, b in structure.functional_links:
        assert a in titles and b in titles and a != b
    for path, title in structure.managers.items():
        assert path in paths and title in titles
        # Руководитель обязан работать в своём подразделении (инвариант дерева).
        assert next(p for p in structure.posts if p.title == title).unit == path


def test_subsidiary_heads_are_directors_not_general_directors():
    """Правка Садыева: в ДО «Директор», не «Генеральный директор»."""
    for s in (HTQ, HTS, KEG):
        head = next(p for p in s.posts if p.reports_to is None)
        assert head.title == "Директор"
    assert next(p for p in HOLDING.posts if p.reports_to is None).title == "Генеральный директор"


def test_holding_directorates_are_directorates():
    assert [u.unit_type for u in HOLDING.units if u.path != "upr"] == ["directorate"] * 3


def test_functional_links_are_exactly_the_dashed_lines():
    assert HOLDING.functional_links == (
        ("Главный бухгалтер", "ГИП"),
        ("ГИП", "Менеджер по кадрам"),
        ("Менеджер ПТО и КК", "Менеджер по закупкам"),
    )
    assert all(s.functional_links == () for s in (HTQ, HTS, KEG))


def test_emails_are_unique_across_the_whole_group():
    """Учётки платформы общие на группу — почта не может повториться."""
    emails = [gs.email_for(p) for s in gs.STRUCTURES.values() for p in s.people]
    assert len(emails) == len(set(emails))
```

- [ ] **Step 2: Убедиться, что падают**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_group_structures.py -q`
Expected: ERROR при импорте — `ModuleNotFoundError: apps.hr.management.group_structures`.

- [ ] **Step 3: Модуль данных**

`backend/apps/hr/management/group_structures.py`:

```python
"""Четыре оргструктуры группы по документу «Обновленный проект Оргструктуры
Группы — комменты Куаныш Садыев от 10.09.2026», стр. 2–5.

Только данные и две чистые функции; кладёт их в базу ``seed_hr_demo``.
Ключ словаря — ``Company.kind`` (строка, не enum: apps.hr не импортирует
apps.companies.models). Для legacy-``regional`` структуры нет.

Что здесь из документа, а что придумано для стенда:

* должности, уровни, подчинение, пунктирные связи, «1 шт. ед.» — документ;
* три дирекции холдинга и их описания — документ (стр. 1–2);
* подразделения ДОЧЕРНИХ компаний документ не задаёт — здесь минимум:
  «Руководство» + один профильный отдел; путь ``stroy`` у HTQ сохранён,
  потому что его читает ``seed_tasks_demo``;
* люди, телефоны, grade, hr_level — демо.

Признаки блоков B и C выставляются по смыслу документа: дирекции
«координируют и контролируют деятельность компаний группы» (стр. 1) →
директора холдинга ``is_manager`` + ``inherit``; восемь менеджеров
холдинга обслуживают ДО (решение 2 блока C) → ``serves_subsidiaries``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Копия hr/0024_seed_level_thresholds.LEVELS — миграция обязана быть
# заморожена и код аппки не импортирует; равенство держит
# tests/test_group_structures.py::test_levels_match_the_migration_seed.
LEVELS = [
    (1, 0, 99, "N-1", "#7c3aed"),
    (2, 100, 299, "N-2", "#2563eb"),
    (3, 300, 599, "N-3", "#0891b2"),
    (4, 600, 1999, "N-4", "#059669"),
]


def level_for(weight: int) -> int | None:
    return next((n for n, w_from, w_to, *_ in LEVELS if w_from <= weight <= w_to), None)


class UnknownStructure(ValueError):
    pass


@dataclass(frozen=True)
class Unit:
    path: str
    name: str
    unit_type: str = "department"
    description: str = ""


@dataclass(frozen=True)
class Post:
    title: str
    unit: str
    weight: int
    grade: int
    hr_level: str
    reports_to: str | None = None
    is_manager: bool = False
    external_hierarchy: str = "none"
    serves_subsidiaries: bool = False


@dataclass(frozen=True)
class Person:
    last: str
    first: str
    middle: str
    post: str
    phone: str


@dataclass(frozen=True)
class Structure:
    kind: str
    company_name: str
    units: tuple[Unit, ...]
    posts: tuple[Post, ...]
    people: tuple[Person, ...]
    functional_links: tuple[tuple[str, str], ...] = ()
    managers: dict[str, str] = field(default_factory=dict)  # путь отдела -> должность


def _translit(text: str) -> str:
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    return "".join(table.get(ch, ch if ch.isalnum() and ch.isascii() else "")
                   for ch in text.lower())


def email_for(person: Person) -> str:
    """Служебная почта: фамилия.инициал@htq.kz — общая для всей группы."""
    return f"{_translit(person.last)}.{_translit(person.first)[:1]}@htq.kz"


# ── Холдинг: ТОО «Hi-Tech Group LTD» (стр. 1–2) ──────────────────────────
_HOLDING = Structure(
    kind="holding",
    company_name="Hi-Tech Group LTD",
    units=(
        Unit("upr", "Руководство"),
        Unit("fin", "Дирекция по финансам и экономике", "directorate",
             "Централизованное управление финансами группы: бюджетирование, "
             "казначейство, управленческий учёт, контроль расходов и "
             "обязательств, консолидированная отчётность."),
        Unit("pto", "Проектно-техническая дирекция", "directorate",
             "Внутренний проектный центр: инженерно-технические решения, "
             "расчёты, проектная, рабочая и сметная документация, авторское "
             "сопровождение."),
        Unit("ops", "Дирекция по операционной деятельности", "directorate",
             "Координация и контроль текущей деятельности компаний группы, "
             "бизнес-процессы, исполнение решений, ресурсы."),
    ),
    posts=(
        Post("Генеральный директор", "upr", 10, 10, "lead",
             is_manager=True, external_hierarchy="inherit"),
        Post("Финансовый директор", "fin", 110, 9, "senior", "Генеральный директор",
             is_manager=True, external_hierarchy="inherit"),
        Post("Технический директор", "pto", 120, 9, "senior", "Генеральный директор",
             is_manager=True, external_hierarchy="inherit"),
        Post("Операционный директор", "ops", 130, 9, "senior", "Генеральный директор",
             is_manager=True, external_hierarchy="inherit"),
        Post("Главный бухгалтер", "fin", 610, 8, "middle", "Финансовый директор",
             serves_subsidiaries=True),
        Post("Кадровый бухгалтер", "fin", 620, 6, "middle", "Финансовый директор",
             serves_subsidiaries=True),
        Post("Экономист-аналитик", "fin", 630, 6, "junior", "Финансовый директор",
             serves_subsidiaries=True),
        Post("ГИП", "pto", 640, 8, "middle", "Технический директор",
             serves_subsidiaries=True),
        Post("Менеджер ПТО и КК", "pto", 650, 6, "junior", "Технический директор",
             serves_subsidiaries=True),
        Post("Менеджер по кадрам", "ops", 660, 7, "senior", "Операционный директор",
             serves_subsidiaries=True),
        Post("Менеджер по закупкам", "ops", 670, 6, "junior", "Операционный директор",
             serves_subsidiaries=True),
        Post("Системный администратор", "ops", 680, 6, "junior", "Операционный директор",
             serves_subsidiaries=True),
    ),
    people=(
        Person("Абдрахманов", "Ерлан", "Серикович", "Генеральный директор", "+7 (700) 100-10-01"),
        Person("Тулегенов", "Аскар", "Муратович", "Финансовый директор", "+7 (700) 100-20-01"),
        Person("Ким", "Светлана", "Юрьевна", "Главный бухгалтер", "+7 (700) 100-20-02"),
        Person("Досжанова", "Аружан", "Ерлановна", "Кадровый бухгалтер", "+7 (700) 100-20-03"),
        Person("Сейткали", "Айдана", "Нурлановна", "Экономист-аналитик", "+7 (700) 100-20-04"),
        Person("Нурсеитов", "Данияр", "Маратович", "Технический директор", "+7 (700) 100-30-01"),
        Person("Байжанов", "Кайрат", "Ерболович", "ГИП", "+7 (700) 100-30-02"),
        Person("Садыков", "Арман", "Болатович", "Менеджер ПТО и КК", "+7 (700) 100-30-03"),
        Person("Ким", "Виктор", "Андреевич", "Операционный директор", "+7 (700) 100-40-01"),
        Person("Сулейменова", "Динара", "Кайратовна", "Менеджер по кадрам", "+7 (700) 100-40-02"),
        Person("Дюсенов", "Марат", "Жомартович", "Менеджер по закупкам", "+7 (700) 100-40-03"),
        Person("Абишев", "Нурбол", "Талгатович", "Системный администратор", "+7 (700) 100-40-04"),
    ),
    # Пунктирные горизонтальные связи стр. 2, слева направо.
    functional_links=(
        ("Главный бухгалтер", "ГИП"),
        ("ГИП", "Менеджер по кадрам"),
        ("Менеджер ПТО и КК", "Менеджер по закупкам"),
    ),
    managers={"upr": "Генеральный директор", "fin": "Финансовый директор",
              "pto": "Технический директор", "ops": "Операционный директор"},
)

# ── ТОО «HI-TECH QAZAQSTAN», строительная (стр. 3) ───────────────────────
# «Генеральный» зачёркнуто — «Директор». N-4: два названных блока и один
# пустой; пустой не сеется (вопрос руководству, roadmap §8.3).
_HTQ = Structure(
    kind="construction",
    company_name="Hi-Tech Qazaqstan",
    units=(
        Unit("upr", "Руководство"),
        Unit("stroy", "Строительство",
             description="Работы на объектах. Путь читает seed_tasks_demo."),
    ),
    posts=(
        Post("Директор", "upr", 10, 10, "lead", is_manager=True),
        Post("Руководитель проекта", "stroy", 110, 8, "senior", "Директор", is_manager=True),
        Post("Начальник участка", "stroy", 610, 7, "middle", "Руководитель проекта"),
        Post("Инженер по ОТ и ТБ", "stroy", 620, 5, "junior", "Руководитель проекта"),
    ),
    people=(
        Person("Исаев", "Тимур", "Русланович", "Директор", "+7 (701) 200-10-01"),
        Person("Оспанов", "Бекзат", "Асхатович", "Руководитель проекта", "+7 (701) 200-20-01"),
        Person("Жумабеков", "Асхат", "Нурланович", "Начальник участка", "+7 (701) 200-20-02"),
        Person("Ткаченко", "Сергей", "Павлович", "Инженер по ОТ и ТБ", "+7 (701) 200-20-03"),
    ),
    managers={"upr": "Директор", "stroy": "Руководитель проекта"},
)

# ── ТОО «HI-TECH SYSTEMS», IT (стр. 4) — все трое подчинены директору ─────
_HTS = Structure(
    kind="it",
    company_name="Hi-Tech Systems",
    units=(Unit("upr", "Руководство"), Unit("dev", "Разработка")),
    posts=(
        Post("Директор", "upr", 10, 10, "lead", is_manager=True),
        Post("Senior Full-stack developer", "dev", 110, 8, "senior", "Директор"),
        Post("Middle Full-stack developer", "dev", 310, 6, "middle", "Директор"),
        Post("Junior Full-stack developer", "dev", 610, 4, "junior", "Директор"),
    ),
    people=(
        Person("Волков", "Дмитрий", "Олегович", "Директор", "+7 (702) 300-10-01"),
        Person("Ли", "Александр", "Витальевич", "Senior Full-stack developer", "+7 (702) 300-20-01"),
        Person("Мукашев", "Нурлан", "Кайратович", "Middle Full-stack developer", "+7 (702) 300-20-02"),
        Person("Шевченко", "Ольга", "Ивановна", "Junior Full-stack developer", "+7 (702) 300-20-03"),
    ),
    managers={"upr": "Директор"},
)

# ── ТОО «KAZAKHSTAN ENGINEERING GROUP», сервисная (стр. 5) ───────────────
_KEG = Structure(
    kind="service",
    company_name="Kazakhstan Engineering Group",
    units=(Unit("upr", "Руководство"), Unit("ops", "Эксплуатация")),
    posts=(
        Post("Директор", "upr", 10, 10, "lead", is_manager=True),
        Post("Диспетчер", "ops", 310, 5, "middle", "Директор"),
        Post("Механик", "ops", 610, 5, "junior", "Директор"),
        Post("Водитель-оператор", "ops", 620, 4, "junior", "Директор"),
    ),
    people=(
        Person("Ахметова", "Айгуль", "Талгатовна", "Директор", "+7 (705) 400-10-01"),
        Person("Копылова", "Наталья", "Сергеевна", "Диспетчер", "+7 (705) 400-20-01"),
        Person("Петров", "Игорь", "Николаевич", "Механик", "+7 (705) 400-20-02"),
        Person("Ерсултанова", "Жанар", "Бахытовна", "Водитель-оператор", "+7 (705) 400-20-03"),
    ),
    managers={"upr": "Директор"},
)

STRUCTURES: dict[str, Structure] = {s.kind: s for s in (_HOLDING, _HTQ, _HTS, _KEG)}


def structure_for(kind: str) -> Structure:
    try:
        return STRUCTURES[kind]
    except KeyError:
        raise UnknownStructure(
            f"Для вида компании {kind!r} утверждённой оргструктуры нет "
            f"(есть: {', '.join(sorted(STRUCTURES))})."
        ) from None
```

- [ ] **Step 4: Тесты зелёные**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_group_structures.py -q`
Expected: все passed.

- [ ] **Step 5: Сторож изоляции**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_app_isolation.py -q`
Expected: PASS (модуль не импортирует чужих аппок; импорт `CompanyKind` — только в тесте).

- [ ] **Step 6: Коммит**

```bash
git add backend/apps/hr/management/group_structures.py backend/apps/hr/tests/test_group_structures.py
git commit -m "feat(hr): справочник четырёх оргструктур группы по документу 10.09.2026

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `seed_hr_demo` сеет структуру по виду компании, `--company`

**Files:**
- Modify: `backend/apps/companies/interface.py` (+ `schema_exists`)
- Modify: `backend/apps/hr/management/commands/seed_hr_demo.py` (переписать константы и шаги)
- Test: `backend/apps/hr/tests/test_seed_hr_demo.py` (переписать под новую структуру), `backend/apps/companies/tests/test_interface.py` (+1 тест)

**Interfaces:**
- Consumes: `group_structures.{STRUCTURES, structure_for, level_for, LEVELS, email_for, UnknownStructure}`; `htqweb.tenancy.db.use_company`; `apps.companies.interface.{get_company, schema_exists}`.
- Produces: `manage.py seed_hr_demo [--company SLUG] [--purge-e2e] [--force-remote]`; без `--company` — структура `construction` в текущий `search_path`. Опция объявлена как `parser.add_argument("--company", dest="company")` — задача 6 вызывает `call_command("seed_hr_demo", company=slug)`.

- [ ] **Step 1: `schema_exists` в интерфейсе компаний — тест**

В `backend/apps/companies/tests/test_interface.py` добавить:

```python
def test_schema_exists_reports_the_physical_schema(company_schema):
    from apps.companies import interface
    assert interface.schema_exists(company_schema["slug"]) is True
    assert interface.schema_exists("t-no-such-company") is False
```

Run: `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_interface.py -q -k schema_exists` → FAIL `AttributeError`.

- [ ] **Step 2: `schema_exists` в интерфейсе**

`backend/apps/companies/interface.py` — рядом с `get_company`:

```python
def schema_exists(slug: str) -> bool:
    """Есть ли у компании ФИЗИЧЕСКАЯ схема.

    Строка реестра и схема — разные факты (осиротевшая строка после
    неудачного отката ``company_create``, см. CLAUDE.md). ``SET search_path``
    молча принимает несуществующую схему, и запросы уходят в ``public`` —
    поэтому команда, входящая в схему по slug, обязана спросить это до входа.
    """
    from apps.companies.services import schema_service
    return schema_service.schema_exists(slug)
```

Run тот же тест → PASS.

- [ ] **Step 3: Переписать тесты сида под утверждённую структуру**

`backend/apps/hr/tests/test_seed_hr_demo.py` — заменить содержимое целиком (сторожа локальной БД сохраняются как были):

```python
"""Команда наполнения HR демо-данными — четыре оргструктуры документа.

Наполнение — такой же код, как остальной: если оно молча перестанет
связывать сотрудника с отделом его должности или дублировать записи при
повторном запуске, локальная база начнёт врать, а по ней потом смотрят
глазами и делают выводы.

Без ``--company`` команда сеет структуру HTQ в текущий ``search_path``
(режим перехода: единственная компания — HTQ). С ``--company`` — входит в
схему компании и сеет структуру её ``kind``.

Отдельно проверяется защита от неместной БД: ``DB_HOST`` по умолчанию
приходит из корневого ``.env``, где стоит боевой адрес.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.hr.management import group_structures as gs
from apps.hr.models import (
    Department, Employee, LevelThreshold, Position, ReportingRelation,
    StaffingPosition,
)


def _seed(**kwargs):
    call_command("seed_hr_demo", verbosity=0, **kwargs)


HTQ = gs.STRUCTURES["construction"]


@pytest.mark.django_db
def test_seed_without_company_is_the_construction_structure():
    _seed()
    assert LevelThreshold.objects.count() == 4
    assert set(Department.objects.values_list("path", flat=True)) == {"upr", "stroy"}
    assert set(Position.objects.values_list("title", flat=True)) == {p.title for p in HTQ.posts}
    assert Employee.objects.count() == 4
    assert ReportingRelation.objects.filter(relation_type="direct").count() == 3
    assert StaffingPosition.objects.count() == 4
    assert all(line.headcount == 1 for line in StaffingPosition.objects.all())


@pytest.mark.django_db
def test_seed_is_idempotent():
    _seed()
    counts = (LevelThreshold.objects.count(), Department.objects.count(),
              Position.objects.count(), Employee.objects.count(),
              ReportingRelation.objects.count(), StaffingPosition.objects.count())
    _seed()
    assert (LevelThreshold.objects.count(), Department.objects.count(),
            Position.objects.count(), Employee.objects.count(),
            ReportingRelation.objects.count(), StaffingPosition.objects.count()) == counts


@pytest.mark.django_db
def test_no_position_falls_into_the_default_level():
    _seed()
    for pos in Position.objects.all():
        assert pos.level == gs.level_for(pos.weight), pos.title
        assert pos.level != 5


@pytest.mark.django_db
def test_seed_retires_foreign_levels_and_recomputes_cached_levels():
    """Старый пятиуровневый сид на dev-базе: L5 (900–1999) пересёкся бы с
    N-4, а кэш уровня у старых должностей остался бы прежним."""
    dep = Department.objects.create(name="Старый", path="old")
    LevelThreshold.objects.create(level_number=5, weight_from=900, weight_to=1999)
    stale = Position.objects.create(title="Старая должность", department=dep,
                                    weight=950, level=5)
    _seed()
    assert not LevelThreshold.objects.filter(level_number=5).exists()
    stale.refresh_from_db()
    assert stale.level == 4


@pytest.mark.django_db
def test_employee_department_always_matches_their_position():
    _seed()
    mismatched = [e.email for e in Employee.objects.select_related("position")
                  if e.department_id != e.position.department_id]
    assert mismatched == []


@pytest.mark.django_db
def test_department_managers_work_in_their_own_department():
    _seed()
    for path, title in HTQ.managers.items():
        dept = Department.objects.get(path=path)
        assert dept.manager is not None, path
        assert dept.manager.position.title == title
        assert dept.manager.department_id == dept.id


@pytest.mark.django_db
def test_direct_relations_follow_the_document():
    _seed()
    by_title = {p.title: p for p in Position.objects.all()}
    for post in HTQ.posts:
        if post.reports_to is None:
            assert not ReportingRelation.objects.filter(
                subordinate_position=by_title[post.title]).exists()
            continue
        assert ReportingRelation.objects.filter(
            superior_position=by_title[post.reports_to],
            subordinate_position=by_title[post.title],
            relation_type="direct",
        ).exists(), post.title


@pytest.mark.django_db
def test_block_b_and_c_flags_come_from_the_structure():
    _seed()
    director = Position.objects.get(title="Директор")
    assert director.is_manager is True
    assert director.external_hierarchy == "none"
    assert not Position.objects.filter(serves_subsidiaries=True).exists()


@pytest.mark.django_db
def test_positions_carry_an_explicit_hr_level():
    _seed()
    for pos in Position.objects.all():
        assert pos.permissions["hr_level"] in {"junior", "middle", "senior", "lead"}, pos.title


@pytest.mark.django_db
def test_phones_use_the_platform_mask():
    import re
    _seed()
    mask = re.compile(r"^\+7 \(7\d\d\) \d{3}-\d\d-\d\d$")
    for e in Employee.objects.all():
        assert mask.match(e.phone), e.phone


# ── --company ────────────────────────────────────────────────────────────

def test_company_option_seeds_the_structure_of_its_kind(company_schema):
    """Фикстура заводит компанию kind=service → структура KEG, в её схеме."""
    from htqweb.tenancy.db import use_company

    _seed(company=company_schema["slug"])
    with use_company(company_schema["slug"]):
        assert set(Position.objects.values_list("title", flat=True)) == {
            "Директор", "Диспетчер", "Механик", "Водитель-оператор"}
        assert set(LevelThreshold.objects.values_list("level_number", flat=True)) == {1, 2, 3, 4}
    # public не тронут.
    assert Position.objects.count() == 0


def test_holding_structure_sets_serving_and_managing_flags(company_schema):
    from django.core.cache import cache

    from apps.companies.models import Company
    from htqweb.tenancy.db import use_company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="holding")
    cache.clear()  # get_company кэширует 5 с
    _seed(company=company_schema["slug"])
    with use_company(company_schema["slug"]):
        assert Position.objects.filter(serves_subsidiaries=True).count() == 8
        assert Position.objects.filter(is_manager=True, external_hierarchy="inherit").count() == 4
        assert Department.objects.filter(unit_type="directorate").count() == 3
        assert ReportingRelation.objects.filter(relation_type="functional").count() == 3
        assert ReportingRelation.objects.filter(relation_type="direct").count() == 11


def test_company_option_rejects_unknown_company(db):
    with pytest.raises(CommandError, match="не найдена"):
        _seed(company="t-no-such-company")


def test_company_option_rejects_a_company_without_schema(db):
    from apps.companies.models import Company, CompanyKind
    Company.objects.create(slug="t-orphan", name="Сирота", kind=CompanyKind.SERVICE)
    with pytest.raises(CommandError, match="схем"):
        _seed(company="t-orphan")


def test_company_option_rejects_legacy_regional_kind(company_schema):
    from django.core.cache import cache

    from apps.companies.models import Company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="regional")
    cache.clear()
    with pytest.raises(CommandError, match="regional"):
        _seed(company=company_schema["slug"])


# ── --purge-e2e и защита от неместной БД: перенести из прежней версии файла
# без изменений (test_purge_removes_e2e_leftovers_only,
# test_refuses_to_run_against_a_remote_database, test_local_hosts_pass_the_guard,
# test_force_remote_is_the_only_way_past_the_guard,
# test_guard_runs_before_anything_is_written).
```

Пять тестов из последнего комментария взять из текущего файла (`git show HEAD:backend/apps/hr/tests/test_seed_hr_demo.py`) дословно.

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_seed_hr_demo.py -q` → FAIL (старая структура: `LevelThreshold == 5`, нет `--company`).

- [ ] **Step 4: Переписать команду**

`backend/apps/hr/management/commands/seed_hr_demo.py`. Убрать константы `LEVELS/DEPARTMENTS/POSITIONS/EMPLOYEES/MANAGERS` и `_translit` (переехали в `group_structures`). Докстринг модуля обновить: «сеет одну из четырёх оргструктур документа 10.09.2026 (`apps/hr/management/group_structures.py`); без `--company` — структуру HTQ в текущий `search_path`; порядок шагов — уровни → отделы → должности → люди → руководители → подчинение → штатное расписание, причины прежние (FK, кэш уровня)». Импорты и `add_arguments`:

```python
import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.hr.management import group_structures as gs
from apps.hr.models import (
    Department, Employee, LevelThreshold, Position, ReportingRelation,
    StaffingPosition,
)
from apps.hr.services.position_service import _DEFAULT_LEVEL

# Дата документа: с неё «действуют» связи подчинения.
STRUCTURE_EFFECTIVE_FROM = dt.date(2026, 9, 10)
```

```python
    def add_arguments(self, parser):
        parser.add_argument(
            "--company", dest="company", default=None,
            help="slug компании: войти в её схему и засеять структуру её вида "
                 "(holding/construction/it/service). Без флага — структура "
                 "HTQ в текущий search_path (режим перехода).",
        )
        parser.add_argument("--force-remote", action="store_true",
                            help="Снять защиту от неместной БД. Не используйте.")
        parser.add_argument("--purge-e2e", action="store_true",
                            help="Сначала удалить следы E2E-прогонов (префиксы «E2E » и «UI »).")
```

`_assert_local` и `_purge_e2e` — без изменений. `handle`:

```python
    def handle(self, *args, **options):
        self._assert_local(options["force_remote"])
        slug = options["company"]
        if slug is None:
            # Режим перехода (roadmap §3): единственная компания — HTQ, её
            # таблицы — там, куда указывает текущий search_path.
            self._run(gs.structure_for("construction"), options)
            return

        from apps.companies import interface as companies

        company = companies.get_company(slug)
        if company is None:
            raise CommandError(f"Компания {slug!r} не найдена в реестре.")
        if not companies.schema_exists(slug):
            raise CommandError(
                f"У компании {slug!r} нет схемы Postgres — SET search_path принял "
                f"бы её молча и данные ушли бы в public. Заведите схему: "
                f"manage.py company_create либо migrate_companies --company {slug}."
            )
        try:
            structure = gs.structure_for(company["kind"])
        except gs.UnknownStructure as exc:
            raise CommandError(str(exc)) from exc

        from htqweb.tenancy.db import use_company

        with use_company(slug):
            self.stdout.write(f"Компания {slug} ({company['kind']}): {structure.company_name}")
            self._run(structure, options)

    @transaction.atomic
    def _run(self, structure: gs.Structure, options) -> None:
        if options["purge_e2e"]:
            self._purge_e2e()
        levels = self._seed_levels()
        units = self._seed_units(structure)
        positions = self._seed_positions(structure, units)
        employees = self._seed_employees(structure, positions)
        managers = self._seed_managers(structure, units, positions, employees)
        relations = self._seed_relations(structure, positions)
        staffing = self._seed_staffing(positions)
        self.stdout.write(self.style.SUCCESS(
            f"\nГотово: уровней {levels}, подразделений {len(units)}, должностей "
            f"{len(positions)}, сотрудников {len(employees)}, руководителей "
            f"{managers}, связей подчинения {relations}, штатных единиц {staffing}."
        ))
```

`@transaction.atomic` переезжает с `handle` на `_run`: `use_company` обязан войти в схему до открытия транзакции и выйти после её закрытия, иначе `SET search_path` внутри откаченной транзакции оставил бы соединение в чужой схеме.

Шаги:

```python
    def _seed_levels(self) -> int:
        self.stdout.write("Уровни должностей...")
        for number, w_from, w_to, label, color in gs.LEVELS:
            LevelThreshold.objects.update_or_create(
                level_number=number,
                defaults={"weight_from": w_from, "weight_to": w_to,
                          "label": label, "color": color},
            )
        # Незаявленные уровни (например L5 старого сида, 900–1999) пересеклись
        # бы с N-4 и оставили бы кэш уровня у старых должностей стар.
        retired, _ = LevelThreshold.objects.exclude(
            level_number__in=[n for n, *_ in gs.LEVELS]).delete()
        recomputed = 0
        for pos in Position.objects.all():
            level = gs.level_for(pos.weight) or _DEFAULT_LEVEL
            if pos.level != level:
                Position.objects.filter(pk=pos.pk).update(level=level)
                recomputed += 1
        self.stdout.write(f"  {len(gs.LEVELS)} порогов; убрано чужих {retired}, "
                          f"пересчитано должностей {recomputed}")
        return len(gs.LEVELS)

    def _seed_units(self, structure) -> dict[str, Department]:
        self.stdout.write("Подразделения...")
        out: dict[str, Department] = {}
        for unit in structure.units:
            dept, _ = Department.objects.update_or_create(
                path=unit.path,
                defaults={"name": unit.name, "description": unit.description or None,
                          "unit_type": unit.unit_type, "is_active": True},
            )
            out[unit.path] = dept
        self.stdout.write(f"  {len(out)}")
        return out

    def _seed_positions(self, structure, units) -> dict[str, Position]:
        self.stdout.write("Должности...")
        out: dict[str, Position] = {}
        for post in structure.posts:
            level = gs.level_for(post.weight)
            assert level is not None, f"{post.title}: вес {post.weight} вне LEVELS"
            position, _ = Position.objects.update_or_create(
                title=post.title,
                defaults={
                    "department": units[post.unit],
                    "grade": post.grade,
                    "weight": post.weight,
                    "level": level,
                    "is_active": True,
                    "is_manager": post.is_manager,
                    "external_hierarchy": post.external_hierarchy,
                    "serves_subsidiaries": post.serves_subsidiaries,
                    # Явная матрица приоритетнее эвристики по названию —
                    # см. apps/hr/access.py.
                    "permissions": {"hr_level": post.hr_level, "permissions": []},
                },
            )
            out[post.title] = position
        self.stdout.write(f"  {len(out)}")
        return out

    def _seed_employees(self, structure, positions) -> dict[str, Employee]:
        self.stdout.write("Сотрудники...")
        out: dict[str, Employee] = {}
        hire_base = dt.date.today() - dt.timedelta(days=900)
        for index, person in enumerate(structure.people):
            position = positions[person.post]
            employee, _ = Employee.objects.update_or_create(
                email=gs.email_for(person),
                defaults={
                    "first_name": person.first, "last_name": person.last,
                    "middle_name": person.middle, "phone": person.phone,
                    # Отдел берётся у должности — связка «сотрудник → должность
                    # → отдел» не может разъехаться.
                    "department": position.department, "position": position,
                    "hire_date": hire_base + dt.timedelta(days=index * 21),
                    "status": "active", "is_deleted": False,
                },
            )
            out[person.post] = employee
        self.stdout.write(f"  {len(out)}")
        return out

    def _seed_managers(self, structure, units, positions, employees) -> int:
        self.stdout.write("Руководители подразделений...")
        count = 0
        for path, title in structure.managers.items():
            dept, holder = units[path], employees.get(title)
            if holder is None:
                continue
            dept.manager = holder
            dept.save(update_fields=["manager", "updated_at"])
            count += 1
        self.stdout.write(f"  {count}")
        return count

    def _seed_relations(self, structure, positions) -> int:
        """Вертикали документа — direct, пунктир — functional (по одной строке
        на пару, слева направо; модель направленная, документ — нет)."""
        self.stdout.write("Подчинение...")
        count = 0
        pairs = [(p.reports_to, p.title, "direct") for p in structure.posts if p.reports_to]
        pairs += [(a, b, "functional") for a, b in structure.functional_links]
        for superior, subordinate, kind in pairs:
            ReportingRelation.objects.update_or_create(
                superior_position=positions[superior],
                subordinate_position=positions[subordinate],
                relation_type=kind,
                defaults={"effective_from": STRUCTURE_EFFECTIVE_FROM, "effective_to": None},
            )
            count += 1
        self.stdout.write(f"  {count}")
        return count

    def _seed_staffing(self, positions) -> int:
        """«1 шт. ед.» у каждой должности документа."""
        self.stdout.write("Штатное расписание...")
        for position in positions.values():
            StaffingPosition.objects.update_or_create(
                position=position, department=position.department,
                defaults={"headcount": 1},
            )
        self.stdout.write(f"  {len(positions)}")
        return len(positions)
```

- [ ] **Step 5: Тесты зелёные**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_seed_hr_demo.py apps/hr/tests/test_group_structures.py -q`
Expected: все passed. Если `test_holding_structure_sets_serving_and_managing_flags` ловит `MultipleObjectsReturned` на `StaffingPosition` — значит в схеме пула остались строки от предыдущего теста; проверить, что `company_schema` чистит схему (`_truncate_schema`), и не ослаблять `update_or_create`.

- [ ] **Step 6: Соседи, читающие сид**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr -q` (≈9 мин, форграунд)
Expected: 2 падения — ровно `test_employees_api.py::test_{create,update}_employee_with_card_t2*` из `ci-known-failures.txt`. Иное — чинить до коммита.

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/companies/interface.py backend/apps/companies/tests/test_interface.py backend/apps/hr/management/commands/seed_hr_demo.py backend/apps/hr/tests/test_seed_hr_demo.py
git commit -m "feat(hr): seed_hr_demo сеет утверждённую оргструктуру по виду компании

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `--company` у `seed_employee_accounts` и `seed_tasks_demo`; пути отделов задач → структура HTQ

**Files:**
- Modify: `backend/apps/users/management/commands/seed_employee_accounts.py`
- Modify: `backend/apps/tasks/management/commands/seed_tasks_demo.py:170-202` (`department_path`), `:659-671` (аргументы), `:1280-1300` (`handle`), `:960-965`
- Test: `backend/apps/users/tests/test_seed_employee_accounts.py`, `backend/apps/tasks/tests/test_seed_tasks_demo.py`

**Interfaces:**
- Produces: `manage.py seed_employee_accounts [--company SLUG]`, `manage.py seed_tasks_demo [--company SLUG]` — обе с `dest="company"`, обе входят в схему через `use_company` до своей транзакции.

- [ ] **Step 1: Падающие тесты**

В `backend/apps/users/tests/test_seed_employee_accounts.py`:

```python
def test_company_option_reads_employees_from_that_schema(company_schema):
    """Сотрудники лежат в схеме компании; без входа в неё команда увидела бы
    пустой public и отказалась."""
    from htqweb.tenancy.db import use_company

    with use_company(company_schema["slug"]):
        department = Department.objects.create(name="Строительство", path="stroy")
        position = Position.objects.create(title="Инженер", department=department, weight=1000)
        Employee.objects.create(
            first_name="Имя", last_name="Фамилия", email="tenant@htq.test",
            department=department, position=position, hire_date="2024-01-09")

    _run(company=company_schema["slug"])

    user = User.objects.get(email="tenant@htq.test")
    with use_company(company_schema["slug"]):
        assert Employee.objects.get(email="tenant@htq.test").user_id == user.id


def test_company_option_rejects_unknown_company(db):
    with pytest.raises(CommandError, match="не найдена"):
        _run(company="t-no-such-company")
```

(`CommandError` импортировать из `django.core.management.base`, если в файле его ещё нет.)

В `backend/apps/tasks/tests/test_seed_tasks_demo.py` — фикстура `hr_data` заводит пути `stroy, stroy.elektro, proekt, snab`; заменить на ровно те, что даёт структура HTQ, чтобы тест не прикрывал расхождение:

```python
    for path, name in (("upr", "Руководство"), ("stroy", "Строительство")):
        departments[path] = Department.objects.create(name=name, path=path)
```

и добавить:

```python
def test_every_project_department_path_exists_in_the_htq_structure():
    """Пути отделов, которые ждёт сид задач, обязаны быть в утверждённой
    структуре HTQ — иначе проекты остаются без отдела молча (department_id
    nullable)."""
    from apps.hr.management import group_structures as gs  # тесты вне сторожа изоляции
    from apps.tasks.management.commands.seed_tasks_demo import PROJECTS

    paths = {u.path for u in gs.STRUCTURES["construction"].units}
    for spec in PROJECTS:
        assert spec["department_path"] in paths, spec["name"]


def test_company_option_writes_into_the_company_schema(company_schema):
    from htqweb.tenancy.db import use_company

    with use_company(company_schema["slug"]):
        departments = {}
        for path, name in (("upr", "Руководство"), ("stroy", "Строительство")):
            departments[path] = Department.objects.create(name=name, path=path)
        position = Position.objects.create(title="Инженер", department=departments["stroy"], weight=1000)
        for i in range(4):
            Employee.objects.create(
                first_name=f"Имя{i}", last_name=f"Фамилия{i}", email=f"seed{i}@htq.test",
                department=departments["stroy"], position=position,
                hire_date="2024-01-09", user_id=100 + i)

    _seed(company=company_schema["slug"])

    with use_company(company_schema["slug"]):
        assert Project.objects.count() >= 4
    assert Project.objects.count() == 0  # public не тронут
```

Run: `../.venv/Scripts/python.exe -m pytest apps/users/tests/test_seed_employee_accounts.py apps/tasks/tests/test_seed_tasks_demo.py -q -k "company or department_path"` → FAIL (нет опции; `stroy.elektro` не в структуре).

- [ ] **Step 2: `seed_employee_accounts`**

Добавить аргумент и вход в схему; тело `handle` вынести в `_run`, атомарность — на `_run` (та же причина, что в задаче 4):

```python
        parser.add_argument(
            "--company", dest="company", default=None,
            help="slug компании: сотрудники читаются из её схемы. Без флага — "
                 "текущий search_path (режим перехода).",
        )
```

```python
    def handle(self, *args, **options):
        self._assert_local(options["force_remote"])
        slug = options["company"]
        if slug is None:
            self._run(options)
            return
        from apps.companies import interface as companies
        from htqweb.tenancy.db import use_company

        if companies.get_company(slug) is None:
            raise CommandError(f"Компания {slug!r} не найдена в реестре.")
        if not companies.schema_exists(slug):
            raise CommandError(f"У компании {slug!r} нет схемы Postgres.")
        with use_company(slug):
            self._run(options)

    @transaction.atomic
    def _run(self, options) -> None:
        password = options["password"]
        employees = hr_interface.list_employees_brief()
        ...  # прежнее тело handle без изменений
```

`apps.users` уже импортирует `apps.companies.interface` (`views.py`) — направление зависимости не новое.

- [ ] **Step 3: `seed_tasks_demo`**

Аргумент `--company` (тот же текст help), `handle` → проверка компании и `use_company` вокруг вызова прежнего тела, вынесенного в `_run(options)`; `@transaction.atomic`, если он стоит на `handle`, переезжает на `_run`. В `PROJECTS` заменить `"department_path": "stroy.elektro"` и `"department_path": "proekt"` на `"stroy"` с комментарием над списком:

```python
# Пути отделов — из утверждённой структуры HTQ
# (apps/hr/management/group_structures.py): у строительной компании один
# профильный отдел ``stroy``. Прежние ``stroy.elektro``/``proekt`` были из
# старого одно-компанейского сида и оставляли бы проекты без отдела молча.
```

Строку `departments.get("stroy")` в запасной ветке (≈`:964`) оставить — путь сохранён именно ради неё.

- [ ] **Step 4: Тесты зелёные**

Run: `../.venv/Scripts/python.exe -m pytest apps/users/tests/test_seed_employee_accounts.py apps/tasks/tests/test_seed_tasks_demo.py -q`
Expected: все passed.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/users/management/commands/seed_employee_accounts.py backend/apps/users/tests/test_seed_employee_accounts.py backend/apps/tasks/management/commands/seed_tasks_demo.py backend/apps/tasks/tests/test_seed_tasks_demo.py
git commit -m "feat(users,tasks): демо-сиды учёток и задач входят в схему компании

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `seed_group_demo` — стенд группы одной командой

**Files:**
- Create: `backend/apps/companies/management/commands/seed_group_demo.py`
- Test: `backend/apps/companies/tests/test_seed_group_demo.py`

**Interfaces:**
- Consumes: `lifecycle.provision_company`, `membership_service.grant_membership`, `apps.access.interface.serving_holders`, `apps.hr.interface.list_employees_brief`, `htqweb.tenancy.db.use_company`, `call_command("seed_hr_demo"|"seed_employee_accounts"|"seed_tasks_demo", company=...)`.
- Produces: `manage.py seed_group_demo [--skip-tasks] [--password PW] [--force-remote]`; константа `GROUP` (slug, имя, kind, parent).

- [ ] **Step 1: Падающие тесты**

`backend/apps/companies/tests/test_seed_group_demo.py`:

```python
"""Стенд группы одной командой: порядок шагов и идемпотентность.

Настоящее заведение четырёх схем — ~4 минуты (по минуте на схему), поэтому
здесь оно подменяется строками реестра, а вызовы соседних сидов
записываются: проверяется ОРКЕСТРАЦИЯ (что, для кого, в каком порядке),
а не содержимое сидов — у тех свои тесты. Сквозной прогон — руками на
dev-базе (план блока D, задача 7).
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.companies.management.commands import seed_group_demo as cmd
from apps.companies.models import Company, CompanyMembership


@pytest.fixture
def fake_provisioning(monkeypatch):
    """provision_company → только строка реестра; call_command → журнал."""
    calls: list[tuple[str, dict]] = []

    def provision(*, slug, name, kind, parent_slug=None, country=""):
        parent = Company.objects.get(slug=parent_slug) if parent_slug else None
        return Company.objects.create(slug=slug, name=name, kind=kind, parent=parent)

    def record(name, *args, **kwargs):
        calls.append((name, kwargs))

    monkeypatch.setattr(cmd.lifecycle, "provision_company", provision)
    monkeypatch.setattr(cmd, "call_command", record)
    # Членства своим сотрудникам читают hr в схеме компании; схем здесь нет.
    monkeypatch.setattr(cmd, "_own_staff_user_ids", lambda slug: [])
    monkeypatch.setattr(cmd, "serving_holders", lambda slug: [])
    return calls


def _run(**kwargs):
    call_command("seed_group_demo", verbosity=0, **kwargs)


@pytest.mark.django_db
def test_creates_the_four_companies_of_the_document(fake_provisioning):
    _run()
    rows = {c.slug: c for c in Company.objects.select_related("parent")}
    assert set(rows) == {"hi-tech-group", "hi-tech-qazaqstan", "hi-tech-systems",
                         "kazakhstan-engineering-group"}
    assert rows["hi-tech-group"].kind == "holding" and rows["hi-tech-group"].parent is None
    for slug in ("hi-tech-qazaqstan", "hi-tech-systems", "kazakhstan-engineering-group"):
        assert rows[slug].parent_id == rows["hi-tech-group"].id
    assert rows["hi-tech-qazaqstan"].kind == "construction"
    assert rows["hi-tech-systems"].kind == "it"
    assert rows["kazakhstan-engineering-group"].kind == "service"


@pytest.mark.django_db
def test_seeds_every_company_in_order_and_tasks_for_htq_only(fake_provisioning):
    _run()
    names = [(name, kw.get("company")) for name, kw in fake_provisioning]
    slugs = [s for s, *_ in cmd.GROUP]
    expected = []
    for slug in slugs:
        expected += [("seed_hr_demo", slug), ("seed_employee_accounts", slug)]
    expected.append(("seed_tasks_demo", "hi-tech-qazaqstan"))
    assert names == expected


@pytest.mark.django_db
def test_skip_tasks(fake_provisioning):
    _run(skip_tasks=True)
    assert all(name != "seed_tasks_demo" for name, _ in fake_provisioning)


@pytest.mark.django_db
def test_existing_company_is_kept_and_gets_its_parent(fake_provisioning):
    """dev-база после tenancy_bootstrap: HTQ уже есть, без родителя."""
    Company.objects.create(slug="hi-tech-qazaqstan", name="Hi-Tech Qazaqstan",
                           kind="construction")
    _run()
    htq = Company.objects.select_related("parent").get(slug="hi-tech-qazaqstan")
    assert htq.parent.slug == "hi-tech-group"
    assert Company.objects.count() == 4


@pytest.mark.django_db
def test_archived_company_in_the_group_is_refused(fake_provisioning):
    Company.objects.create(slug="hi-tech-systems", name="X", kind="it", status="archived")
    with pytest.raises(CommandError, match="архив"):
        _run()


@pytest.mark.django_db
def test_grants_membership_to_own_staff_and_serving_holders(fake_provisioning, monkeypatch):
    monkeypatch.setattr(cmd, "_own_staff_user_ids",
                        lambda slug: {"hi-tech-group": [11, 12], "hi-tech-systems": [31]}.get(slug, []))
    monkeypatch.setattr(cmd, "serving_holders",
                        lambda slug: [11] if slug != "hi-tech-group" else [])
    _run(skip_tasks=True)
    by = {(m.company.slug, m.user_id) for m in CompanyMembership.objects.select_related("company")}
    assert ("hi-tech-group", 11) in by and ("hi-tech-group", 12) in by
    assert ("hi-tech-systems", 31) in by
    # Обслуживающий холдинга — член каждого ДО (блок C, решение 6).
    for slug in ("hi-tech-qazaqstan", "hi-tech-systems", "kazakhstan-engineering-group"):
        assert (slug, 11) in by


@pytest.mark.django_db
def test_is_idempotent(fake_provisioning):
    _run(skip_tasks=True)
    _run(skip_tasks=True)
    assert Company.objects.count() == 4


@pytest.mark.parametrize("host", ["10.0.0.5", "db.example.com", "203.0.113.10"])
def test_refuses_to_run_against_a_remote_database(host):
    with pytest.raises(CommandError, match="не похож на локальную"):
        cmd.Command()._assert_local(False, host=host)
```

Run: `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_seed_group_demo.py -q` → ERROR при импорте (модуля нет).

- [ ] **Step 2: Команда**

`backend/apps/companies/management/commands/seed_group_demo.py`:

```python
"""Локальный стенд группы: четыре компании документа 10.09.2026 одной командой.

Заводит компании (строка реестра + схема + миграции + сводки холдинга —
``lifecycle.provision_company``, идемпотентно), в каждой сеет утверждённую
оргструктуру (``seed_hr_demo --company``), заводит учётки
(``seed_employee_accounts --company``), выдаёт членства своим сотрудникам и
обслуживающим должностям холдинга (``serving_holders`` — блок C, членство
остаётся явным решением, здесь оно принимается за оператора стенда), и
наполняет задачи строительной компании (``seed_tasks_demo --company``).

Сиды соседних аппок вызываются через ``call_command`` — это композиция
CLI, как в shell-скрипте, а не обход правила «сосед только через
interface»: команда не импортирует ни моделей, ни сервисов hr/users/tasks,
а членства и реестр — её собственные сервисы.

ТОЛЬКО ДЛЯ ЛОКАЛЬНОЙ БАЗЫ (``_assert_local``): на бою в режиме перехода
одна компания, остальные заводятся отдельным шагом выкатки (roadmap §7).
Не атомарна как целое: заведение схем — DDL сотен таблиц вне транзакции;
каждый сид атомарен сам по себе.

Slug холдинга ``hi-tech-group`` — предварительный: какое юрлицо является
управляющей компанией, руководство не ответило (roadmap §8.1).
"""

from __future__ import annotations

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.access.interface import serving_holders
from apps.companies.models import Company, CompanyStatus
from apps.companies.services import lifecycle, membership_service
from apps.hr.interface import list_employees_brief
from htqweb.tenancy.db import use_company

# (slug, имя, вид, slug родителя). Порядок — родитель раньше детей.
GROUP = (
    ("hi-tech-group", "Hi-Tech Group LTD", "holding", None),
    ("hi-tech-qazaqstan", "Hi-Tech Qazaqstan", "construction", "hi-tech-group"),
    ("hi-tech-systems", "Hi-Tech Systems", "it", "hi-tech-group"),
    ("kazakhstan-engineering-group", "Kazakhstan Engineering Group", "service", "hi-tech-group"),
)
TASKS_COMPANY = "hi-tech-qazaqstan"


def _own_staff_user_ids(slug: str) -> list[int]:
    """user_id сотрудников компании — из её схемы, через interface hr."""
    with use_company(slug):
        return [e["user_id"] for e in list_employees_brief() if e["user_id"]]


class Command(BaseCommand):
    help = ("Локальный стенд группы: четыре компании, их оргструктуры, учётки, "
            "членства, задачи HTQ. Идемпотентно. Только для локальной БД.")

    def add_arguments(self, parser):
        parser.add_argument("--skip-tasks", action="store_true",
                            help="Не наполнять домен задач строительной компании.")
        parser.add_argument("--password", default=None,
                            help="Пароль демо-учёток (по умолчанию — как у seed_employee_accounts).")
        parser.add_argument("--force-remote", action="store_true",
                            help="Снять защиту от неместной БД. Не используйте.")

    def _assert_local(self, force: bool, host: str | None = None) -> None:
        """Тот же сторож, что у seed_hr_demo: команда заводит схемы и пишет
        в десятки таблиц — не то, что стоит отправить на боевой адрес из
        корневого .env по опечатке."""
        if host is None:
            host = str(settings.DATABASES["default"].get("HOST", ""))
        if host in {"localhost", "127.0.0.1", "db", "::1", ""} or force:
            self.stdout.write(f"  БД: {host or '(по умолчанию)'}")
            return
        raise CommandError(
            f"DB_HOST={host!r} не похож на локальную БД. Команда заводит компании "
            f"и наполняет их демо-данными — только для локальной среды. "
            f"Если это осознанно — --force-remote."
        )

    def handle(self, *args, **opts):
        self._assert_local(opts["force_remote"])
        for slug, name, kind, parent in GROUP:
            self._ensure_company(slug, name, kind, parent)

        account_opts = {"password": opts["password"]} if opts["password"] else {}
        for slug, *_ in GROUP:
            self.stdout.write(f"\n== {slug} ==")
            call_command("seed_hr_demo", company=slug, verbosity=opts["verbosity"])
            call_command("seed_employee_accounts", company=slug,
                         verbosity=opts["verbosity"], **account_opts)
            self._grant(slug, _own_staff_user_ids(slug), "своим сотрудникам")

        # Обслуживающие должности холдинга видны только после того, как
        # засеяны ВСЕ компании: serving_holders идёт вверх по дереву.
        for slug, *_ in GROUP:
            self._grant(slug, serving_holders(slug), "обслуживающим из вышестоящих")

        if not opts["skip_tasks"]:
            self.stdout.write(f"\n== задачи {TASKS_COMPANY} ==")
            call_command("seed_tasks_demo", company=TASKS_COMPANY, verbosity=opts["verbosity"])

        self.stdout.write(self.style.SUCCESS("\nСтенд группы готов."))

    def _ensure_company(self, slug: str, name: str, kind: str, parent: str | None) -> None:
        company = Company.objects.select_related("parent").filter(slug=slug).first()
        if company is None:
            try:
                lifecycle.provision_company(slug=slug, name=name, kind=kind, parent_slug=parent)
            except lifecycle.LifecycleError as exc:
                raise CommandError(exc.detail) from exc
            self.stdout.write(f"  {slug}: заведена")
            return
        if company.status != CompanyStatus.ACTIVE:
            raise CommandError(f"Компания {slug} в архиве — верните её: manage.py company_restore {slug}.")
        if parent and company.parent_id is None:
            # dev-база после tenancy_bootstrap: HTQ есть, родителя нет
            # (на бою его выставляет PATCH блока A — roadmap §7 шаг 5).
            company.parent = Company.objects.get(slug=parent)
            company.save(update_fields=["parent", "updated_at"])
            self.stdout.write(f"  {slug}: уже есть, родитель выставлен → {parent}")
            return
        if company.kind != kind:
            self.stdout.write(self.style.WARNING(
                f"  {slug}: уже есть с kind={company.kind!r} (в документе {kind!r}) — не меняю"))
            return
        self.stdout.write(f"  {slug}: уже есть")

    def _grant(self, slug: str, user_ids, label: str) -> None:
        if not user_ids:
            return
        company = Company.objects.get(slug=slug)
        granted = sum(1 for uid in user_ids if membership_service.grant_membership(company, uid))
        self.stdout.write(f"  членства {label}: новых {granted}, было {len(user_ids) - granted}")
```

Проверить имена: `lifecycle.LifecycleError.detail` (есть в `company_create`), `CompanyStatus` в `apps/companies/models.py`, `verbosity` приходит в `opts`.

- [ ] **Step 3: Тесты зелёные**

Run: `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_seed_group_demo.py apps/core/tests/test_app_isolation.py -q`
Expected: все passed.

- [ ] **Step 4: Коммит**

```bash
git add backend/apps/companies/management/commands/seed_group_demo.py backend/apps/companies/tests/test_seed_group_demo.py
git commit -m "feat(companies): seed_group_demo — стенд четырёх компаний группы одной командой

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Сквозная проверка на dev-базе, полные прогоны, документы

**Files:**
- Modify: `README.md` (раздел «Backend — management-команды»), `CLAUDE.md` (блок «Django management» и абзац про `seed_tasks_demo`), `docs/dev/infra-ops.md:165-180`, `docs/plans/2026-09-14-group-structure-roadmap.md` (§4 таблица: строки «Уровни N-1…N-4» и «Демо-данные»; §5.D «(выполнено)»; §7 шаг 2 — номера миграций `hr/0023`, `hr/0024`).

**Interfaces:** нет новых.

- [ ] **Step 1: Сквозной прогон на dev-базе (порт 55432, база `htqweb`)**

Это меняет состояние dev-базы пользователя: в реестре появятся четыре компании и четыре схемы. Пользователь на это согласился, заказав стенд (roadmap §5.D «чтобы стенд показывал именно их»); отдельного подтверждения не нужно, но факт — в итоговый отчёт.

Из `backend/`:

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 \
  DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 \
  ../.venv/Scripts/python.exe manage.py migrate hr        # 0023, 0024 в public: no-op по данным
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 \
  DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 \
  ../.venv/Scripts/python.exe manage.py seed_group_demo
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 \
  DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 \
  ../.venv/Scripts/python.exe manage.py tenancy_status
```

Expected: четыре компании; в каждой схеме `hr_levelthreshold` = 4 строки (N-1…N-4 — от миграции при заведении, сид их не менял); `hr_position` = 12/4/4/4; `public.hr_levelthreshold` по-прежнему 5 строк старого сида (миграция public не трогает). Повторный `seed_group_demo` — без ошибок и без новых строк. Проверка одной SQL (через Bash, не PowerShell):

```bash
docker exec htqweb-local-db-1 psql -U htqweb -d htqweb -At -c "
select n.nspname, (select count(*) from information_schema.tables t where t.table_schema=n.nspname and t.table_name='hr_position')
from pg_namespace n where n.nspname like 'co_%' order by 1;"
for s in co_hi_tech_group co_hi_tech_qazaqstan co_hi_tech_systems co_kazakhstan_engineering_group; do
  docker exec htqweb-local-db-1 psql -U htqweb -d htqweb -At -c "select '$s', (select count(*) from $s.hr_levelthreshold), (select count(*) from $s.hr_position), (select count(*) from $s.hr_employee);"
done
```

Expected: `4|12|12`, `4|4|4`, `4|4|4`, `4|4|4`.

- [ ] **Step 2: Метрика разрыва блока C — ноль**

```bash
docker exec htqweb-local-db-1 psql -U htqweb -d htqweb -At -c "select c.slug, count(m.id) from companies_company c left join companies_companymembership m on m.company_id=c.id group by 1 order by 1;"
```

Expected: холдинг 12; каждое ДО — свои 4 + 8 обслуживающих = 12. Если 8 не добавились — `serving_holders` вернул пусто: проверить, что `seed_hr_demo` холдинга выставил `serves_subsidiaries` и что учётки заведены ДО выдачи.

- [ ] **Step 3: Полный backend-сьют (форграунд, один)**

Run: `../.venv/Scripts/python.exe -m pytest -q` (≈45 мин)
Expected: падения — ровно 8 из `ci-known-failures.txt`. `test_seed_hr_demo`/`test_seed_tasks_demo`/`test_seed_employee_accounts`/`test_seed_group_demo`/`test_level_seed_migration`/`test_group_structures` — зелёные.

- [ ] **Step 4: Фронт**

Из `frontend/`: `npx vitest run` → базовые 8 падений в HR-диалогах и ни одного нового; `npx tsc --noEmit -p tsconfig.app.json 2>&1 | tail -1` → не больше 150.

- [ ] **Step 5: Документы**

`README.md`, блок команд — заменить строку `seed_hr_demo` и добавить:

```bash
../.venv/Scripts/python.exe manage.py seed_hr_demo [--company SLUG]   # оргструктура документа 10.09.2026 по виду компании; без флага — HTQ в текущий search_path
../.venv/Scripts/python.exe manage.py seed_employee_accounts [--company SLUG]
../.venv/Scripts/python.exe manage.py seed_tasks_demo [--company SLUG] [--purge|--wipe|--wipe-only]
../.venv/Scripts/python.exe manage.py seed_group_demo [--skip-tasks]   # стенд группы: 4 компании, структуры, учётки, членства, задачи HTQ
```

и абзац: «`seed_group_demo` — единственный способ увидеть группу локально: заводит `hi-tech-group` (холдинг) и три ДО с родителем, в каждой сеет утверждённую оргструктуру, заводит учётки (`demo12345`), выдаёт членства сотрудникам своей компании и обслуживающим должностям холдинга (блок C), наполняет задачи HTQ. Идемпотентна. Только локальная БД.»

`CLAUDE.md`, блок «Django management»: строка `seed_tasks_demo` → `seed_tasks_demo [--company SLUG] …`, добавить строки `seed_hr_demo [--company SLUG]` и `seed_group_demo [--skip-tasks]` с теми же комментариями; в абзац про `seed_tasks_demo` добавить одно предложение: «Пути отделов в нём — из утверждённой структуры HTQ (`apps/hr/management/group_structures.py`, один профильный отдел `stroy`).» В раздел «Мультикомпанейность» после абзаца об expand добавить:

«**Новая схема компании рождается с уровнями N-1…N-4** — `hr/0024_seed_level_thresholds` сеет `LevelThreshold` при `migrate_companies`, только в схеме компании (`search_path` начинается с `co_`) и только в пустую таблицу; в `public` (pytest, dev до `tenancy_bootstrap`, HTQ до переноса) миграция ничего не пишет. `UnitType.DIRECTORATE` — вид подразделения для трёх дирекций холдинга.»

`docs/dev/infra-ops.md:165-180` — те же строки команд и одна фраза про `--company`.

Roadmap: §4 строка «Уровни N-1…N-4» → «✅ `LevelThreshold` + сид `hr/0024` в новой схеме, `UnitType.DIRECTORATE`» / расхождение «—»; строка «Демо-данные» → «✅ `group_structures.py`, `seed_group_demo`» / расхождение «slug холдинга предварительный (§8.1); пустой блок HTQ не сеется (§8.3)». §5.D — заголовок «(выполнено)» и три строки «что сделано» по образцу §5.B/§5.C. §7 шаг 2 — «`hr/0023`–`0024` через `migrate_companies` на HTQ (оба no-op по данным: choices без DDL; пороги уже есть)».

- [ ] **Step 6: Коммит документов**

```bash
git add README.md CLAUDE.md docs/dev/infra-ops.md docs/plans/2026-09-14-group-structure-roadmap.md
git commit -m "docs: блок D закрыт — уровни, дирекции, стенд группы

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

**Покрытие спеки (roadmap §5.D):**
- «data-миграция hr: сид LevelThreshold N-1…N-4 если таблица пуста; через migrate_companies; на HTQ no-op» → задача 2 (плюс уточнение «только в схеме компании», без которого сломалась бы pytest-база).
- «UnitType.DIRECTORATE» → задача 1 (модель, миграция, подпись фронта).
- «seed_hr_demo → четыре оргструктуры (12+3+4+4), пунктирные связи как ReportingRelation.functional» → задачи 3–4. Число «3» у HTQ в roadmap — описка: на стр. 3 четыре именованные должности (директор, РП, начальник участка, инженер ОТ и ТБ), сеются четыре; исправить в roadmap при закрытии (задача 7).
- «проверить seed_tasks_demo» → задача 5 (пути отделов + тест-сторож + `--company`).
- §7 шаг 5 (заведение остальных компаний, `--parent hi-tech-group`, `company_grant` персоналу холдинга) — локально воспроизводит `seed_group_demo` (задача 6); боевой шаг остаётся ручным по §7.

**Заглушки:** все шаги содержат код; «перенести пять тестов дословно» в задаче 4 — ссылка на конкретный файл в `HEAD`, не TBD.

**Согласованность имён:** `gs.LEVELS`/`migration.LEVELS` (2↔3), `structure_for`/`UnknownStructure`/`level_for`/`email_for` (3↔4), `dest="company"` у трёх команд (4,5↔6), `companies.interface.schema_exists` (4↔5), `_own_staff_user_ids`/`serving_holders` как атрибуты модуля команды (6, для monkeypatch), `STRUCTURE_EFFECTIVE_FROM` только в 4.

**Известные ограничения (в итог):** роли должностям (`PositionRole`) сид не назначает — их выдают через UI; функциональные связи видны в матрице, не в дереве; `unit_type` через API отдела по-прежнему не задаётся (только сид/админка) — вне блока.
