# Блок B «Внешняя иерархия — снять заглушку» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Должность получает два поля — «руководящая» и «участвует ли во внешней иерархии», — и внешняя иерархия перестаёт быть заглушкой: `access.subordinate_companies` начинает возвращать реальное поддерево компаний, а экран оргструктуры показывает дерево владения вместо пустого списка слагов.

**Architecture:** Вся новая семантика — два поля на `hr.Position`. Шов с доменом доступа уже построен и ждёт их: `apps/access/services/hierarchy.py::_is_external_manager` читает `brief["is_manager"]` и `brief["external_hierarchy"]` из `apps.hr.interface.get_employee_brief` — после аддитивного расширения брифа он начинает работать **без единой правки в `apps.access`**. Дальше поля прокидываются наружу штатным путём домена HR (схема → сервис → вьюха) и правятся в карточке должности; экран внешней иерархии переходит с плоского списка слагов на дерево компаний из API блока A, с деградацией на прежний список, если у смотрящего нет прав на реестр.

**Tech Stack:** Django 5.2.7 / Python 3.13 (корневой `.venv`), Pydantic-схемы, pytest-django против Postgres `:55432`; React + Vite, TanStack Query, vitest + RTL, i18next с инлайн-фолбэками `t('key', 'текст')`.

**Spec:** [2026-09-14-group-structure-roadmap.md](2026-09-14-group-structure-roadmap.md) §5.B (и §3 — режим перехода, он действует и здесь). Правила заказчика по иерархии — [stage2-spec §1.4](2026-08-29-stage2-access-and-roles-spec.md#L117), а §1.6 прямо относит эти два поля к «переработке HR», то есть к настоящему блоку.

## Global Constraints

- Интерпретатор — **корневой** `.venv` (Python 3.13, Django 5.2.7); `backend/.venv` не существует, предупреждение в CLAUDE.md устарело. Из `backend/`: `../.venv/Scripts/python.exe -m pytest <path> -q`.
- **Один прогон pytest за раз, всегда в форграунде.** Параллельные сессии делят `test_htqweb` и пулы схем компаний — второй прогон даёт десятки ложных падений. Полный backend-сьют ~40 мин, `apps/hr` ~10 мин, `apps/access` ~2 мин.
- Межаппный доступ — только через `apps.<x>.interface`; межаппных FK нет.
- `hr` — **тенантная** аппка (`settings.TENANT_APPS`): её таблицы живут в `co_<slug>`, миграции по схемам компаний доводит `manage.py migrate_companies` отдельным шагом выкатки, а не старт контейнера. Любое изменение схемы — **expand/contract**; в этом блоке только expand.
- `Position` входит в `apps/hr/holding.py::HOLDING_MODELS`, поэтому сводные представления схемы `holding` пересобираются после миграции (это делает сам `migrate_companies`: сносит до прогона, собирает после).
- Модели тенантных аппок **не содержат поля компании** — изоляцию даёт `search_path`.
- API рукописный: `htqweb.http.api_view`, конверт ошибок `{"detail": ...}`, `APPEND_SLASH = False`.
- Режим перехода (roadmap §3): одна действующая компания; ничего не переносим, не переименовываем и не удаляем.
- **Зона:** `apps/contracts/**`, `apps/signoff/**` и их экраны не трогаются.
- **Ветки не создавать** — работа в выданной ветке (сейчас `sanzhar`). Не индексировать `.gitignore` и `AGENTS.md` — это чужие изменения рабочего дерева.
- Коммиты заканчиваются строкой `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Фронт: перед коммитом `npx tsc --noEmit -p tsconfig.json` и `npx vitest run <файлы>`. В репозитории ~331 существующая ошибка линта в нетронутых файлах и 8 падающих тестов в `src/components/hr/__tests__/{EmployeeFormDialog,CardT2SectionDialog}.test.tsx` — они были до блока A и к этой работе отношения не имеют; ваши файлы должны быть чистыми.

---

## Файловая структура

**Backend (изменить):**
- `apps/hr/models.py` — `ExternalHierarchy` (TextChoices) + два поля на `Position`.
- `apps/hr/migrations/0021_position_external_hierarchy.py` — expand, два `AddField` (генерируется).
- `apps/hr/interface.py` — два ключа в `get_employee_brief` (аддитивно).
- `apps/hr/services/position_service.py` — два ключа в `serialize`.
- `apps/hr/schemas.py` — два поля в `PositionCreate` и `PositionUpdate`.
- `CLAUDE.md` — строка о том, что после выкатки тенантного expand'а нужен `migrate_companies`.

**Backend (создать):**
- `apps/hr/tests/test_position_external_hierarchy.py` — модель, сериализация, API.
- `apps/access/tests/test_hierarchy_integration.py` — сквозная проверка через настоящую `Position`, без monkeypatch.

**Frontend (изменить):**
- `src/types/hr.ts` — два поля в `Position`.
- `src/pages/hr/HRPositions.tsx` — блок «Внешняя иерархия» в диалоге должности.
- `src/components/hr/OrgChart/ExternalHierarchy.tsx` — дерево вместо списка слагов.

**Frontend (создать):**
- `src/pages/hr/__tests__/HRPositionsExternalHierarchy.test.tsx`.
- `src/components/hr/OrgChart/ExternalHierarchy.test.tsx`.

**Документы (изменить):** `docs/plans/2026-09-14-group-structure-roadmap.md` (блок B закрыт), `docs/plans/2026-08-29-stage2-access-and-roles-spec.md` (§1.6 и §7 — поля появились), `STRUCTURE.md`.

---

## Решения, принятые до начала (не переоткрывать по ходу)

1. **Бэкфилла нет.** Ни одна существующая должность не помечается руководящей автоматически. Угадать «кто руководитель» по весу или по названию — ровно та эвристика, против которой написана вся модель доступа: ошибка тихо раздала бы видимость чужих компаний. После выкатки внешняя иерархия пуста у всех, пока кадровик не отметит должности руками, и экран обязан сказать это словами, а не показать пустоту.
2. **`external_hierarchy` по умолчанию `inherit`, `is_manager` по умолчанию `False`.** Участие включается одним флажком «руководящая», а `none` нужен для исключения: руководящая должность, которая НЕ командует нижестоящими компаниями (главный бухгалтер холдинга руководит своим отделом и никем в дочерних).
3. **Ограничения в БД на пару полей НЕ добавляем.** Соблазн запретить `external_hierarchy='inherit'` у неруководящей должности велик, но `inherit` — значение по умолчанию, и такой `CheckConstraint` сделал бы нелегальной каждую обычную должность. Разрешение прав и так требует ОБА условия (`apps/access/services/hierarchy.py:69`); в интерфейсе выбор просто заблокирован, пока не включена «руководящая».
4. **Внешняя иерархия остаётся только для чтения и только для отображения.** Она не режет выборки (spec §7) и не передаёт прав (§1.4): начальник из вышестоящей компании получает права ролями своей должности, а иерархия лишь расширяет множество компаний, в которых они действуют. Подпись об этом в интерфейсе обязательна — это самое вероятное расхождение ожиданий с заказчиком.
5. **Экран деградирует, а не падает.** `GET companies/v1/companies/tree` гейтован `module=companies, level=read`; у кадровика, смотрящего оргструктуру, таких прав может не быть. Тогда показываем прежний плоский список слагов из `/access/v1/me` (он доступен каждому вошедшему) и подписываем, что полное дерево требует доступа к реестру. Это не `fallback()` из `htqweb/fallback.py` и не подмена значения — это разный объём данных для разных прав.

---

### Task 1: Поля `is_manager` и `external_hierarchy` на должности

**Files:**
- Modify: `backend/apps/hr/models.py` (после `class UnitType`, и класс `Position`, строки 90–116)
- Create: `backend/apps/hr/migrations/0021_position_external_hierarchy.py` (через `makemigrations`)
- Create: `backend/apps/hr/tests/test_position_external_hierarchy.py`

**Interfaces:**
- Produces: `apps.hr.models.ExternalHierarchy` с членами `INHERIT = "inherit"`, `NONE = "none"`; `Position.is_manager: bool` (по умолчанию `False`), `Position.external_hierarchy: str` (по умолчанию `"inherit"`).

- [ ] **Step 1: Написать падающие тесты**

```python
# backend/apps/hr/tests/test_position_external_hierarchy.py
"""Два поля должности, которыми включается внешняя иерархия (roadmap §5.B).

Внешняя иерархия выводится из дерева владения компаниями и распространяется
только на руководящие должности — оговорка «относится к руководителям» часть
правила заказчика, а не уточнение: без неё рядовой сотрудник холдинга
оказался бы начальником директора дочерней компании.
"""

import datetime

import pytest
from django.core.exceptions import ValidationError

from apps.hr.models import Department, ExternalHierarchy, Position


@pytest.fixture
def department(db):
    return Department.objects.create(name="Руководство", path="upr")


@pytest.mark.django_db
def test_position_is_not_a_manager_by_default(department):
    """Бэкфилла нет: молча раздать видимость чужих компаний нельзя."""
    pos = Position.objects.create(title="Инженер", department=department, weight=100)
    pos.refresh_from_db()
    assert pos.is_manager is False


@pytest.mark.django_db
def test_external_hierarchy_defaults_to_inherit(department):
    """Участие включается одним флажком «руководящая», а не двумя действиями."""
    pos = Position.objects.create(title="Инженер", department=department, weight=100)
    pos.refresh_from_db()
    assert pos.external_hierarchy == ExternalHierarchy.INHERIT


@pytest.mark.django_db
def test_managerial_position_can_opt_out_of_the_external_hierarchy(department):
    pos = Position.objects.create(
        title="Главный бухгалтер", department=department, weight=110,
        is_manager=True, external_hierarchy=ExternalHierarchy.NONE,
    )
    pos.full_clean()
    pos.refresh_from_db()
    assert (pos.is_manager, pos.external_hierarchy) == (True, "none")


@pytest.mark.django_db
def test_unknown_external_hierarchy_value_is_rejected(department):
    pos = Position(title="Директор", department=department, weight=10,
                   external_hierarchy="maybe")
    with pytest.raises(ValidationError):
        pos.full_clean()


@pytest.mark.django_db
def test_ordinary_position_with_default_inherit_is_valid(department):
    """Пара «не руководитель + inherit» ЗАКОННА и ограничением БД не запрещена.

    inherit — значение по умолчанию, поэтому запрет сделал бы нелегальной
    каждую обычную должность. Оба условия проверяет разрешение прав
    (apps/access/services/hierarchy.py), а не схема.
    """
    pos = Position(title="Слесарь", department=department, weight=900)
    pos.full_clean()  # не должно поднять ValidationError
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_position_external_hierarchy.py -q`
Expected: FAIL — `ImportError: cannot import name 'ExternalHierarchy'`.

- [ ] **Step 3: Добавить перечисление и поля**

В `backend/apps/hr/models.py` после класса `UnitType` (строки 31–34) добавить:

```python
class ExternalHierarchy(models.TextChoices):
    """Участвует ли руководящая должность во ВНЕШНЕЙ иерархии.

    Внешняя иерархия не хранится и не редактируется — она выводится из дерева
    владения компаниями (``companies.Company.parent``): сотрудник вышестоящей
    компании является начальником сотрудников нижестоящих. Хранить её отдельной
    таблицей нельзя — два источника правды о подчинении разъедутся при первой
    же реорганизации, причём молча.

    Поле отвечает на единственный вопрос, который деревом не выводится:
    командует ли ЭТА руководящая должность нижестоящими компаниями. Главный
    бухгалтер холдинга руководит своим отделом и никем в дочерних — это
    выбирается, а не следует из факта руководства.
    """

    INHERIT = "inherit", "Участвует"
    NONE = "none", "Не участвует"
```

В классе `Position` после поля `is_system` (строка 105) добавить:

```python
    # Руководящая ли должность. Вместе с external_hierarchy включает внешнюю
    # иерархию (apps/access/services/hierarchy.py::_is_external_manager).
    # Умолчание False и НИКАКОГО бэкфилла: угадать руководителя по весу или
    # названию значило бы раздать видимость чужих компаний молча.
    is_manager = models.BooleanField(default=False, db_default=False, db_index=True)
    # Действует только у is_manager=True. Пара «не руководитель + inherit» —
    # законное состояние по умолчанию, поэтому ограничения в БД здесь нет:
    # оба условия проверяет разрешение прав, а не схема.
    external_hierarchy = models.CharField(
        max_length=16,
        choices=ExternalHierarchy.choices,
        default=ExternalHierarchy.INHERIT,
        db_default=ExternalHierarchy.INHERIT.value,
    )
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `cd backend && DJANGO_SETTINGS_MODULE=htqweb.settings.test ../.venv/Scripts/python.exe manage.py makemigrations hr -n position_external_hierarchy`
Expected: `0021_position_external_hierarchy.py` ровно с двумя `AddField` и ничем больше. Если автодетектор добавил что-то ещё — остановиться и доложить DONE_WITH_CONCERNS.

Дописать в начало сгенерированного файла модульный докстринг:

```python
"""Expand-шаг: два поля должности для внешней иерархии.

``hr`` — тенантная аппка, её таблицы живут в схемах компаний, поэтому эта
миграция НЕ применяется стартом контейнера (он зовёт ``migrate_shared``).
Схемы компаний доводит ``manage.py migrate_companies`` отдельным шагом
выкатки.

Шаг чисто аддитивный: два столбца с ``db_default``, существующие строки
получают значения без переписывания таблицы, старый код продолжает работать
не зная о них. Разрушающего парного шага у этого изменения нет и не
планируется.

``Position`` входит в ``HOLDING_MODELS``, поэтому сводные представления схемы
``holding`` обязаны быть пересобраны после прогона — это делает сам
``migrate_companies`` (сносит до, собирает после). Пока компании не
догонят друг друга, сводки холдинга не собираются: это известная цена
expand'а по тенантной аппке, см. docs/multi-company-tenancy-design.md §8.
"""
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_position_external_hierarchy.py -q`
Expected: 5 passed.

- [ ] **Step 6: Коммит**

```bash
git add backend/apps/hr/models.py backend/apps/hr/migrations/0021_position_external_hierarchy.py backend/apps/hr/tests/test_position_external_hierarchy.py
git commit -m "feat(hr): должность знает, руководящая ли она и командует ли нижестоящими компаниями

Два поля, которых ждал шов внешней иерархии в apps.access. Бэкфилла нет
намеренно: угадать руководителя по весу или названию значило бы раздать
видимость чужих компаний молча.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Поля наружу — бриф, сериализация, схемы; внешняя иерархия оживает

**Files:**
- Modify: `backend/apps/hr/interface.py:38-60` (`get_employee_brief`)
- Modify: `backend/apps/hr/services/position_service.py:165-181` (`serialize`)
- Modify: `backend/apps/hr/schemas.py` (`PositionCreate`, `PositionUpdate`)
- Create: `backend/apps/access/tests/test_hierarchy_integration.py`
- Modify: `backend/apps/hr/tests/test_position_external_hierarchy.py` (дописать API-тесты)

**Interfaces:**
- Consumes: `apps.hr.models.ExternalHierarchy`, `Position.is_manager` / `.external_hierarchy` (Task 1).
- Produces: `get_employee_brief` возвращает дополнительно `is_manager: bool` и `external_hierarchy: str`; `position_service.serialize` — те же два ключа; `PositionCreate`/`PositionUpdate` их принимают.

- [ ] **Step 1: Написать падающие тесты**

Дописать в конец `backend/apps/hr/tests/test_position_external_hierarchy.py`:

```python
# ── Шов наружу ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_employee_brief_carries_both_fields(department):
    """Единственный шов внешней иерархии с кадровым доменом.

    apps.access читает их отсюда и больше ниоткуда: модели HR он не
    импортирует ни одной строкой.
    """
    from apps.hr import interface as hr
    from apps.hr.models import Employee

    pos = Position.objects.create(title="Генеральный директор", department=department,
                                  weight=10, is_manager=True)
    Employee.objects.create(
        first_name="Ерлан", last_name="Абдрахманов", email="ceo@htq.test",
        department=department, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=4242,
    )

    brief = hr.get_employee_brief(4242)
    assert brief["is_manager"] is True
    assert brief["external_hierarchy"] == "inherit"
    # Аддитивность: ключи, которые читает действующий фронт, на месте.
    assert {"id", "full_name", "department_id", "position_id",
            "position_title", "status"} <= set(brief)


@pytest.mark.django_db
def test_serialize_exposes_both_fields(department):
    from apps.hr.services import position_service

    pos = Position.objects.create(title="Технический директор", department=department,
                                  weight=20, is_manager=True,
                                  external_hierarchy=ExternalHierarchy.NONE)
    row = position_service.serialize(pos)
    assert row["is_manager"] is True
    assert row["external_hierarchy"] == "none"


@pytest.mark.django_db
def test_patch_sets_the_fields(client, department, admin_headers):
    pos = Position.objects.create(title="Операционный директор", department=department,
                                  weight=30)
    res = client.patch(
        f"/api/hr/v1/positions/{pos.id}/",
        data='{"is_manager": true, "external_hierarchy": "none"}',
        content_type="application/json", **admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["is_manager"] is True
    assert res.json()["external_hierarchy"] == "none"
    pos.refresh_from_db()
    assert (pos.is_manager, pos.external_hierarchy) == (True, "none")


@pytest.mark.django_db
def test_patch_rejects_an_unknown_external_hierarchy_value(client, department, admin_headers):
    pos = Position.objects.create(title="Директор по строительству",
                                  department=department, weight=40)
    res = client.patch(
        f"/api/hr/v1/positions/{pos.id}/",
        data='{"external_hierarchy": "sometimes"}',
        content_type="application/json", **admin_headers,
    )
    assert res.status_code == 422
```

Фикстуры `client` и `admin_headers` взять по образцу существующих тестов домена — см. `backend/apps/hr/tests/conftest.py::auth_headers` и любой файл `apps/hr/tests/test_*_api.py`: прочитайте один из них и повторите тот же способ, а не изобретайте свой. Если админский заголовок там называется иначе — используйте его имя.

И новый файл:

```python
# backend/apps/access/tests/test_hierarchy_integration.py
"""Внешняя иерархия на НАСТОЯЩИХ полях должности, без подмены брифа.

test_hierarchy.py проверяет логику обхода дерева, подменяя ответ кадрового
интерфейса, — он писался до того, как поля существовали. Здесь тот же
сценарий проходит целиком: строка Position -> apps.hr.interface ->
apps.access. Оба файла нужны: первый ловит логику обхода, второй — то, что
шов реально сходится.
"""

import pytest

from apps.access.services import hierarchy


@pytest.fixture
def company_tree(db):
    from apps.companies.models import Company, CompanyKind

    holding = Company.objects.create(slug="htq-holding", name="Холдинг",
                                     kind=CompanyKind.HOLDING)
    Company.objects.create(slug="htq-kz", name="КЗ",
                           kind=CompanyKind.CONSTRUCTION, parent=holding)
    return holding


@pytest.mark.django_db
def test_managerial_position_opens_the_subtree(user, employee_with_position, company_tree):
    """Флажок «руководящая» на должности — и подчинённые компании появились."""
    employee_with_position.is_manager = True
    employee_with_position.save(update_fields=["is_manager"])

    assert hierarchy.subordinate_companies(user, "htq-holding") == ["htq-kz"]


@pytest.mark.django_db
def test_opting_out_closes_it_again(user, employee_with_position, company_tree):
    from apps.hr.models import ExternalHierarchy

    employee_with_position.is_manager = True
    employee_with_position.external_hierarchy = ExternalHierarchy.NONE
    employee_with_position.save(update_fields=["is_manager", "external_hierarchy"])

    assert hierarchy.subordinate_companies(user, "htq-holding") == []


@pytest.mark.django_db
def test_ordinary_position_stays_empty(user, employee_with_position, company_tree):
    """Состояние сразу после выкатки: бэкфилла нет, у всех пусто."""
    assert hierarchy.subordinate_companies(user, "htq-holding") == []
```

Фикстуры `user` и `employee_with_position` уже есть в `apps/access/tests/conftest.py` — `employee_with_position` возвращает объект `Position`.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_position_external_hierarchy.py apps/access/tests/test_hierarchy_integration.py -q`
Expected: FAIL — в брифе нет ключей, `serialize` их не отдаёт, PATCH их игнорирует, подчинённых компаний нет.

- [ ] **Step 3: Расширить бриф**

В `backend/apps/hr/interface.py::get_employee_brief` добавить два поля в `.values(...)` и два ключа в возвращаемый словарь:

```python
        .values("id", "first_name", "last_name", "department_id",
                "position_id", "position__title", "status",
                "position__is_manager", "position__external_hierarchy")
```

```python
        "position_title": row["position__title"],
        # Второй шов стадии 2 с кадровым доменом: внешнюю иерархию включают
        # два поля ДОЛЖНОСТИ, а читает их apps.access, который моделей HR не
        # импортирует (apps/access/services/hierarchy.py::_is_external_manager).
        # Ключи добавлены АДДИТИВНО — остальные читает действующий фронт.
        "is_manager": row["position__is_manager"],
        "external_hierarchy": row["position__external_hierarchy"],
        "status": row["status"],
```

- [ ] **Step 4: Расширить сериализацию и схемы**

В `backend/apps/hr/services/position_service.py::serialize` добавить после `"is_system"`:

```python
        "is_manager": pos.is_manager,
        "external_hierarchy": pos.external_hierarchy,
```

В `backend/apps/hr/schemas.py` добавить литерал рядом с прочими и по одному полю в обе схемы:

```python
ExternalHierarchyLiteral = Literal["inherit", "none"]
```

В `PositionCreate` — после `weight`:

```python
    is_manager: bool = False
    external_hierarchy: ExternalHierarchyLiteral = "inherit"
```

В `PositionUpdate` — после `weight`:

```python
    is_manager: bool | None = None
    external_hierarchy: ExternalHierarchyLiteral | None = None
```

⚠️ `update_position` делает `data.model_dump(exclude_none=True)` и затем `setattr` по каждому ключу — оба новых поля попадут в патч сами, дописывать сервис не требуется. Проверьте это тестом из шага 1, а не глазами. Если `Literal` в этом файле ещё не импортирован — добавьте его в существующий `from typing import ...`.

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_position_external_hierarchy.py apps/access -q`
Expected: passed, включая прежние `apps/access/tests/test_hierarchy.py` (они подменяют бриф и обязаны остаться зелёными).

- [ ] **Step 6: Прогнать домен целиком**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest apps/hr -q`
Expected: зелёный, кроме двух известных падений `test_employees_api.py::test_*_card_t2_*` из `backend/ci-known-failures.txt`.

- [ ] **Step 7: Коммит**

```bash
git add backend/apps/hr/interface.py backend/apps/hr/services/position_service.py backend/apps/hr/schemas.py backend/apps/hr/tests/test_position_external_hierarchy.py backend/apps/access/tests/test_hierarchy_integration.py
git commit -m "feat(hr): внешняя иерархия оживает — два поля должности доходят до apps.access

Шов был построен заранее и ждал полей: _is_external_manager читает их из
get_employee_brief, поэтому apps.access не правится ни строкой. Плюс
сквозной тест на настоящей должности вместо подменённого брифа.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Правка полей в карточке должности

**Files:**
- Modify: `frontend/src/types/hr.ts:12-27` (`Position`)
- Modify: `frontend/src/pages/hr/HRPositions.tsx` (локальный тип `Position` в начале файла, состояние `form`, сброс формы, отправка, разметка диалога)
- Create: `frontend/src/pages/hr/__tests__/HRPositionsExternalHierarchy.test.tsx`

**Interfaces:**
- Consumes: `is_manager`, `external_hierarchy` в ответе `hr/v1/positions` (Task 2).
- Produces: PATCH должности отправляет оба поля.

- [ ] **Step 1: Написать падающий тест**

```tsx
// frontend/src/pages/hr/__tests__/HRPositionsExternalHierarchy.test.tsx
/**
 * Внешняя иерархия в карточке должности.
 *
 * Проверяется то, что отличает этот блок формы от остальных полей: участие во
 * внешней иерархии выбирается только у руководящей должности, и рядом стоит
 * подпись о том, что связь означает подчинение, а не передачу прав.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import HRPositions from '../HRPositions';

const updatePosition = vi.fn();

vi.mock('@/api/hr', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/hr')>();
  return {
    ...actual,
    getPositions: vi.fn(async () => ({
      items: [{
        id: 1, title: 'Генеральный директор', department: 1, department_id: 1,
        department_name: 'Руководство', weight: 10, level: 1, grade: 10,
        is_active: true, is_system: false, is_manager: false,
        external_hierarchy: 'inherit',
      }],
      total: 1, page: 1, limit: 200,
    })),
    getDepartments: vi.fn(async () => ([{ id: 1, name: 'Руководство', path: 'upr' }])),
    getLevelThresholds: vi.fn(async () => ([])),
    updatePosition: (id: number, data: unknown) => updatePosition(id, data),
  };
});

vi.mock('@/components/Header', () => ({ Header: () => null }));
vi.mock('@/components/Footer', () => ({ Footer: () => null }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

describe('HRPositions — внешняя иерархия', () => {
  beforeEach(() => updatePosition.mockReset());

  it('участие нельзя выбрать, пока должность не руководящая', async () => {
    renderWithProviders(<HRPositions />);
    await userEvent.click(await screen.findByRole('button', { name: /Генеральный директор/ }));

    expect(await screen.findByRole('switch', { name: /Руководящая должность/ })).not.toBeChecked();
    expect(screen.getByRole('combobox', { name: /Внешняя иерархия/ })).toBeDisabled();
  });

  it('подпись объясняет, что это подчинение, а не передача прав', async () => {
    renderWithProviders(<HRPositions />);
    await userEvent.click(await screen.findByRole('button', { name: /Генеральный директор/ }));

    expect(await screen.findByText(/подчинение, а не передач/i)).toBeInTheDocument();
  });

  it('оба поля уходят в PATCH', async () => {
    updatePosition.mockResolvedValue({});
    renderWithProviders(<HRPositions />);
    await userEvent.click(await screen.findByRole('button', { name: /Генеральный директор/ }));
    await userEvent.click(await screen.findByRole('switch', { name: /Руководящая должность/ }));
    await userEvent.click(screen.getByRole('button', { name: /Сохранить/ }));

    await waitFor(() => expect(updatePosition).toHaveBeenCalled());
    expect(updatePosition.mock.calls[0][1]).toMatchObject({
      is_manager: true, external_hierarchy: 'inherit',
    });
  });
});
```

⚠️ Мок `@/api/hr` перечисляет функции, которые страница действительно зовёт. Откройте `HRPositions.tsx` и сверьте имена ДО запуска: если страница берёт данные другой функцией (или через общий объект), поправьте мок под неё, а не наоборот. Кнопка открытия карточки и надпись на кнопке сохранения — тоже по факту разметки; подберите запросы по тому, что рендерится, сохранив смысл проверок.

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && npx vitest run src/pages/hr/__tests__/HRPositionsExternalHierarchy.test.tsx`
Expected: FAIL — переключателя и селекта в форме нет.

- [ ] **Step 3: Расширить типы**

В `frontend/src/types/hr.ts`, в `interface Position` после `is_system`:

```ts
  /** Руководящая ли должность — включает участие во внешней иерархии. */
  is_manager?: boolean;
  /** Действует только у руководящей: командует ли нижестоящими компаниями. */
  external_hierarchy?: 'inherit' | 'none';
```

Тот же файл `HRPositions.tsx` объявляет собственный локальный тип позиции (около строки 35) — добавить туда те же два поля.

- [ ] **Step 4: Добавить поля в форму**

В `HRPositions.tsx`:

1. В тип состояния `form` и в оба места, где форма сбрасывается/инициализируется (строка ~137 и ~222, плюс место, где форма заполняется из `editingPos`), добавить `is_manager: boolean;` и `external_hierarchy: 'inherit' | 'none';` со значениями `false` / `'inherit'` по умолчанию и из должности при редактировании.
2. В формируемый `payload` добавить `is_manager: form.is_manager` и `external_hierarchy: form.external_hierarchy`.
3. В разметку диалога, рядом с блоком `hr.positions.hrAccessLevel` (строка ~587), добавить блок:

```tsx
                    <div className="grid gap-2 rounded-lg border bg-muted/30 p-3">
                      <div className="text-sm font-semibold">
                        {t('hr.positions.externalHierarchy', 'Внешняя иерархия')}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {t(
                          'hr.positions.externalHierarchyHint',
                          'Сотрудник вышестоящей компании является начальником сотрудников '
                          + 'нижестоящих. Связь означает подчинение, а не передачу прав: права '
                          + 'приходят ролями должности, иерархия лишь расширяет круг компаний, '
                          + 'в которых они действуют.',
                        )}
                      </p>
                      <label className="flex items-center justify-between gap-3 text-sm">
                        {t('hr.positions.isManager', 'Руководящая должность')}
                        <Switch
                          aria-label={t('hr.positions.isManager', 'Руководящая должность')}
                          checked={form.is_manager}
                          onCheckedChange={(next) => setForm({ ...form, is_manager: next })}
                        />
                      </label>
                      <label className="grid gap-1 text-sm">
                        {t('hr.positions.externalParticipation', 'Участие во внешней иерархии')}
                        <select
                          aria-label={t('hr.positions.externalParticipation', 'Участие во внешней иерархии')}
                          className="rounded-md border bg-background px-3 py-2 text-sm disabled:opacity-50"
                          disabled={!form.is_manager}
                          value={form.external_hierarchy}
                          onChange={(e) => setForm({
                            ...form,
                            external_hierarchy: e.target.value as 'inherit' | 'none',
                          })}
                        >
                          <option value="inherit">
                            {t('hr.positions.externalInherit', 'Командует нижестоящими компаниями')}
                          </option>
                          <option value="none">
                            {t('hr.positions.externalNone', 'Только своя компания')}
                          </option>
                        </select>
                        {!form.is_manager && (
                          <span className="text-xs text-muted-foreground">
                            {t(
                              'hr.positions.externalNeedsManager',
                              'Выбор доступен только у руководящей должности.',
                            )}
                          </span>
                        )}
                      </label>
                    </div>
```

Нативный `<select>` — сознательно: два варианта и `aria-label`, который ищет тест. Импорт `Switch` из `@/components/ui/switch` добавить, если его в файле ещё нет.

- [ ] **Step 5: Проверки**

Run: `cd frontend && npx vitest run src/pages/hr && npx tsc --noEmit -p tsconfig.json && npm run lint`
Expected: новые тесты зелёные, прежние тесты `HRPositions` не сломаны, tsc чисто, линт чист по вашим файлам.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/types/hr.ts frontend/src/pages/hr/HRPositions.tsx frontend/src/pages/hr/__tests__/HRPositionsExternalHierarchy.test.tsx
git commit -m "feat(hr): руководящая должность и участие во внешней иерархии правятся в карточке

Участие выбирается только у руководящей должности; рядом подпись о том, что
связь означает подчинение, а не передачу прав — это самое вероятное
расхождение ожиданий с заказчиком, и закрывать его надо в интерфейсе.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Внешняя иерархия — дерево компаний вместо списка слагов

**Files:**
- Modify: `frontend/src/components/hr/OrgChart/ExternalHierarchy.tsx` (полностью переписывается)
- Create: `frontend/src/components/hr/OrgChart/ExternalHierarchy.test.tsx`

**Interfaces:**
- Consumes: `companiesApi.tree()` и типы `CompanyTreeNode` (блок A), `usePermissions()` → `{ company, subordinateCompanies, isLoading }`.

- [ ] **Step 1: Написать падающий тест**

```tsx
// frontend/src/components/hr/OrgChart/ExternalHierarchy.test.tsx
/**
 * Внешняя иерархия: дерево владения компаниями, только для чтения.
 *
 * Три предмета проверки — ровно то, что отличает этот экран: дерево рисуется
 * из реестра, пустой результат ОБЪЯСНЯЕТСЯ (иначе читается как сбой загрузки),
 * и при отсутствии прав на реестр экран деградирует до списка слагов, а не
 * показывает ошибку.
 */
import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { ExternalHierarchy } from './ExternalHierarchy';

const tree = vi.fn();
vi.mock('@/api/companies', () => ({ companiesApi: { tree: () => tree() } }));

const permissions = vi.fn();
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

const TREE = [{
  slug: 'hi-tech-group', name: 'Hi-Tech Group', kind: 'holding', status: 'active', country: '',
  children: [
    { slug: 'hi-tech-qazaqstan', name: 'Hi-Tech Qazaqstan', kind: 'construction', status: 'active', country: 'KZ', children: [] },
    { slug: 'hi-tech-systems', name: 'Hi-Tech Systems', kind: 'it', status: 'active', country: 'KZ', children: [] },
  ],
}];

describe('ExternalHierarchy', () => {
  beforeEach(() => {
    tree.mockReset();
    permissions.mockReturnValue({
      company: 'hi-tech-group', subordinateCompanies: ['hi-tech-qazaqstan', 'hi-tech-systems'],
      isLoading: false,
    });
  });

  it('рисует дерево владения и отмечает подчинённые компании', async () => {
    tree.mockResolvedValue({ data: TREE });
    renderWithProviders(<ExternalHierarchy />);

    expect(await screen.findByText('Hi-Tech Group')).toBeInTheDocument();
    expect(screen.getByText('Hi-Tech Qazaqstan')).toBeInTheDocument();
    expect(screen.getAllByText(/подчин/i).length).toBeGreaterThan(0);
  });

  it('объясняет пустой результат, а не показывает пустоту', async () => {
    tree.mockResolvedValue({ data: TREE });
    permissions.mockReturnValue({
      company: 'hi-tech-group', subordinateCompanies: [], isLoading: false,
    });
    renderWithProviders(<ExternalHierarchy />);

    expect(await screen.findByText(/не помечена руководящей/i)).toBeInTheDocument();
  });

  it('без прав на реестр деградирует до списка слагов, а не до ошибки', async () => {
    tree.mockRejectedValue({ response: { status: 403 } });
    renderWithProviders(<ExternalHierarchy />);

    expect(await screen.findByText('hi-tech-qazaqstan')).toBeInTheDocument();
    expect(screen.queryByText(/ошибк/i)).toBeNull();
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && npx vitest run src/components/hr/OrgChart/ExternalHierarchy.test.tsx`
Expected: FAIL — компонент не ходит в реестр и дерева не рисует.

- [ ] **Step 3: Переписать компонент**

```tsx
// frontend/src/components/hr/OrgChart/ExternalHierarchy.tsx
import { useQuery } from '@tanstack/react-query';
import { Building2, CornerDownRight, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { companiesApi } from '@/api/companies';
import { Badge } from '@/components/ui/badge';
import { usePermissions } from '@/hooks/usePermissions';
import type { CompanyTreeNode } from '@/types/companies';

/**
 * Внешняя иерархия — дерево владения компаниями (§1.4 спеки стадии 2).
 *
 * Только чтение: редактировать здесь нечего, дерево вычисляется из реестра
 * компаний, а участие должности в нём задаётся в её карточке.
 *
 * **Пустой список — нормальное состояние, а не сбой загрузки**, и экран обязан
 * различать два разных «пусто»: под компанией вообще нет нижестоящих, и
 * нижестоящие есть, но должность смотрящего не помечена руководящей. Пустая
 * область без объяснения читается как «не загрузилось», и разбираться пойдут
 * не туда.
 *
 * **Деградация вместо ошибки.** Реестр компаний закрыт правом `companies:read`,
 * которого у кадровика может не быть. Тогда показываем то, что доступно
 * каждому вошедшему, — список слагов из `/access/v1/me`, — и подписываем, что
 * полное дерево требует доступа к реестру. Это не подмена значения
 * (`htqweb/fallback.py` тут ни при чём), а разный объём данных для разных прав.
 */

function TreeBranch({ node, depth, current, subordinate }: {
  node: CompanyTreeNode; depth: number; current: string | null; subordinate: Set<string>;
}) {
  const { t } = useTranslation();
  const isCurrent = node.slug === current;
  const isSubordinate = subordinate.has(node.slug);

  return (
    <li>
      <div
        className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-sm ${isCurrent ? 'bg-accent font-medium' : ''}`}
        style={{ paddingLeft: `${0.5 + depth * 1.25}rem` }}
      >
        {depth > 0
          ? <CornerDownRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          : <Building2 className="h-4 w-4 shrink-0 text-primary" />}
        <span>{node.name}</span>
        {isCurrent && (
          <Badge variant="outline">{t('access.hierarchy.youAreHere', 'ваша компания')}</Badge>
        )}
        {isSubordinate && (
          <Badge variant="secondary">{t('access.hierarchy.subordinate', 'подчинённая')}</Badge>
        )}
      </div>
      {node.children.length > 0 && (
        <ul>
          {node.children.map((child) => (
            <TreeBranch key={child.slug} node={child} depth={depth + 1}
              current={current} subordinate={subordinate} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function ExternalHierarchy() {
  const { t } = useTranslation();
  const { company, subordinateCompanies, isLoading } = usePermissions();
  const treeQuery = useQuery({
    queryKey: ['companies', 'tree'],
    queryFn: async () => (await companiesApi.tree()).data,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  const subordinate = new Set(subordinateCompanies);
  const registryAvailable = treeQuery.isSuccess && (treeQuery.data ?? []).length > 0;

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t('common.loading', 'Загрузка…')}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto rounded-xl border bg-card p-6">
      <div className="mb-4 flex items-start gap-2 rounded-lg border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          {t(
            'access.hierarchy.externalHint',
            'Дерево выводится из иерархии компаний и не редактируется: сотрудник '
            + 'вышестоящей компании является начальником сотрудников нижестоящих. '
            + 'Связь означает подчинение, а не передачу прав. Правило действует для '
            + 'руководящих должностей, у которых включено участие во внешней иерархии.',
          )}
        </p>
      </div>

      {registryAvailable ? (
        <ul className="space-y-0.5">
          {(treeQuery.data ?? []).map((node) => (
            <TreeBranch key={node.slug} node={node} depth={0}
              current={company} subordinate={subordinate} />
          ))}
        </ul>
      ) : (
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            <Building2 className="h-4 w-4 text-primary" />
            {company ?? t('access.hierarchy.noCompany', 'компания не определена')}
          </div>
          {subordinateCompanies.length > 0 && (
            <ul className="mt-3 space-y-2 border-l pl-4">
              {subordinateCompanies.map((slug) => (
                <li key={slug} className="flex items-center gap-2 text-sm">
                  <CornerDownRight className="h-4 w-4 text-muted-foreground" />
                  <span className="font-mono">{slug}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 max-w-prose text-xs text-muted-foreground">
            {t(
              'access.hierarchy.registryClosed',
              'Полное дерево компаний показывается при доступе к реестру компаний; '
              + 'здесь перечислено то, что видно по вашим правам.',
            )}
          </p>
        </div>
      )}

      {subordinateCompanies.length === 0 && (
        <p className="mt-4 max-w-prose text-sm text-muted-foreground">
          {t(
            'access.hierarchy.externalEmpty',
            'Подчинённых компаний нет: ваша должность не помечена руководящей с '
            + 'участием во внешней иерархии. Это не ошибка загрузки — отметка ставится '
            + 'в карточке должности.',
          )}
        </p>
      )}
    </div>
  );
}

export default ExternalHierarchy;
```

- [ ] **Step 4: Проверки**

Run: `cd frontend && npx vitest run src/components/hr/OrgChart && npx tsc --noEmit -p tsconfig.json && npm run lint`
Expected: новые тесты зелёные, соседние тесты `OrgChart` (в т.ч. `HierarchySwitch.test.tsx`) не сломаны.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/components/hr/OrgChart/ExternalHierarchy.tsx frontend/src/components/hr/OrgChart/ExternalHierarchy.test.tsx
git commit -m "feat(hr): внешняя иерархия показывает дерево компаний, а не список слагов

Экран различает два разных «пусто» — под компанией никого нет и должность не
помечена руководящей, — и деградирует до прежнего списка, если у смотрящего
нет прав на реестр компаний.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Проверка целиком и документы

**Files:**
- Modify: `docs/plans/2026-09-14-group-structure-roadmap.md` (§5.B и §7), `docs/plans/2026-08-29-stage2-access-and-roles-spec.md` (§1.6, §7), `STRUCTURE.md`, `CLAUDE.md`

- [ ] **Step 1: Полный backend-сьют**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
(форграунд, таймаут 3600000 мс; ~40 мин)
Expected: падений ровно восемь — список `backend/ci-known-failures.txt`. Любое девятое разобрать: своё оно или чужое (`git log --oneline <база блока>..HEAD --name-only` по файлу теста).

- [ ] **Step 2: Полный фронт**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json && npm run lint && npm test`
Expected: tsc чисто; падений ровно восемь, все в `src/components/hr/__tests__/{EmployeeFormDialog,CardT2SectionDialog}.test.tsx` (существовали до блока A).

- [ ] **Step 3: Документы**

`docs/plans/2026-09-14-group-structure-roadmap.md`:
- в §5.B заменить описание на отметку о выполнении со ссылкой на настоящий план;
- в таблице §4 строку «Внешняя иерархия (правило 4) | заглушка | …» привести к фактическому состоянию (поля есть, отметка ставится вручную, бэкфилла нет).

`docs/plans/2026-08-29-stage2-access-and-roles-spec.md`:
- §1.6 — снять `is_manager`/`external_hierarchy` из списка «что остаётся за переработкой HR», оставив там перевод уровней и `hr-level`;
- §1.6 — снять фразу «До появления полей §1.4 `subordinate_companies` отдаётся пустым списком»: список теперь непустой у отмеченных руководителей;
- §7 — оставить пункт «фильтрация данных по внешней иерархии» как невыполненный (блок B её не делает), но отметить, что само множество теперь вычисляется по реальным данным.

`STRUCTURE.md` — в описании домена HR упомянуть два новых поля должности одной строкой в стиле соседних записей.

`CLAUDE.md`, раздел про мультикомпанейность — дописать после абзаца о `migrate_companies`:

```markdown
⚠️ **Expand по тенантной аппке требует `migrate_companies` отдельным шагом выкатки.** Старт контейнера зовёт `migrate_shared` и схем компаний не трогает, поэтому новый столбец появится в `public`-части и не появится в `co_<slug>` — код, который его читает, упадёт у всех компаний. Образец такого шага — `hr/0021_position_external_hierarchy`.
```

- [ ] **Step 4: Коммит**

```bash
git add docs/plans/2026-09-14-group-structure-roadmap.md docs/plans/2026-08-29-stage2-access-and-roles-spec.md STRUCTURE.md CLAUDE.md
git commit -m "docs: блок B закрыт — внешняя иерархия работает на реальных полях

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Рантбук выкатки блока B

1. До выкатки: `manage.py tenancy_status --json > before.json` на боевом `backend-web`.
2. Выкатка образов. `migrate_shared` **не применит** `hr/0021` — это тенантная аппка.
3. **`manage.py migrate_companies`** без фильтров — доводит схемы всех действующих компаний и пересобирает сводки холдинга. Пока прогон идёт, дашборд холдинга отдаёт `relation does not exist`; это цена expand'а по тенантной аппке, названная в `docs/multi-company-tenancy-design.md` §8.
4. После: `manage.py tenancy_status --json > after.json`; `diff before.json after.json` — состав таблиц и компаний не меняется.
5. Проверить в интерфейсе: в карточке должности появился блок «Внешняя иерархия»; отметить одну руководящую должность холдинга и убедиться, что на экране оргструктуры её сотрудник видит подчинённые компании.
6. Отметку «руководящая» ставит кадровик по утверждённой оргструктуре — автоматически никто её не проставит и не должен.

## Что блок B не делает

- **Не режет выборки по внешней иерархии** — `subordinate_companies` вычисляется и отдаётся, но данные поперёк компаний по нему не фильтруются (spec §7). Это отдельный шаг масштаба объектной области.
- Не переводит `junior/middle/senior/lead` в роли и не удаляет `hr-level` — это блок I дорожной карты.
- Не показывает сотрудников чужих компаний: подресурсы компании закрыты собственной компанией либо платформенным администратором (блок A), и показывать чужой штат этот экран не должен.
- Не трогает внутреннюю иерархию должностей — она редактируется прежней диаграммой.

## Self-review (выполнен)

- **Покрытие roadmap §5.B:** поля + expand-миграция — Task 1; `get_employee_brief` аддитивно и оживший `apps.access` — Task 2; правка в карточке должности — Task 3; дерево вместо списка слагов в `ExternalHierarchy.tsx` — Task 4; документы и сквозная проверка — Task 5.
- **Плейсхолдеры:** нет; в двух местах (фикстуры HR-тестов в Task 2, имена функций API в моке Task 3) вместо кода стоит явное указание сверить с существующим файлом — это не «разберитесь сами», а защита от расхождения с фактическими именами, и оба места названы точно.
- **Согласованность имён:** `ExternalHierarchy` (Task 1) → импортируется в Task 2; ключи `is_manager` / `external_hierarchy` одинаковы в модели, брифе, `serialize`, схемах, типах фронта и форме; `CompanyTreeNode` и `companiesApi.tree` — из блока A, уже существуют; `usePermissions()` отдаёт `company`, `subordinateCompanies`, `isLoading` (проверено по `frontend/src/hooks/usePermissions.ts`).
