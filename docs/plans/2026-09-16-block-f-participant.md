# Блок F «ОСУ / Участник» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Общее собрание участников (ОСУ) — орган, который в матрице полномочий HR-FRM-004 УТВЕРЖДАЕТ назначение директора ДО, бюджет группы и крупные сделки, — получает в платформе представление, на которое маршрут согласования может сослаться обычным `position_id`: системная должность «Участник (ОСУ)» над генеральным директором холдинга, заводимая одной командой и отдаваемая соседнему домену одной функцией.

**Architecture:** Никакой новой модели и никакой миграции. ОСУ — строка `hr.Position` с `is_system=True` (переименовать, перевести в другой отдел или деактивировать через UI нельзя, удалить — тоже), весом `0` (вершина шкалы) и прямой связью «ГД подчинён ОСУ» в дереве подчинения. Заводит её `apps/hr/services/participant_service.ensure_participant()` — идемпотентно; на бою её зовёт команда `manage.py hr_participant --company <slug>`, на стенде — `seed_hr_demo` для холдинга. Наружу — `hr.interface.participant_position()`: сосед не хардкодит название, а спрашивает.

**Tech Stack:** Django 5.2.7 / Python 3.13 (корневой `.venv`), pytest-django против Postgres `:55432`. Фронт не трогается: дерево оргструктуры уже рисует должность над ГД по связи подчинения (dagre раскладывает по рёбрам, не по уровню).

**Spec:** [2026-09-14-group-structure-roadmap.md](2026-09-14-group-structure-roadmap.md) §5.F (одна строка: «должность уровня N-0 в холдинге, `is_system`; маршруты signoff ссылаются на неё обычным `position_id`»), §6.1–6.2 (что ждёт signoff), §1 («Над ГД группы — Общее собрание участников»). Документы руководства: оргструктура стр. 1 (ОСУ нарисовано над ГД как орган, без «1 шт. ед.»); HR-FRM-004 — колонка «Участник / ОСУ» перерисована ниже.

## Global Constraints

- Интерпретатор — **корневой** `.venv`. Из `backend/`: `../.venv/Scripts/python.exe -m pytest <path> -q`.
- **Один прогон pytest за раз, всегда в форграунде, никогда в фоне и не через монитор.** Полный сьют ~45 мин, `apps/hr` ~10 мин.
- Межаппный доступ — только через `apps.<x>.interface` (сторож `apps/core/tests/test_app_isolation.py`); межаппных FK нет.
- `hr` — **тенантная** аппка. В этом блоке миграций НЕТ: если `makemigrations hr --check` показывает изменения — кто-то тронул модель, это ошибка.
- Режим перехода (roadmap §3): на бою одна действующая компания, холдинга ещё нет. Команда `hr_participant` пишет только туда, куда её явно направили (`--company` обязателен, без умолчания на текущий `search_path`).
- **Зона:** `apps/contracts/**`, `apps/signoff/**` не трогаются. Блок F только предоставляет должность и функцию; маршруты строит другой разработчик.
- **Ветки не создавать** — работа в выданной ветке (`sanzhar`).
- Трейлер коммитов: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Известные падения бэкенда — ровно `backend/ci-known-failures.txt` (8 штук).
- **Сторожа, о которых обязан знать исполнитель:** `test_positions_api.py` пинит точный набор ключей `PositionOut` — сериализация должности не меняется; `test_group_structures.py` пинит данные оргструктуры литералами документа — правки данных сопровождаются правкой литералов с комментарием, почему; `htqweb/date_rules.py` и `uxContract.test.ts` в этом блоке не задеваются (дат и фронта нет).
- `manage.py` без блока переменных окружения из CLAUDE.md («Reaching the dev database from the host») висит 120 с на недоступном `db` — строку не сокращать.

---

## Данные документа

**Оргструктура, стр. 1:** «ОБЩЕЕ СОБРАНИЕ УЧАСТНИКОВ» → «ГЕНЕРАЛЬНЫЙ ДИРЕКТОР (CEO ГРУППЫ), единоличный исполнительный орган» → три дирекции. ОСУ нарисовано НАД генеральным директором, без штатной единицы: это орган владельцев, а не должность в штате.

**HR-FRM-004, колонка «Участник / ОСУ»** (И — инициирует, С — согласовывает, У — утверждает):

| № | Решение | Участник/ОСУ | ГД УК | CFO | Примечание |
|---|---|---|---|---|---|
| 7 | Назначение и смена директора дочернего общества | **У** | И | | Решение участника; оформляет ГДХ |
| 11 | Утверждение бюджета группы | **У** | С | И | |
| 14 | Крупные сделки, займы, кредиты, гарантии, залоги | **У** | С | И | Независимо от суммы — участник |
| 15 | Списание активов и дебиторской задолженности | | У | С | Свыше порога — участник |

В остальных одиннадцати строках у ОСУ пусто. Значит для маршрутов signoff ОСУ — утверждающий на четырёх решениях, и это ровно то, ради чего ему нужна адресуемая должность.

## Решения, принятые при планировании (для проверки заказчиком)

1. **«Уровень N-0» реализуется положением в дереве, а не порогом уровней.** Roadmap говорит «должность уровня N-0», но уровень 0 в платформе невозможен без переделки: `LevelThreshold` держит ограничение БД `level_number >= 1`, пять схем API — `ge=1`, а сид порогов N-1…N-4 (`hr/0024`) уже накатан на схемы, и «вырезать» N-0 из диапазона N-1 пришлось бы data-миграцией по всем компаниям, включая боевую HTQ с порогами от ETL. Всё это — ради подписи-бейджа. Дерево оргструктуры раскладывается по СВЯЗЯМ ПОДЧИНЕНИЯ (dagre), а не по номеру уровня, поэтому ОСУ с весом `0` и связью «ГД → ОСУ» встанет НАД генеральным директором и без своего порога. *Цена решения:* бейдж уровня на карточке ОСУ покажет тот же ярус, что у ГД (N-1). Если заказчик захочет отдельный ярус — это отдельная работа с порогами, и она названа в §«Что осталось».
2. **ОСУ — должность, у которой есть держатели.** Участник(и) заводятся как сотрудники холдинга на этой должности — иначе `resolve_position_users` не найдёт, кому адресовать задачу согласования. Это не искажение: участник ТОО, принимающий решения по HR-FRM-004, — реальный человек с учёткой.
3. **ОСУ — руководящая должность с внешней иерархией** (`is_manager=True`, `external_hierarchy=inherit`): владелец группы видит все дочерние компании (блок B). При этом **не** `serves_subsidiaries`: участник не обслуживает ДО, он ими владеет; права в ДО ему раздаются через членство и роли, как любому, а не через канал обслуживающих должностей (блок C).
4. **Отдельное подразделение «Общее собрание участников»** (`osu`), а не «Руководство»: у «Руководства» руководитель — ГД, и класть ОСУ внутрь отдела, которым командует ГД, значило бы перевернуть смысл. Подразделение без руководителя — законное состояние (у HTS/KEG так уже сделано в блоке D).
5. **Только холдинг.** У дочерних ТОО участник — сам холдинг как юрлицо, и решения «участника ДО» принимает ГД холдинга (HR-FRM-004 п. 7: «Решение участника; оформляет ГДХ»). Это кросс-компанейский согласующий — §6.2, работа другого разработчика через `ApprovalRouteStageRole.company_slug`. Заводить «Участник (ОСУ)» в каждой ДО было бы ложью о том, кто там решает. Команда `hr_participant` при этом принимает любой `--company` — запрет на уровне команды был бы решением за заказчика.
6. **Название — «Участник (ОСУ)».** Колонка документа называется «Участник / ОСУ»; скобки вместо косой черты, чтобы название читалось как должность, а не как выбор. `is_system` закрепляет его: переименовать через UI нельзя, и сосед может на него положиться — но положиться он должен не на строку, а на `hr.interface.participant_position()` (решение 7).
7. **Сосед не хардкодит название.** `hr.interface.participant_position() -> dict | None` возвращает `{id, title, is_active}` должности ОСУ в текущей компании; в компании без ОСУ — `None`. Форма — три ключа, как у прочих brief-функций интерфейса; добавляется в §6.1.
8. **Связь «ГД → ОСУ» на бою заводит кадровик, а не команда.** `hr_participant` создаёт подразделение и должность; искать генерального директора по названию строки и привязывать его автоматически — угадывание, которое на бою может попасть не в ту должность. На стенде связь идёт из справочника структур (`reports_to`).

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `backend/apps/hr/services/participant_service.py` | `ensure_participant()` — единственный способ завести ОСУ; константы названия и пути подразделения |
| `backend/apps/hr/interface.py` | `participant_position()` — контракт для соседа |
| `backend/apps/hr/management/commands/hr_participant.py` | боевой путь: `--company <slug>` |
| `backend/apps/hr/management/group_structures.py` | `Post.is_system`, ОСУ и подразделение `osu` в структуре холдинга, участник среди людей, `reports_to` у ГД |
| `backend/apps/hr/management/commands/seed_hr_demo.py` | системные должности заводятся через `participant_service`, а не upsert'ом |
| `backend/apps/hr/tests/test_participant_service.py`, `test_interface_participant.py`, `test_hr_participant_command.py` | новые тесты |
| `backend/apps/hr/tests/test_group_structures.py`, `test_seed_hr_demo.py` | правка литералов документа |
| `docs/plans/2026-09-14-group-structure-roadmap.md`, `STRUCTURE.md`, `CLAUDE.md`, `README.md` | документы |

---

### Task 1: `participant_service.ensure_participant()`

**Files:**
- Create: `backend/apps/hr/services/participant_service.py`
- Test: `backend/apps/hr/tests/test_participant_service.py`

**Interfaces:**
- Consumes: `apps.hr.models.{Department, Position, UnitType, ExternalHierarchy}`, `position_service._compute_level`, `position_service._assert_weight_free`, `position_service.WeightTaken`.
- Produces (используют задачи 2–4): константы `PARTICIPANT_TITLE = "Участник (ОСУ)"`, `PARTICIPANT_UNIT_PATH = "osu"`, `PARTICIPANT_UNIT_NAME = "Общее собрание участников"`, `PARTICIPANT_WEIGHT = 0`; функция `ensure_participant() -> tuple[Position, bool]` (должность, создана ли заново); исключение `ParticipantWeightTaken(detail)`; функция `find_participant() -> Position | None`.

- [ ] **Step 1: Написать падающий тест**

`backend/apps/hr/tests/test_participant_service.py`:

```python
"""Системная должность «Участник (ОСУ)».

ОСУ в документах — орган владельцев над генеральным директором, без штатной
единицы. В платформе это должность с ``is_system=True``: её нельзя
переименовать, перевести или удалить через интерфейс, а маршрут
согласования может сослаться на неё обычным ``position_id``. Заводится
ровно одним способом — этим сервисом, — чтобы стенд и бой не разъехались.
"""

from __future__ import annotations

import pytest

from apps.hr.models import Department, ExternalHierarchy, Position, UnitType
from apps.hr.services import participant_service as svc
from apps.hr.services import position_service


@pytest.mark.django_db
def test_creates_the_unit_and_the_system_position():
    position, created = svc.ensure_participant()
    assert created is True
    assert position.title == "Участник (ОСУ)"
    assert position.is_system is True
    assert position.weight == 0
    assert position.department.path == "osu"
    assert position.department.name == "Общее собрание участников"
    assert position.department.unit_type == UnitType.DEPARTMENT
    assert position.department.manager_id is None


@pytest.mark.django_db
def test_participant_oversees_the_group_but_does_not_serve_it():
    """Владелец видит дочерние компании (блок B), но не «обслуживает» их
    (блок C): права в ДО ему раздаются членством и ролями, как любому."""
    position, _ = svc.ensure_participant()
    assert position.is_manager is True
    assert position.external_hierarchy == ExternalHierarchy.INHERIT
    assert position.serves_subsidiaries is False
    assert position.permissions == {"hr_level": "lead", "permissions": []}


@pytest.mark.django_db
def test_level_is_computed_from_thresholds_not_hardcoded():
    """Уровень — кэш от веса; в схеме без порогов это запасной уровень,
    с порогами — тот, куда попадает вес 0."""
    position, _ = svc.ensure_participant()
    assert position.level == position_service._compute_level(0)


@pytest.mark.django_db
def test_is_idempotent_and_repairs_drift():
    first, created = svc.ensure_participant()
    assert created
    # Кто-то через ORM снял руководящий признак и поменял грейд — повторный
    # вызов возвращает ОСУ в предписанное состояние, не плодя вторую строку.
    Position.objects.filter(pk=first.pk).update(is_manager=False, grade=3)
    second, created_again = svc.ensure_participant()
    assert created_again is False
    assert second.pk == first.pk
    assert second.is_manager is True
    assert Position.objects.filter(title="Участник (ОСУ)").count() == 1
    assert Department.objects.filter(path="osu").count() == 1


@pytest.mark.django_db
def test_refuses_when_weight_zero_belongs_to_someone_else():
    """Вес 0 — вершина шкалы. Если его уже держит другая должность, молча
    подвинуть её нельзя: это чужие данные."""
    dep = Department.objects.create(name="Руководство", path="upr")
    Position.objects.create(title="Председатель", department=dep, weight=0)
    with pytest.raises(svc.ParticipantWeightTaken) as exc:
        svc.ensure_participant()
    assert "Председатель" in exc.value.detail
    assert not Position.objects.filter(title="Участник (ОСУ)").exists()


@pytest.mark.django_db
def test_find_participant_returns_none_when_absent():
    assert svc.find_participant() is None
    position, _ = svc.ensure_participant()
    assert svc.find_participant().pk == position.pk


@pytest.mark.django_db
def test_system_position_is_locked_for_ui_edits():
    """Смысл is_system: через API нельзя переименовать, перевести и
    деактивировать, нельзя удалить — иначе маршрут согласования, который
    ссылается на ОСУ, однажды укажет в пустоту."""
    from apps.hr import schemas

    position, _ = svc.ensure_participant()
    with pytest.raises(position_service.SystemPositionFieldsLocked):
        position_service.update_position(
            position.id, schemas.PositionUpdate(title="Совет"))
    with pytest.raises(position_service.SystemPositionProtected):
        position_service.delete_position(position.id)
```

- [ ] **Step 2: Убедиться, что падает**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_participant_service.py -q`
Expected: ERROR при импорте — `ImportError: cannot import name 'participant_service'`.

- [ ] **Step 3: Сервис**

`backend/apps/hr/services/participant_service.py`:

```python
"""Системная должность «Участник (ОСУ)» — блок F дорожной карты.

Общее собрание участников в документах руководства — орган владельцев НАД
генеральным директором (оргструктура, стр. 1), утверждающий назначение
директора ДО, бюджет группы и крупные сделки (HR-FRM-004, п. 7, 11, 14).
Чтобы маршрут согласования мог сослаться на него обычным ``position_id``,
ОСУ представлено должностью:

* ``is_system=True`` — переименовать, перевести в другой отдел,
  деактивировать через интерфейс нельзя (``position_service``), удалить —
  тоже. Маршрут, однажды сославшийся на ОСУ, не укажет в пустоту.
* вес ``0`` — вершина шкалы («меньший вес = выше»); отдельного порога
  уровней для ОСУ нет намеренно: ``LevelThreshold`` не допускает уровень 0,
  а дерево оргструктуры раскладывается по связям подчинения, не по номеру
  уровня, — связь «ГД → ОСУ» ставит его над генеральным директором и так.
* своё подразделение «Общее собрание участников» без руководителя: класть
  орган владельцев внутрь «Руководства», которым командует ГД, значило бы
  перевернуть смысл.
* руководящая должность с внешней иерархией (блок B): владелец видит все
  дочерние компании. НЕ ``serves_subsidiaries`` (блок C): владелец не
  обслуживает ДО, права в них ему раздаются членством и ролями, как любому.

Единственный способ завести ОСУ — ``ensure_participant()``: его зовут и
боевая команда ``hr_participant``, и демо-сид, — чтобы стенд и бой не
разъехались. Связь «ГД подчинён ОСУ» сервис НЕ заводит: искать ГД по
названию строки — угадывание, которое на бою попадёт не в ту должность.
На стенде связь идёт из справочника структур, на бою её ставит кадровик.

Функция действует в контексте ТЕКУЩЕЙ компании (схема) — как весь домен.
"""

from __future__ import annotations

from django.db import transaction

from apps.hr.models import Department, ExternalHierarchy, Position, UnitType
from apps.hr.services import position_service

PARTICIPANT_TITLE = "Участник (ОСУ)"
PARTICIPANT_UNIT_PATH = "osu"
PARTICIPANT_UNIT_NAME = "Общее собрание участников"
PARTICIPANT_WEIGHT = 0


class ParticipantWeightTaken(Exception):
    """Вес 0 держит другая должность. Двигать её молча нельзя — это чужие
    данные; человек решает сам, что с ней делать."""

    def __init__(self, holder: Position) -> None:
        self.detail = (
            f"Вес {PARTICIPANT_WEIGHT} уже занят должностью «{holder.title}» "
            f"(id={holder.id}). Освободите его (смените вес той должности) "
            f"и повторите."
        )
        super().__init__(self.detail)


# Состояние, к которому ensure_participant приводит должность ПРИ КАЖДОМ
# вызове. Это не «умолчания при создании», а предписание: повторный вызов
# чинит расхождение, а не пропускает его.
_PRESCRIBED = {
    "is_system": True,
    "is_active": True,
    "grade": 10,
    "weight": PARTICIPANT_WEIGHT,
    "is_manager": True,
    "external_hierarchy": ExternalHierarchy.INHERIT,
    "serves_subsidiaries": False,
    "permissions": {"hr_level": "lead", "permissions": []},
    "description": (
        "Общее собрание участников — высший орган управления. Утверждает "
        "назначение директоров дочерних обществ, бюджет группы и крупные "
        "сделки (HR-FRM-004)."
    ),
}


def find_participant() -> Position | None:
    return (Position.objects
            .filter(title=PARTICIPANT_TITLE, is_system=True)
            .select_related("department")
            .first())


@transaction.atomic
def ensure_participant() -> tuple[Position, bool]:
    """Завести или привести к предписанному состоянию должность ОСУ.

    Возвращает ``(должность, создана_ли_заново)``.
    """
    unit, _ = Department.objects.update_or_create(
        path=PARTICIPANT_UNIT_PATH,
        defaults={
            "name": PARTICIPANT_UNIT_NAME,
            "unit_type": UnitType.DEPARTMENT,
            "description": "Орган владельцев над генеральным директором.",
            "is_active": True,
        },
    )

    existing = find_participant()
    holder = (Position.objects
              .filter(weight=PARTICIPANT_WEIGHT)
              .exclude(pk=existing.pk if existing else None)
              .first())
    if holder is not None:
        raise ParticipantWeightTaken(holder)

    fields = {**_PRESCRIBED, "department": unit,
              "level": position_service._compute_level(PARTICIPANT_WEIGHT)}
    if existing is None:
        position = Position.objects.create(title=PARTICIPANT_TITLE, **fields)
        return position, True

    for name, value in fields.items():
        setattr(existing, name, value)
    existing.save()
    return existing, False
```

`Position.objects.filter(weight=…).exclude(pk=None)` — `exclude(pk=None)` в Django исключает ничего; если линтер или тест на это укажет, разведи на две ветки (`if existing is None: … else: .exclude(pk=existing.pk)`) — поведение то же.

- [ ] **Step 4: Тесты зелёные**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_participant_service.py -q`
Expected: все passed. Если `test_system_position_is_locked_for_ui_edits` падает на имени исключения — открой `position_service.py:411-416` и `:445-447` и возьми имена оттуда; менять сервис должностей нельзя.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/hr/services/participant_service.py backend/apps/hr/tests/test_participant_service.py
git commit -m "feat(hr): системная должность «Участник (ОСУ)» заводится одним сервисом

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Контракт наружу — `hr.interface.participant_position()`

**Files:**
- Modify: `backend/apps/hr/interface.py`
- Test: `backend/apps/hr/tests/test_interface_participant.py`

**Interfaces:**
- Consumes: `participant_service.find_participant`.
- Produces: `apps.hr.interface.participant_position() -> dict | None` с ключами РОВНО `id`, `title`, `is_active`. Добавляется в roadmap §6.1 (задача 5).

- [ ] **Step 1: Написать падающий тест**

`backend/apps/hr/tests/test_interface_participant.py`:

```python
"""Контракт `hr.participant_position` — как сосед находит ОСУ.

Название должности зафиксировано ``is_system``, но сосед не должен
хардкодить строку «Участник (ОСУ)»: он спрашивает, и получает либо brief,
либо ``None`` там, где органа владельцев нет (дочерние компании — решение 5
плана блока F).
"""

from __future__ import annotations

import pytest

from apps.core.services import ServiceDisabled
from apps.hr import interface
from apps.hr.services import participant_service as svc


@pytest.mark.django_db
def test_returns_exactly_the_agreed_keys():
    position, _ = svc.ensure_participant()
    brief = interface.participant_position()
    assert set(brief) == {"id", "title", "is_active"}
    assert brief == {"id": position.id, "title": "Участник (ОСУ)", "is_active": True}


@pytest.mark.django_db
def test_company_without_a_participant_body_returns_none():
    assert interface.participant_position() is None


@pytest.mark.django_db
def test_disabled_hr_refuses(monkeypatch):
    from apps.core import services as core_services

    svc.ensure_participant()
    monkeypatch.setattr(core_services, "service_status",
                        lambda name: (False, "выключено для проверки"))
    with pytest.raises(ServiceDisabled):
        interface.participant_position()
```

- [ ] **Step 2: Убедиться, что падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_interface_participant.py -q`
Expected: FAIL — `AttributeError: module 'apps.hr.interface' has no attribute 'participant_position'`.

- [ ] **Step 3: Функция интерфейса**

`backend/apps/hr/interface.py`, в конец файла, рядом с `substitutes_for`:

```python
def participant_position() -> dict | None:
    """Должность «Участник (ОСУ)» в ТЕКУЩЕЙ компании — или ``None``.

    Общее собрание участников утверждает назначение директора ДО, бюджет
    группы и крупные сделки (HR-FRM-004, п. 7, 11, 14); маршрут
    согласования ссылается на него обычным ``position_id`` — этим и берёт.
    Держателей резолвит ``resolve_position_users``, как для любой должности.

    Сосед не хардкодит название: оно закреплено ``is_system``, но знать его
    соседу незачем. ``None`` — законный ответ: у дочерних компаний органа
    владельцев в платформе нет, там «участник» — сам холдинг, и решение
    принимает его генеральный директор (кросс-компанейский этап, roadmap §6.2).

    Ровно три ключа — форма закреплена в roadmap §6.1.
    """
    require_service("hr")
    from apps.hr.services import participant_service

    position = participant_service.find_participant()
    if position is None:
        return None
    return {"id": position.id, "title": position.title,
            "is_active": position.is_active}
```

- [ ] **Step 4: Тесты зелёные + сторож границ**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_interface_participant.py apps/core/tests/test_app_isolation.py -q`
Expected: все passed.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/hr/interface.py backend/apps/hr/tests/test_interface_participant.py
git commit -m "feat(hr): контракт participant_position — сосед находит ОСУ, не хардкодя название

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Боевой путь — `manage.py hr_participant --company <slug>`

**Files:**
- Create: `backend/apps/hr/management/commands/hr_participant.py`
- Test: `backend/apps/hr/tests/test_hr_participant_command.py`

**Interfaces:**
- Consumes: `participant_service.ensure_participant`, `apps.companies.interface.{get_company, schema_exists}`, `htqweb.tenancy.db.use_company`.
- Produces: `manage.py hr_participant --company SLUG` — идемпотентно; печатает «заведена» / «уже есть, приведена к предписанному состоянию»; отказ понятной ошибкой, если компании нет, схемы нет или вес 0 занят.

- [ ] **Step 1: Написать падающий тест**

`backend/apps/hr/tests/test_hr_participant_command.py`:

```python
"""``hr_participant`` — боевой способ завести ОСУ в компании.

Команда обязана писать ТОЛЬКО туда, куда её явно направили: ``--company``
обязателен, умолчания на текущий ``search_path`` нет — на бою ``public``
это не компания, и молчаливая запись туда была бы подменой данных.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.hr.models import Department, Position


def _run(**kwargs):
    call_command("hr_participant", verbosity=0, **kwargs)


def test_company_is_required(db):
    with pytest.raises(CommandError):
        _run()


def test_unknown_company_is_refused(db):
    with pytest.raises(CommandError, match="не найдена"):
        _run(company="t-no-such-company")


def test_company_without_schema_is_refused(db):
    from apps.companies.models import Company, CompanyKind
    Company.objects.create(slug="t-orphan", name="Сирота", kind=CompanyKind.HOLDING)
    with pytest.raises(CommandError, match="схем"):
        _run(company="t-orphan")


def test_creates_the_participant_in_the_company_schema(company_schema, capsys):
    from htqweb.tenancy.db import use_company

    call_command("hr_participant", company=company_schema["slug"], verbosity=1)
    out = capsys.readouterr().out
    assert "заведена" in out
    with use_company(company_schema["slug"]):
        position = Position.objects.get(title="Участник (ОСУ)")
        assert position.is_system is True
        assert position.department.path == "osu"
    # public не тронут.
    assert not Position.objects.filter(title="Участник (ОСУ)").exists()
    assert not Department.objects.filter(path="osu").exists()


def test_second_run_reports_repair_not_creation(company_schema, capsys):
    call_command("hr_participant", company=company_schema["slug"], verbosity=1)
    capsys.readouterr()
    call_command("hr_participant", company=company_schema["slug"], verbosity=1)
    out = capsys.readouterr().out
    assert "уже есть" in out
    from htqweb.tenancy.db import use_company
    with use_company(company_schema["slug"]):
        assert Position.objects.filter(title="Участник (ОСУ)").count() == 1


def test_weight_conflict_is_a_readable_error(company_schema):
    from htqweb.tenancy.db import use_company

    with use_company(company_schema["slug"]):
        dep = Department.objects.create(name="Руководство", path="upr")
        Position.objects.create(title="Председатель", department=dep, weight=0)
    with pytest.raises(CommandError, match="Председатель"):
        _run(company=company_schema["slug"])
```

- [ ] **Step 2: Убедиться, что падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_hr_participant_command.py -q`
Expected: FAIL — `CommandError: Unknown command: 'hr_participant'`.

- [ ] **Step 3: Команда**

`backend/apps/hr/management/commands/hr_participant.py`:

```python
"""Завести системную должность «Участник (ОСУ)» в компании — блок F.

Боевой путь: холдинг заводится ``company_create`` (roadmap §7, шаг 5), после
чего этой командой в его схему кладётся орган владельцев. Демо-стенд делает
то же самое внутри ``seed_hr_demo`` тем же сервисом — двух реализаций нет.

``--company`` обязателен, умолчания на текущий ``search_path`` нет: на бою
``public`` — не компания (режим перехода, roadmap §3), и молчаливая запись
туда была бы подменой данных. Проверки те же, что у остальных команд с
``--company``: строка реестра есть, физическая схема есть (``SET search_path``
принял бы несуществующую схему молча, и запись ушла бы в ``public``).

Связь «ГД подчинён ОСУ» команда НЕ ставит — см. докстринг
``participant_service``. После команды кадровик соединяет их в дереве
оргструктуры.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.hr.services import participant_service


class Command(BaseCommand):
    help = "Завести должность «Участник (ОСУ)» в схеме компании. Идемпотентно."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", dest="company", required=True,
            help="slug компании (обычно холдинг). Умолчания нет намеренно.",
        )

    def handle(self, *args, **options):
        slug = options["company"]
        from apps.companies import interface as companies

        if companies.get_company(slug) is None:
            raise CommandError(f"Компания {slug!r} не найдена в реестре.")
        if not companies.schema_exists(slug):
            raise CommandError(
                f"У компании {slug!r} нет схемы Postgres — SET search_path принял "
                f"бы её молча и данные ушли бы в public. Заведите схему: "
                f"manage.py company_create либо migrate_companies --company {slug}."
            )

        from htqweb.tenancy.db import use_company

        with use_company(slug):
            try:
                position, created = participant_service.ensure_participant()
            except participant_service.ParticipantWeightTaken as exc:
                raise CommandError(exc.detail) from exc

        state = "заведена" if created else "уже есть, приведена к предписанному состоянию"
        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug}: должность «{position.title}» (id={position.id}) {state}. "
            f"Соедините её с генеральным директором в дереве оргструктуры."
        ))
```

- [ ] **Step 4: Тесты зелёные**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_hr_participant_command.py -q`
Expected: все passed. `test_company_is_required` ловит `CommandError` от `argparse` (`required=True`) — это штатное поведение `call_command`.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/hr/management/commands/hr_participant.py backend/apps/hr/tests/test_hr_participant_command.py
git commit -m "feat(hr): hr_participant — ОСУ заводится в компании одной командой

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: ОСУ в справочнике структур и в демо-стенде

**Files:**
- Modify: `backend/apps/hr/management/group_structures.py` (`Post.is_system`, структура холдинга)
- Modify: `backend/apps/hr/management/commands/seed_hr_demo.py` (`_seed_positions`: системные должности через сервис)
- Test: `backend/apps/hr/tests/test_group_structures.py`, `backend/apps/hr/tests/test_seed_hr_demo.py`

**Interfaces:**
- Consumes: `participant_service.{ensure_participant, PARTICIPANT_TITLE, PARTICIPANT_UNIT_PATH}`.
- Produces: `Post(..., is_system=True)`; в структуре холдинга появляется `Unit("osu", …)`, `Post("Участник (ОСУ)", "osu", 0, …, is_system=True)`, у «Генеральный директор» — `reports_to="Участник (ОСУ)"`, среди людей — участник.

- [ ] **Step 1: Данные и падающие тесты**

В `group_structures.py`:

К датаклассу `Post` добавить поле `is_system: bool = False` (последним, с умолчанием — существующие вызовы не меняются).

В `_HOLDING.units` первой строкой:
```python
        Unit("osu", "Общее собрание участников",
             description="Орган владельцев над генеральным директором."),
```

В `_HOLDING.posts` первой строкой, и правка ГД:
```python
        Post("Участник (ОСУ)", "osu", 0, 10, "lead",
             is_manager=True, external_hierarchy="inherit", is_system=True),
        Post("Генеральный директор", "upr", 10, 10, "lead", "Участник (ОСУ)",
             is_manager=True, external_hierarchy="inherit"),
```

В `_HOLDING.people` первой строкой:
```python
        Person("Сарсенов", "Бауыржан", "Маратович", "Участник (ОСУ)", "+7 (700) 100-00-01"),
```

Над структурой холдинга — комментарий:
```python
# Блок F: «Участник (ОСУ)» — орган владельцев над ГД (оргструктура, стр. 1).
# В документе он нарисован без штатной единицы и в счётчик «всего 12» не
# входит; в справочнике это системная должность (is_system) с весом 0 в своём
# подразделении, чтобы маршрут согласования мог сослаться на неё position_id.
# Заводится через participant_service, а не upsert'ом сида — один код на
# стенд и бой.
```

`managers` холдинга не трогать: у «Общего собрания участников» руководителя нет намеренно (решение 4).

Тесты в `test_group_structures.py` — править литералы с комментарием «блок F»:

- `test_headcount_matches_the_document`: холдинг — `posts` 13 и `people` 13, но ДОКУМЕНТ говорит 12 → считать штатные: заменить параметр холдинга на `(HOLDING, 12, 12)` и внутри считать `[p for p in structure.posts if not p.is_system]` и `[p for p in structure.people if p.post not in system_titles]`; отдельно `assert sum(p.is_system for p in HOLDING.posts) == 1`.
- `test_holding_has_four_managers_and_eight_serving_specialists`: `directors = [p for p in HOLDING.posts if p.is_manager and not p.is_system]` — по-прежнему 4; добавить `participant = next(p for p in HOLDING.posts if p.is_system)`, `assert participant.is_manager and participant.external_hierarchy == "inherit" and not participant.serves_subsidiaries`.
- `test_levels_used_by_each_structure`: холдинг остаётся `{1, 2, 4}` — вес 0 попадает в N-1 (решение 1); добавить комментарий.
- `test_every_reference_resolves`: «ровно одна должность без начальника» — теперь это ОСУ; добавить `assert heads[0].title == "Участник (ОСУ)"` для холдинга (для остальных структур глава — «Директор», как было).
- `test_direct_chain_matches_the_document`: в `"holding"` добавить пару `("Генеральный директор", "Участник (ОСУ)")` с комментарием «стр. 1: ОСУ над ГД».
- Новый тест:

```python
def test_participant_is_the_only_system_post_and_sits_on_top():
    """ОСУ — единственная системная должность, с весом 0 (вершина шкалы),
    в своём подразделении, и оно есть только у холдинга."""
    system = [p for p in HOLDING.posts if p.is_system]
    assert [p.title for p in system] == ["Участник (ОСУ)"]
    assert system[0].weight == 0 and system[0].unit == "osu"
    assert min(p.weight for p in HOLDING.posts) == 0
    for kind in ("construction", "it", "service"):
        assert not any(p.is_system for p in gs.STRUCTURES[kind].posts)
        assert not any(u.path == "osu" for u in gs.STRUCTURES[kind].units)
```

- `test_emails_are_unique_across_the_whole_group` — не меняется, новый участник (sarsenov.b) уникален.

Тесты в `test_seed_hr_demo.py`: в `test_holding_structure_sets_serving_and_managing_flags` число `is_manager=True, external_hierarchy="inherit"` становится **5** (4 директора + ОСУ), число `direct`-связей — **12**; добавить:

```python
def test_holding_seed_creates_the_participant_through_the_service(company_schema):
    from django.core.cache import cache

    from apps.companies.models import Company
    from htqweb.tenancy.db import use_company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="holding")
    cache.clear()
    _seed(company=company_schema["slug"])
    with use_company(company_schema["slug"]):
        osu = Position.objects.get(title="Участник (ОСУ)")
        assert osu.is_system is True and osu.weight == 0
        assert osu.department.path == "osu" and osu.department.manager_id is None
        ceo = Position.objects.get(title="Генеральный директор")
        assert ReportingRelation.objects.filter(
            superior_position=osu, subordinate_position=ceo, relation_type="direct").exists()
        assert Employee.objects.filter(position=osu).count() == 1
```

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_group_structures.py apps/hr/tests/test_seed_hr_demo.py -q` → FAIL (у `Post` нет `is_system`; сид не знает про системные должности).

- [ ] **Step 2: Сид — системные должности через сервис**

В `seed_hr_demo.py`, в `_seed_positions`, ПЕРЕД циклом `update_or_create`:

```python
        # Системные должности заводит их сервис, а не upsert сида: на бою их
        # кладёт та же функция (hr_participant), и два пути к одной строке
        # разъехались бы. Сегодня системная должность одна — ОСУ.
        from apps.hr.services import participant_service

        for post in structure.posts:
            if not post.is_system:
                continue
            assert post.title == participant_service.PARTICIPANT_TITLE, post.title
            assert post.unit == participant_service.PARTICIPANT_UNIT_PATH, post.unit
            try:
                position, _ = participant_service.ensure_participant()
            except participant_service.ParticipantWeightTaken as exc:
                raise CommandError(exc.detail) from exc
            out[post.title] = position
```

и в основном цикле — `if post.is_system: continue`. Подразделение `osu` при этом заводит `_seed_units` (оно есть в `structure.units`) ДО должностей, а `ensure_participant` делает `update_or_create` по тому же `path` — конфликта нет, второй вызов лишь подтверждает состояние.

`_check_no_foreign_positions_on_our_weights` — вес 0 ОСУ входит в `wanted_weights`; чужая должность на весе 0 попадёт в понятную ошибку, как и остальные, — ничего менять не нужно.

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_group_structures.py apps/hr/tests/test_seed_hr_demo.py apps/hr/tests/test_participant_service.py -q`
Expected: все passed.

- [ ] **Step 3: Сторож миграций**

Run (со строкой переменных окружения из CLAUDE.md): `../.venv/Scripts/python.exe manage.py makemigrations hr --check`
Expected: `No changes detected` — в блоке F модель не менялась.

- [ ] **Step 4: Коммит**

```bash
git add backend/apps/hr/management/group_structures.py backend/apps/hr/management/commands/seed_hr_demo.py backend/apps/hr/tests/test_group_structures.py backend/apps/hr/tests/test_seed_hr_demo.py
git commit -m "feat(hr): «Участник (ОСУ)» над генеральным директором в структуре холдинга

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Сквозная проверка и документы

**Files:**
- Modify: `docs/plans/2026-09-14-group-structure-roadmap.md` (§4 строка про ОСУ, §5.F → «(выполнено)», §6.1 + строка `hr.participant_position`, §6.2 — снять оговорку «`user`/`role` — если ОСУ не пойдёт по варианту F», §7 шаг 5 — после `company_create` холдинга: `hr_participant --company hi-tech-group`), `CLAUDE.md` (команда в блок «Django management» + абзац), `README.md` (команда), `STRUCTURE.md` (сервис одной строкой).

- [ ] **Step 1: Прогоны (гонит КОНТРОЛЛЕР)**

`../.venv/Scripts/python.exe -m pytest -q` — полный сьют, ожидается ровно 8 известных падений. Фронт не менялся — `npx vitest run` только как контроль (8 базовых).

- [ ] **Step 2: Сквозной прогон на dev-базе**

Из `backend/`, со строкой переменных окружения:

```
manage.py hr_participant --company hi-tech-group      # заведена
manage.py hr_participant --company hi-tech-group      # уже есть
manage.py seed_hr_demo --company hi-tech-group        # связь ГД → ОСУ и участник
```

Проверка через Bash:

```bash
docker exec htqweb-local-db-1 psql -U htqweb -d htqweb -At -c "
select p.title, p.weight, p.is_system, d.path, d.manager_id
from co_hi_tech_group.hr_position p join co_hi_tech_group.hr_department d on d.id = p.department_id
where p.title = 'Участник (ОСУ)';"
docker exec htqweb-local-db-1 psql -U htqweb -d htqweb -At -c "
select sup.title, sub.title, r.relation_type
from co_hi_tech_group.hr_reportingrelation r
join co_hi_tech_group.hr_position sup on sup.id = r.superior_position_id
join co_hi_tech_group.hr_position sub on sub.id = r.subordinate_position_id
where sup.title = 'Участник (ОСУ)';"
```
Expected: `Участник (ОСУ)|0|t|osu|` и `Участник (ОСУ)|Генеральный директор|direct`. Должностей в холдинге — 13, сотрудников — 13.

- [ ] **Step 3: Документы**

Roadmap: §4 — добавить строку «ОСУ / Участник | ✅ системная должность `Участник (ОСУ)` над ГД, `hr_participant`, `hr.participant_position()` | «N-0» реализован положением в дереве, не порогом (решение 1 плана F)». §5.F — «(выполнено)» и три строки о сделанном. §6.1 — строка `hr.participant_position() -> {id, title, is_active} | None` — «есть, блок F» — «утверждающий ОСУ в маршрутах (HR-FRM-004 п. 7, 11, 14)». §6.2 — первый пункт переписать: «`ApproverKind`: `manager_of_initiator` (через `hr.manager_position_of`); ОСУ — обычная должность по `hr.participant_position()`, отдельного вида согласующего не нужно». §7 шаг 5 — после `company_create` холдинга добавить `manage.py hr_participant --company hi-tech-group`, затем «кадровик соединяет ОСУ с ГД в дереве».

`CLAUDE.md`, блок «Django management»: строка `../.venv/Scripts/python.exe manage.py hr_participant --company SLUG   # системная должность «Участник (ОСУ)» в схеме компании; идемпотентно`. В раздел «Мультикомпанейность», после абзаца о замещении:

«**ОСУ — системная должность, не порог уровней.** `hr.Position` «Участник (ОСУ)» (`is_system`, вес 0, своё подразделение `osu`) над генеральным директором холдинга; заводится только `participant_service.ensure_participant()` — через `manage.py hr_participant` на бою и `seed_hr_demo` на стенде. Маршруты согласования берут её через `hr.interface.participant_position()` (ровно `id`, `title`, `is_active`; `None` в компании без органа владельцев). Отдельного уровня N-0 нет намеренно: `LevelThreshold` не допускает 0, а дерево раскладывается по связям подчинения. Связь «ГД → ОСУ» на бою ставит кадровик — команда не угадывает ГД по названию.»

`README.md` — строка команды в блок management-команд. `STRUCTURE.md` — `services/participant_service.py` одной строкой в составе `apps/hr`.

- [ ] **Step 4: Коммит**

```bash
git add docs/plans/2026-09-14-group-structure-roadmap.md CLAUDE.md README.md STRUCTURE.md
git commit -m "docs: блок F закрыт — «Участник (ОСУ)» адресуем в маршрутах согласования

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Что осталось за рамками (названо заранее)

- **Отдельный ярус N-0 в бейдже уровня.** Потребует: ослабить `ck_threshold_level_positive` и пять `ge=1` в схемах, data-миграцию «вырезать 0–9 из N-1» по всем схемам с защитой от боевых порогов ETL, правку сида порогов. Делается только по явному желанию заказчика.
- **ОСУ в дочерних компаниях** — там «участник» = холдинг; это кросс-компанейский согласующий, работа другого разработчика (§6.2).
- **Роли/членство держателя ОСУ в ДО** — через `company_grant` и роли, как любому (решение 3).

## Self-review

**Покрытие спеки (§5.F):** «должность уровня N-0 в холдинге» → задачи 1, 4 (с решением 1 о том, что такое «N-0»); «`is_system`» → задача 1 (закреплено тестом на блокировку правок); «маршруты signoff ссылаются обычным `position_id`» → задача 2 даёт соседу способ узнать этот id, §6.2 обновляется в задаче 5. Сверх спеки: боевая команда (задача 3) — без неё на бою ОСУ было бы не завести вовсе (API ставит `is_system=False` всему созданному).

**Заглушек нет:** код задач 1–3 целиком; в задаче 4 правки данных и литералов заданы построчно.

**Согласованность имён:** `PARTICIPANT_TITLE`/`PARTICIPANT_UNIT_PATH`/`ensure_participant`/`find_participant`/`ParticipantWeightTaken` (1 → 2, 3, 4); `participant_position` три ключа (2 → §6.1); `Post.is_system` (4); текст «заведена» / «уже есть» (3 — команда и её тесты).

**Риски:** вес 0 может быть занят на боевой схеме — команда отказывает понятной ошибкой, не двигая чужое; литералы блока D меняются в четырёх тестах — каждая правка подписана «блок F».
