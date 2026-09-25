# Блок G «HR-субъекты согласования» (HR-FRM-004, строки 1–10) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Все десять кадровых решений матрицы полномочий HR-FRM-004 перестают быть бумагой: у каждого появляется объект в платформе, который отправляется на согласование существующим движком `apps.signoff` и несёт факты, по которым второй разработчик строит маршруты (сумма премии, срок отпуска, категория должности).

**Architecture:** Движок согласования не трогается вовсе. Каждый кадровый предмет — модель в `apps.hr`, наследующая `signoff.interface.Approvable`, объявляющая `SIGNOFF_SUBJECT_TYPE = "hr.<…>"` и регистрируемая в `apps/hr/approval_hooks.py::register()`, который зовёт `HrConfig.ready()` — ровно так, как это сделано в `apps/contracts`. Наружу — одна ручка «отправить на согласование» на предмет, через `apps.signoff.interface.start_process`. Ключ блока — не модели, а **факты**: именно по ним маршрут ветвится, и именно их ждёт §6.2.

**Tech Stack:** Django 5.2.7 / Python 3.13 (корневой `.venv`), Pydantic-схемы, pytest-django против Postgres `:55432`. Фронта в блоке нет — экраны кадровых заявок отдельная работа, здесь только модели, регистрация и ручки.

**Spec:** [2026-09-14-group-structure-roadmap.md](2026-09-14-group-structure-roadmap.md) §5.G (моя половина), §6.2 (что ждёт signoff), §6.4 (список subject-типов и фактов уезжает второму разработчику), §3 (режим перехода). Документ руководства: **HR-FRM-004 «Матрица полномочий»** — перерисована целиком в §«Данные документа» ниже. Образец реализации в этом же репозитории: `apps/contracts/approval_hooks.py`, `apps/contracts/models.py:66-67`, `apps/contracts/apps.py::ready`.

## Global Constraints

- Интерпретатор — **корневой** `.venv`. Из `backend/`: `../.venv/Scripts/python.exe -m pytest <path> -q`.
- **Один прогон pytest за раз, всегда в форграунде, никогда в фоне и не через монитор.** Полный сьют ~45 мин, `apps/hr` ~10 мин, `apps/signoff` ~4 мин.
- Межаппный доступ — только через `apps.<x>.interface` (сторож `apps/core/tests/test_app_isolation.py`); межаппных FK нет. Из `signoff` в `hr` импортируется РОВНО `apps.signoff.interface` — и в моделях (`Approvable`), и в хуках, и во вьюхах.
- `hr` — **тенантная** аппка: миграции доводит `manage.py migrate_companies` отдельным шагом выкатки. Только expand. **Каждая задача — своя миграция**, номера идут подряд от `hr/0027`.
- **Зона:** `apps/signoff/**` и `apps/contracts/**` НЕ трогаются. Движок, маршруты, `ApproverKind`, кросс-компанейские этапы — работа второго разработчика (§6.2). Блок G только предоставляет субъекты и факты.
- Режим перехода (roadmap §3): на бою одна действующая компания; ничего не переносим, не переименовываем, не удаляем.
- **Ветки не создавать** — работа в выданной ветке (`sanzhar`).
- Трейлер коммитов: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Известные падения бэкенда — ровно `backend/ci-known-failures.txt` (8 штук), из них **пять в `apps/signoff`**: они были до блока и к нему отношения не имеют. Шестое падение в signoff — наше.
- **Сторожа, о которых обязан знать исполнитель:** `test_positions_api.py` пинит точный набор ключей `PositionOut`; `test_group_structures.py` пинит данные оргструктуры литералами; `htqweb/date_rules.py` — **каждая пара дат в платформе обязана быть в `DATE_PAIRS`, схемы наследуют `OrderedDates`, сервис зовёт `assert_instance_ordered` перед `save()`, вьюха переводит `DatesOutOfOrder` в 422** (в этом блоке пар дат МНОГО — см. задачи 4, 5, 6); `apps/core/tests/test_invariants.py` ловит новые ограничения `ck_*dates`, поэтому ограничение на пару дат обязано называться `ck_<модель>_dates`.
- `manage.py` без блока переменных окружения из CLAUDE.md («Reaching the dev database from the host») висит 120 с на недоступном `db` — строку не сокращать.

---

## Данные документа (HR-FRM-004), перерисованные целиком

И — инициирует/готовит; С — согласовывает; У — утверждает (право подписи).

| № | Решение | Участник/ОСУ | ГД УК | CFO | Техн. дир. | Опер. дир. | Рук. блока | Примечание |
|---|---|---|---|---|---|---|---|---|
| 1 | Утверждение и изменение оргструктуры УК | | **У** | | | И | | |
| 2 | Утверждение и изменение штатного расписания УК | | **У** | С | | И | | ФОТ — в пределах бюджета |
| 3 | Утверждение локальных нормативных актов (политик, положений) | | **У** | С | | | И | Юр. экспертиза — юрконсультант |
| 4 | Утверждение должностных инструкций | | **У** | | | С | И | |
| 5 | Приём и увольнение специалистов УК | | **У** | | | С | И | |
| 6 | Приём и увольнение руководителей блоков УК | | **У** | | | С | | ⚠️ инициатора (И) нет — вопрос руководству §8.4 |
| 7 | Назначение и смена директора дочернего общества | **У** | И | | | | | Решение участника; оформляет ГДХ |
| 8 | Премирование работников | | **У** | С | | | И | По KPI и Положению о премировании |
| 9 | Применение дисциплинарных взысканий | | **У** | | | С | И | |
| 10 | Утверждение графика отпусков; направление в командировку | | **У** | | | И | | |
| 11–15 | финансовые строки | | | | | | | **не в этом блоке** — зона contracts (§6.3) |

## Решения заказчика (приняты 16.09.2026, обязательны к исполнению)

1. **Объём — все десять строк**, а не пять, названные роадмапом. Строки 1, 3, 4, 7 добавлены сверх §5.G по прямому решению заказчика.
2. **Строка 10 разбивается на ТРИ предмета:** годовой график отпусков, отдельное заявление на отпуск, командировка. У них разные поля, разные факты и разные маршруты; сливать их в один субъект значило бы ветвить маршрут по виду внутри одного типа и всегда держать половину полей пустыми.
3. **Приём/увольнение — новый кадровый приказ**, а не пометка существующей кадровой истории. Согласуется ПРИКАЗ; после утверждения он пишет запись в `PersonnelHistory`. Кадровая история остаётся журналом того, что УЖЕ произошло, и её читателям (карточка сотрудника, стаж, отчёты) не приходится знать про состояние согласования.

## Решения, принятые при планировании (для проверки заказчиком)

4. **Десять строк матрицы → десять subject-типов, девять новых моделей.** Строки 5, 6 и 7 — один тип `hr.personnel_order`: это одно и то же действие (назначение/освобождение), различающееся КАТЕГОРИЕЙ должности и компанией. Различие живёт в фактах (`position_level`, `is_manager`, `target_company_slug`), по которым маршрут и ветвится, — именно этого §6.2 и просит («категория должности»). Заводить три модели с одинаковыми полями значило бы три раза написать одно и то же и лишить маршрут возможности сказать «для руководителей блоков — такой-то этап».
5. **Согласуется строка штатного расписания, а не расписание целиком.** Контейнера «штатное расписание» в домене нет, а приказ на практике меняет конкретную позицию (добавить единицу, изменить оклад). Факты `salary`, `headcount`, `department_id` дают маршруту ровно то, что нужно примечанию документа «ФОТ — в пределах бюджета».
6. **Оргструктура (строка 1) — заявка на изменение, а не дерево.** Согласовать «дерево» нельзя: у него нет версии и нет момента. `OrgChangeRequest` — это приказ: что меняем (текстом), с какой даты, кто инициатор, приложение. После утверждения изменение вносит кадровик руками. Автоматическое применение диффа оргструктуры — отдельный крупный проект, и он в этот блок не входит.
7. **Локальные нормативные акты — своя модель `Policy`, а не существующий `Document`.** `Document` привязан к СОТРУДНИКУ (`Document.employee`); политика компании ничьей карточке не принадлежит. Использовать его значило бы завести «документ ничей» и сломать смысл поля.
8. **Должностная инструкция — своя модель `JobDescription`, привязанная к должности, с версией.** Не поле `Position.description`: инструкция утверждается версиями и живёт своей историей, а описание должности — редактируемый текст карточки.
9. **Ни одна новая модель не входит в `HOLDING_MODELS`.** Сводное чтение кадровых заявок по всей группе никем не заказано, а включение модели в сводки стоит пересборки представлений на каждой выкатке.
10. **Ручка «отправить на согласование» — под обычным JWT, без `admin=True`.** Заявку подаёт сотрудник или кадровик, а не платформенный администратор; это ровно тот выбор, что сделан в `apps/contracts` (`SubmitView`, `admin=False`) и по той же причине. Утверждает — маршрут, а не право на ручку.
11. **Ни одного `on_approved`, который меняет чужие данные, кроме `PersonnelOrder`.** Только приказ пишет кадровую историю (решение заказчика 3). Остальные девять предметов после утверждения просто становятся утверждёнными — дальше с ними работает человек. Каждый автоматический эффект — это риск, и вводить их без заказа нельзя.
12. **Суммы — `DecimalField(max_digits=12, decimal_places=2)`**, как у денег в `StaffingPosition.salary` и в `contracts`. Валюта отдельным полем не заводится: домен кадров одновалютный, и первый же мультивалютный случай потребует не поля, а решения заказчика.

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `backend/apps/hr/models.py` | девять новых моделей + `Approvable` на `StaffingPosition` |
| `backend/apps/hr/migrations/0027…0033` | по миграции на задачу, все expand |
| `backend/apps/hr/approval_hooks.py` | `register()` + `describe`/`facts`/`fact_fields` на каждый предмет |
| `backend/apps/hr/apps.py` | `HrConfig.ready()` зовёт `approval_hooks.register()` |
| `backend/apps/hr/services/approval_service.py` | `submit_for_approval(subject_type, subject_id, actor_id)` — одна функция на все предметы |
| `backend/apps/hr/views.py`, `urls.py` | ручки «отправить на согласование» |
| `backend/apps/hr/schemas.py` | схемы создания заявок (там, где нужны) |
| `docs/plans/2026-09-14-group-structure-roadmap.md`, `API.md`, `STRUCTURE.md`, `CLAUDE.md` | документы + §6.4 сводка для второго разработчика |

---

### Task 1: Каркас и первый предмет — штатное расписание (строка 2)

Эта задача задаёт ОБРАЗЕЦ для всех остальных: примесь, регистрация, хуки, сервис отправки, ручка, тесты. Остальные семь задач повторяют её форму на своих моделях.

**Files:**
- Modify: `backend/apps/hr/models.py` (`StaffingPosition` наследует `Approvable`)
- Create: `backend/apps/hr/migrations/0027_staffingposition_approval_state.py`
- Create: `backend/apps/hr/approval_hooks.py`
- Modify: `backend/apps/hr/apps.py` (`ready()`)
- Create: `backend/apps/hr/services/approval_service.py`
- Modify: `backend/apps/hr/views.py`, `backend/apps/hr/urls.py`
- Modify: `backend/apps/signoff/interface.py` — ОДНА строка в `__all__` (см. ⚠️ ниже), больше в этой аппке ничего
- Test: `backend/apps/hr/tests/test_approval_subjects.py`

**Interfaces:**
- Consumes: `apps.signoff.interface` — `Approvable`, `register_subject`, `start_process`, `approval_state_of`, `has_active_route`, исключения `SignoffError`, `RouteNotConfigured`, `AlreadyInApproval`, `RouteUnusable`, `SubjectLocked`.
- Produces (используют задачи 2–8): `approval_hooks.register()`; `approval_service.submit_for_approval(subject_type: str, subject_id: int, *, actor_id: int | None) -> dict`; исключение `SubjectNotFound`; вьюха-диспетчер `submit_subject(request, subject_type, subject_id)`; путь `POST /api/hr/v1/approvals/<subject_type>/<int:subject_id>/submit`.

- [ ] **Step 1: Написать падающий тест**

`backend/apps/hr/tests/test_approval_subjects.py`:

```python
"""Кадровые предметы согласования (HR-FRM-004).

Движок согласования — чужой (apps.signoff) и в этом блоке не трогается.
Проверяется ровно то, за что отвечает домен кадров: предмет объявлен
согласуемым, зарегистрирован под своим типом, отдаёт факты, по которым
маршрут ветвится, и отправляется на согласование одной ручкой.

Факты — не украшение: именно по ним второй разработчик строит условия
маршрута (roadmap §6.2 просит сумму премии, срок отпуска и категорию
должности). Поэтому набор ключей фактов пинится точным сравнением: лишний
или переименованный ключ — это сломанное условие в чужом маршруте.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.hr.models import Department, Position, StaffingPosition
from apps.signoff import interface as signoff

BASE = "/api/hr/v1"


@pytest.fixture
def dep(db):
    return Department.objects.create(name="Дирекция по финансам", path="fin")


@pytest.fixture
def staffing_line(dep):
    position = Position.objects.create(title="Главный бухгалтер", department=dep, weight=610)
    return StaffingPosition.objects.create(
        position=position, department=dep, headcount=1, salary=800000, grade=8)


@pytest.mark.django_db
def test_staffing_position_is_approvable(staffing_line):
    """Примесь даёт колонку состояния на самой таблице предмета —
    межаппного FK при этом не возникает."""
    assert staffing_line.approval_state == signoff.ApprovalState.DRAFT
    assert staffing_line.SIGNOFF_SUBJECT_TYPE == "hr.staffing_position"
    assert staffing_line.is_approved is False


@pytest.mark.django_db
def test_subject_is_registered_under_its_type():
    registered = {s["subject_type"]: s for s in signoff.registered_subjects()}
    assert "hr.staffing_position" in registered
    assert registered["hr.staffing_position"]["label"] == "Штатная единица"


@pytest.mark.django_db
def test_facts_carry_exactly_the_agreed_keys(staffing_line):
    from apps.hr import approval_hooks

    facts = approval_hooks._staffing_facts(staffing_line.id)
    assert set(facts) == {"department_id", "position_id", "position_level",
                          "headcount", "salary", "payroll"}
    assert facts["salary"] == 800000
    # Фонд оплаты труда строки — это оклад, умноженный на число единиц:
    # примечание документа «ФОТ — в пределах бюджета» ветвится именно по нему,
    # а не по окладу одного человека.
    assert facts["payroll"] == 800000
    assert facts["position_level"] == staffing_line.position.level


@pytest.mark.django_db
def test_facts_of_a_deleted_subject_are_empty_not_an_error():
    """Объект удалили между отправкой и запуском — условный маршрут откажет
    внятным «не сошлось ни одно условие», а не упадёт."""
    from apps.hr import approval_hooks

    assert approval_hooks._staffing_facts(10_000_000) == {}


@pytest.mark.django_db
def test_fact_fields_describe_every_fact(staffing_line):
    """Редактор маршрута предлагает поля из fact_fields; поле, которого нет
    в фактах, даст условие, падающее уже в руках пользователя."""
    from apps.hr import approval_hooks

    facts = approval_hooks._staffing_facts(staffing_line.id)
    declared = {f["key"] for f in approval_hooks._staffing_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_describe_names_the_subject_for_the_approver(staffing_line):
    from apps.hr import approval_hooks

    card = approval_hooks._describe_staffing(staffing_line.id)
    assert "Главный бухгалтер" in card["title"]
    assert card["url"].endswith(str(staffing_line.id))
    assert approval_hooks._describe_staffing(10_000_000) is None


# ── ручка «отправить на согласование» ────────────────────────────────────

@pytest.mark.django_db
def test_submit_requires_jwt(staffing_line):
    resp = Client().post(f"{BASE}/approvals/hr.staffing_position/{staffing_line.id}/submit")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_submit_without_a_route_is_409_and_says_so(staffing_line, auth):
    """Маршрута нет — это не поломка, а незаконченная настройка; человеку
    надо сказать словами, а не 500."""
    resp = Client().post(
        f"{BASE}/approvals/hr.staffing_position/{staffing_line.id}/submit", **auth)
    assert resp.status_code == 409
    assert "маршрут" in resp.json()["detail"].lower()


@pytest.mark.django_db
def test_submit_of_unknown_subject_type_is_404(staffing_line, auth):
    resp = Client().post(f"{BASE}/approvals/hr.no_such_thing/1/submit", **auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_submit_of_missing_object_is_404(auth):
    resp = Client().post(f"{BASE}/approvals/hr.staffing_position/10000000/submit", **auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_both_url_spellings_work(staffing_line, auth):
    for url in (f"{BASE}/approvals/hr.staffing_position/{staffing_line.id}/submit",
                f"{BASE}/approvals/hr.staffing_position/{staffing_line.id}/submit/"):
        assert Client().post(url, **auth).status_code != 404
```

⚠️ Фикстура `auth` объявлена ВНУТРИ `apps/hr/tests/test_positions_api.py` (обычный вошедший пользователь), а не в общем `conftest.py`. Скопируй её дословно в начало своего файла вместе с нужными импортами; не изобретай третий способ аутентификации в тестах.

⚠️ `signoff.registered_subjects()` **определена в `apps/signoff/interface.py`, но не перечислена в его `__all__`** (проверено контроллером). Пользоваться ей законно — граница аппки это модуль `interface`, а не список `__all__`, — но список обязан говорить правду о публичной поверхности. В этой же задаче добавь `"registered_subjects"` в `__all__` соседнего модуля ОДНОЙ строкой; это не правка движка (поведение не меняется), а приведение объявления в соответствие с тем, что в нём уже есть. Больше в `apps/signoff/**` не трогай НИЧЕГО — это чужая зона.

- [ ] **Step 2: Убедиться, что падает**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_approval_subjects.py -q`
Expected: ERROR/FAIL — у `StaffingPosition` нет `approval_state`, модуля `approval_hooks` нет.

- [ ] **Step 3: Примесь на модель**

`backend/apps/hr/models.py`. В шапку файла, рядом с прочими импортами:

```python
# Сосед — только через interface (apps/core/tests/test_app_isolation.py).
# Из signoff здесь берётся ровно один класс — абстрактная примесь.
from apps.signoff import interface as signoff
```

`StaffingPosition` начинает наследовать примесь; докстринг дополняется:

```python
class StaffingPosition(signoff.Approvable, HrBase):
    """Строка штатного расписания — порт models/staffing.py.

    Таблица — дефолтное имя Django: hr_staffingposition (не
    hr_staffing_positions исходника, решение D2). Оба FK исходник объявляет
    с явным ``index=True`` — дефолтное индексирование Django FK уже
    воспроизводит это без дополнительных пометок.

    Блок G: строка 2 матрицы полномочий HR-FRM-004 («Утверждение и
    изменение штатного расписания УК»). Согласуется СТРОКА, а не расписание
    целиком: контейнера «штатное расписание» в домене нет, а приказ на
    практике меняет конкретную позицию — добавить единицу, изменить оклад.
    Примесь добавляет колонку ``approval_state`` в ЭТУ таблицу; межаппного
    FK при этом не возникает.
    """
```

- [ ] **Step 4: Миграция**

Run: `../.venv/Scripts/python.exe manage.py makemigrations hr -n staffingposition_approval_state`
Expected: один `AddField` с `approval_state`. Докстринг файла:

```python
"""Expand-шаг: состояние согласования у строки штатного расписания (блок G).

``hr`` — тенантная аппка: миграция НЕ применяется стартом контейнера
(``migrate_shared``), схемы компаний доводит ``manage.py migrate_companies``
отдельным шагом выкатки.

Шаг чисто аддитивный: один столбец с ``db_default``, существующие строки
получают «черновик» без переписывания таблицы. ``StaffingPosition`` НЕ
входит в ``HOLDING_MODELS`` — сводное чтение заявок по группе не заказано.
"""
```

- [ ] **Step 5: Хуки**

`backend/apps/hr/approval_hooks.py`:

```python
"""Кадровые предметы согласования — блок G, матрица HR-FRM-004.

Здесь домен кадров ОБЪЯВЛЯЕТ свои объекты согласуемыми и отдаёт про них
три вещи: как назвать предмет согласующему (``describe``), какие факты он
несёт (``facts``) и какие из этих фактов можно предлагать в редакторе
маршрута (``fact_fields``). Сам движок, маршруты и виды согласующих — чужая
зона (``apps.signoff``), и этот файл её не касается.

Факты — главное в блоке. По ним маршрут ветвится, и roadmap §6.2 называет
три поимённо: сумма премии, срок отпуска, категория должности. Ключ факта —
часть контракта со вторым разработчиком: переименовать его молча значит
сломать условие в уже настроенном маршруте.

Устройство каждого предмета — тройка функций с общим соглашением:

* ``describe`` возвращает ``None``, если объект удалён: карточка процесса
  просто останется без заголовка, а не упадёт;
* ``facts`` возвращает ПУСТОЙ словарь по той же причине — условный маршрут
  честно откажет «не сошлось ни одно условие», безусловный отработает;
* ``fact_fields`` обязан описывать ровно те ключи, что отдаёт ``facts``:
  поле, которого на запуске не окажется, даст условие, падающее уже в руках
  пользователя (``register_subject`` это частично проверяет сам).

Образец — ``apps/contracts/approval_hooks.py``.
"""

from apps.hr.models import Department, Position, StaffingPosition
from apps.signoff import interface as signoff


# ── строка 2: штатное расписание ─────────────────────────────────────────

def _describe_staffing(subject_id: int) -> dict | None:
    line = (StaffingPosition.objects
            .select_related("position", "department")
            .filter(pk=subject_id).first())
    if line is None:
        return None
    return {
        "title": (f"Штатная единица: {line.position.title} — "
                  f"{line.department.name}, {line.headcount} ед., "
                  f"оклад {line.salary}"),
        "url": f"/hr/staffing/{line.pk}",
    }


def _staffing_facts(subject_id: int) -> dict:
    line = (StaffingPosition.objects
            .select_related("position")
            .filter(pk=subject_id).first())
    if line is None:
        return {}
    return {
        "department_id": line.department_id,
        "position_id": line.position_id,
        # Категория должности (roadmap §6.2) — уровень в иерархии: по нему
        # маршрут отличает специалиста от руководителя блока.
        "position_level": line.position.level,
        "headcount": line.headcount,
        "salary": line.salary,
        # «ФОТ — в пределах бюджета» (примечание документа к строке 2)
        # считается по строке целиком, а не по окладу одного человека.
        "payroll": line.salary * line.headcount,
    }


def _staffing_fact_fields() -> list[dict]:
    return [
        {"key": "department_id", "label": "Подразделение", "type": "choice",
         "options": _department_options()},
        {"key": "position_id", "label": "Должность", "type": "number"},
        {"key": "position_level", "label": "Уровень должности", "type": "number"},
        {"key": "headcount", "label": "Штатных единиц", "type": "number"},
        {"key": "salary", "label": "Оклад", "type": "number"},
        {"key": "payroll", "label": "ФОТ по строке", "type": "number"},
    ]


def _department_options() -> list[dict]:
    """Подразделения текущей компании для редактора условий.

    Читается на КАЖДЫЙ показ редактора, а не кэшируется: список меняется
    реорганизациями, и устаревший выбор здесь означает условие, указывающее
    на несуществующий отдел.
    """
    return [{"value": d.id, "label": d.name}
            for d in Department.objects.filter(is_active=True).order_by("path")]


# ── регистрация ──────────────────────────────────────────────────────────

def register() -> None:
    """Объявить кадровые объекты согласуемыми. Зовётся из HrConfig.ready().

    Явный вызов, а не автопоиск модулей: автопоиск — тот же межаппный
    импорт, только спрятанный от проверки границ. Здесь его видно и
    человеку, и грепу.
    """
    signoff.register_subject(
        StaffingPosition.SIGNOFF_SUBJECT_TYPE,
        label="Штатная единица",
        model=StaffingPosition,
        describe=_describe_staffing,
        facts=_staffing_facts,
        fact_fields=_staffing_fact_fields,
    )
```

Добавь `SIGNOFF_SUBJECT_TYPE = "hr.staffing_position"` в класс `StaffingPosition` (шаг 3).

- [ ] **Step 6: `HrConfig.ready()`**

`backend/apps/hr/apps.py`:

```python
    def ready(self):
        """Объявить кадровые объекты согласуемыми (блок G).

        Явный вызов, а не автопоиск: тот же приём и та же причина, что в
        ``apps/contracts/apps.py``. Импорт локальный — ``ready()`` вызывается
        после загрузки моделей, и импорт верхнего уровня их бы не дождался.
        """
        from . import approval_hooks

        approval_hooks.register()
```

⚠️ Если в `HrConfig` уже есть `ready()` (проверь перед правкой) — дописывай в него, а не заводи второй.

- [ ] **Step 7: Сервис отправки**

`backend/apps/hr/services/approval_service.py`:

```python
"""Отправка кадрового предмета на согласование — блок G.

Одна функция на все десять предметов, а не десять почти одинаковых: вся
разница между ними — какой класс достать по типу, и она выражается
таблицей, а не копией кода. Предметных проверок «можно ли отправлять» здесь
нет намеренно: у кадровых заявок нет собственного жизненного цикла вроде
«закрытый бюджет» — заявка либо существует, либо нет. Всё остальное
(повторная отправка, отсутствие маршрута, непригодный маршрут) отбивает сам
движок и отдаёт своими исключениями.
"""

from apps.signoff import interface as signoff


class SubjectNotFound(Exception):
    """404: такого предмета этого типа в текущей компании нет."""

    status = 404
    detail = "Объект не найден."


def _model_for(subject_type: str):
    """Класс предмета по его типу — или ``None`` для незнакомого типа.

    Таблица строится из реестра signoff, а не дублируется здесь: реестр уже
    знает соответствие, и вторая копия разъехалась бы с ним при добавлении
    предмета.
    """
    from apps.hr import approval_hooks

    return approval_hooks.SUBJECT_MODELS.get(subject_type)


def submit_for_approval(subject_type: str, subject_id: int, *,
                        actor_id: int | None = None) -> dict:
    """Запустить согласование предмета. Возвращает карточку процесса.

    Карточка процесса, а не предметный объект: после отправки человеку надо
    показать «на каком этапе и кто согласует», и это знает signoff.
    """
    model = _model_for(subject_type)
    if model is None:
        raise SubjectNotFound()
    if not model.objects.filter(pk=subject_id).exists():
        raise SubjectNotFound()
    return signoff.start_process(subject_type=subject_type, subject_id=subject_id,
                                 actor_id=actor_id)
```

В `approval_hooks.py` добавь таблицу и держи её единственным источником:

```python
#: Тип предмета → класс модели. Единственное место соответствия: и
#: register(), и approval_service берут его отсюда.
SUBJECT_MODELS: dict[str, type] = {
    StaffingPosition.SIGNOFF_SUBJECT_TYPE: StaffingPosition,
}
```

и перепиши `register()` так, чтобы он шёл по этой таблице — метаданные (label, describe, facts, fact_fields) держи во втором словаре `SUBJECT_SPECS`, чтобы добавление предмета было ОДНОЙ записью:

```python
#: Тип предмета → как его показывать и по каким фактам ветвить маршрут.
SUBJECT_SPECS: dict[str, dict] = {
    StaffingPosition.SIGNOFF_SUBJECT_TYPE: {
        "label": "Штатная единица",
        "describe": _describe_staffing,
        "facts": _staffing_facts,
        "fact_fields": _staffing_fact_fields,
    },
}


def register() -> None:
    """…докстринг из шага 5…"""
    for subject_type, model in SUBJECT_MODELS.items():
        signoff.register_subject(subject_type, model=model,
                                 **SUBJECT_SPECS[subject_type])
```

- [ ] **Step 8: Вьюха и роут**

`backend/apps/hr/views.py` — рядом с прочими ручками (стиль `hr` — функции с `api_view`, а не классы; посмотри соседние и повтори):

```python
# ── /approvals/{subject_type}/{id}/submit — отправка на согласование (блок G) ──

@api_view(methods=("POST",), auth="jwt", status=201)
def submit_subject(request, subject_type: str, subject_id: int):
    """Отправить кадровый предмет на согласование.

    Без ``admin=True``: заявку подаёт сотрудник или кадровик, а не
    платформенный администратор — тот же выбор и та же причина, что у
    ``SubmitView`` в apps/contracts. Кто её УТВЕРДИТ, решает маршрут.
    """
    try:
        return approval_svc.submit_for_approval(
            subject_type, subject_id, actor_id=request.token.user_id)
    except approval_svc.SubjectNotFound as exc:
        return json_error(exc.detail, exc.status)
    except signoff.RouteNotConfigured as exc:
        # Маршрута нет — незаконченная настройка, а не поломка.
        return json_error(str(exc), 409)
    except (signoff.AlreadyInApproval, signoff.RouteUnusable,
            signoff.SubjectLocked) as exc:
        return json_error(str(exc), 409)
```

⚠️ Проверь по `apps/signoff/interface.py`, КАКИЕ именно исключения экспортируются и какие тексты они несут; приведи ветки к реальному набору, а не к списку выше на веру. Если у исключения есть `.detail`, используй его вместо `str(exc)`.

`backend/apps/hr/urls.py` — обе формы пути (`APPEND_SLASH = False`):

```python
    # Отправка кадрового предмета на согласование (блок G). Тип предмета в
    # пути, а не в теле: он часть адреса ресурса, и по нему же роутится
    # реестр signoff.
    path("approvals/<str:subject_type>/<int:subject_id>/submit", views.submit_subject),
    path("approvals/<str:subject_type>/<int:subject_id>/submit/", views.submit_subject),
```

- [ ] **Step 9: Прогон**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_approval_subjects.py apps/core/tests/test_app_isolation.py -q`
Expected: все passed. Затем `../.venv/Scripts/python.exe -m pytest apps/signoff -q` — ожидается ровно 5 известных падений из `ci-known-failures.txt` и ни одного нового: регистрация нового субъекта не должна задеть движок.

- [ ] **Step 10: Коммит**

```bash
git add backend/apps/hr/models.py backend/apps/hr/migrations/0027_staffingposition_approval_state.py backend/apps/hr/approval_hooks.py backend/apps/hr/apps.py backend/apps/hr/services/approval_service.py backend/apps/hr/views.py backend/apps/hr/urls.py backend/apps/signoff/interface.py backend/apps/hr/tests/test_approval_subjects.py
git commit -m "feat(hr): штатное расписание согласуется — каркас кадровых предметов

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Кадровый приказ — приём, увольнение, назначение директора ДО (строки 5, 6, 7)

**Files:**
- Modify: `backend/apps/hr/models.py`
- Create: `backend/apps/hr/migrations/0028_personnelorder.py`
- Modify: `backend/apps/hr/approval_hooks.py`
- Test: `backend/apps/hr/tests/test_personnel_order.py`

**Interfaces:**
- Produces: `PersonnelOrder` с `SIGNOFF_SUBJECT_TYPE = "hr.personnel_order"`; `PersonnelOrderKind.{HIRE, DISMISS, TRANSFER}`; факты `kind`, `position_id`, `position_level`, `is_manager`, `target_company_slug`, `salary`, `effective_date`.

- [ ] **Step 1: Написать падающий тест**

`backend/apps/hr/tests/test_personnel_order.py`:

```python
"""Кадровый приказ — строки 5, 6, 7 матрицы HR-FRM-004.

Согласуется ПРИКАЗ, а не запись кадровой истории (решение заказчика 3):
история остаётся журналом того, что уже произошло, и её читателям —
карточке сотрудника, стажу, отчётам — не приходится знать про состояние
согласования. Запись в историю появляется РОВНО в момент утверждения.

Три строки матрицы — один тип предмета: приём специалиста, приём
руководителя блока и назначение директора дочернего общества различаются не
действием, а категорией должности и компанией. Именно это различие маршрут
и читает из фактов.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.hr.models import (
    Department, Employee, PersonnelHistory, PersonnelOrder, PersonnelOrderKind,
    Position,
)
from apps.signoff import interface as signoff


@pytest.fixture
def org(db):
    dep = Department.objects.create(name="Руководство", path="upr")
    lead = Position.objects.create(title="Операционный директор", department=dep,
                                   weight=130, level=2, is_manager=True)
    clerk = Position.objects.create(title="Менеджер по кадрам", department=dep,
                                    weight=660, level=4)
    return {"dep": dep, "lead": lead, "clerk": clerk}


def _order(org, **over):
    payload = {
        "kind": PersonnelOrderKind.HIRE,
        "position": org["clerk"],
        "department": org["dep"],
        "candidate_name": "Сейткали Айдана Нурлановна",
        "effective_date": dt.date(2026, 10, 1),
        "salary": 500000,
        "basis": "Приказ ГД",
    }
    payload.update(over)
    return PersonnelOrder.objects.create(**payload)


@pytest.mark.django_db
def test_order_is_approvable_and_registered(org):
    order = _order(org)
    assert order.approval_state == signoff.ApprovalState.DRAFT
    assert order.SIGNOFF_SUBJECT_TYPE == "hr.personnel_order"
    registered = {s["subject_type"] for s in signoff.registered_subjects()}
    assert "hr.personnel_order" in registered


@pytest.mark.django_db
def test_facts_tell_the_route_the_category_of_the_position(org):
    """Строки 5 и 6 матрицы различаются ровно этим: специалист или
    руководитель блока. Маршрут читает это из фактов, а не из типа."""
    from apps.hr import approval_hooks

    specialist = approval_hooks._personnel_order_facts(_order(org).id)
    chief = approval_hooks._personnel_order_facts(
        _order(org, position=org["lead"]).id)
    assert specialist["is_manager"] is False and specialist["position_level"] == 4
    assert chief["is_manager"] is True and chief["position_level"] == 2


@pytest.mark.django_db
def test_facts_carry_exactly_the_agreed_keys(org):
    from apps.hr import approval_hooks

    facts = approval_hooks._personnel_order_facts(_order(org).id)
    assert set(facts) == {"kind", "position_id", "position_level", "is_manager",
                          "target_company_slug", "salary", "effective_date"}
    declared = {f["key"] for f in approval_hooks._personnel_order_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_order_for_a_subsidiary_names_its_company(org):
    """Строка 7 — назначение директора ДО: решение принимает участник
    холдинга, а должность живёт в дочерней компании. Маршрут узнаёт об этом
    из факта, кросс-компанейский этап строит второй разработчик (§6.2)."""
    from apps.hr import approval_hooks

    order = _order(org, target_company_slug="hi-tech-systems")
    facts = approval_hooks._personnel_order_facts(order.id)
    assert facts["target_company_slug"] == "hi-tech-systems"
    assert approval_hooks._personnel_order_facts(_order(org).id)["target_company_slug"] is None


@pytest.mark.django_db
def test_approval_writes_the_history_entry(org):
    """Единственный автоматический эффект во всём блоке — и он заказан."""
    from apps.hr import approval_hooks

    employee = Employee.objects.create(
        first_name="Айдана", last_name="Сейткали", email="s.a@htq.kz",
        department=org["dep"], position=org["clerk"], hire_date="2024-01-09")
    order = _order(org, kind=PersonnelOrderKind.DISMISS, employee=employee,
                   candidate_name="")
    assert PersonnelHistory.objects.count() == 0

    approval_hooks._personnel_order_on_approved(order.id)

    entry = PersonnelHistory.objects.get()
    assert entry.employee_id == employee.id
    assert entry.event_type == "dismissed"
    assert entry.event_date == order.effective_date
    assert entry.order_number == order.basis


@pytest.mark.django_db
def test_approval_of_a_hire_without_an_employee_writes_nothing(org):
    """Приём нового человека: карточки сотрудника ещё нет, писать историю
    некому. Заводит сотрудника кадровик, глядя на утверждённый приказ —
    выдумывать за него карточку из имени строкой нельзя."""
    from apps.hr import approval_hooks

    order = _order(org)  # kind=hire, employee=None
    approval_hooks._personnel_order_on_approved(order.id)
    assert PersonnelHistory.objects.count() == 0


@pytest.mark.django_db
def test_approval_of_a_deleted_order_does_nothing(org):
    from apps.hr import approval_hooks

    approval_hooks._personnel_order_on_approved(10_000_000)
    assert PersonnelHistory.objects.count() == 0


@pytest.mark.django_db
def test_order_names_either_an_employee_or_a_candidate(org):
    """Приказ либо про существующего сотрудника, либо про кандидата по
    имени — пустой приказ ни о ком согласовывать нечего."""
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        _order(org, candidate_name="", employee=None)
```

- [ ] **Step 2: Убедиться, что падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_personnel_order.py -q` → ImportError.

- [ ] **Step 3: Модель**

`backend/apps/hr/models.py`, после `PersonnelHistory` (приказ и его след в журнале стоят рядом):

```python
class PersonnelOrderKind(models.TextChoices):
    HIRE = "hire", "Приём"
    DISMISS = "dismiss", "Увольнение"
    TRANSFER = "transfer", "Перевод"


class PersonnelOrder(signoff.Approvable, HrBase):
    """Кадровый приказ — строки 5, 6, 7 матрицы HR-FRM-004.

    Согласуется ПРИКАЗ, а не запись кадровой истории (решение заказчика
    16.09.2026): ``PersonnelHistory`` остаётся журналом состоявшегося, и её
    читателям — карточке сотрудника, стажу, отчётам — не нужно знать про
    состояние согласования. Запись в журнал появляется в момент утверждения
    (``approval_hooks._personnel_order_on_approved``).

    Три строки матрицы — один тип предмета. Приём специалиста (5), приём
    руководителя блока (6) и назначение директора дочернего общества (7)
    различаются не действием, а КАТЕГОРИЕЙ должности и компанией, и маршрут
    ветвится по фактам ``is_manager``/``position_level``/
    ``target_company_slug``. Три модели с одинаковыми полями лишили бы
    маршрут возможности сказать «для руководителей блоков — такой-то этап».

    ``employee`` и ``candidate_name`` — «или/или»: увольнение и перевод про
    существующего человека, приём — про того, чьей карточки ещё нет.
    Заводить карточку по приказу автоматически нельзя: имя строкой не
    содержит ни почты, ни даты рождения, ни документов, и «сотрудник,
    созданный из приказа» оказался бы наполовину пустым.

    ``target_company_slug`` пуст для приказов своей компании. Он не FK и не
    проверяется на существование: компании живут в ``public``, кадры — в
    схеме компании, и межаппных FK в платформе нет; резолвит его маршрут
    через ``companies.interface`` уже на своей стороне.
    """

    SIGNOFF_SUBJECT_TYPE = "hr.personnel_order"

    kind = models.CharField(
        max_length=16, choices=PersonnelOrderKind.choices,
        default=PersonnelOrderKind.HIRE, db_default=PersonnelOrderKind.HIRE.value,
        db_index=True,
    )
    employee = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.CASCADE,
        related_name="personnel_orders",
    )
    candidate_name = models.CharField(max_length=255, default="", db_default="")
    position = models.ForeignKey(
        Position, on_delete=models.PROTECT, related_name="personnel_orders",
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="personnel_orders",
    )
    target_company_slug = models.CharField(
        max_length=63, null=True, blank=True, db_index=True,
    )
    effective_date = models.DateField()
    salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, db_default=0)
    basis = models.CharField(max_length=255, default="", db_default="")
    comment = models.TextField(default="", db_default="")

    class Meta:
        verbose_name = "Кадровый приказ"
        verbose_name_plural = "Кадровые приказы"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(employee__isnull=False) | ~models.Q(candidate_name=""),
                name="ck_personnel_order_subject",
            ),
        ]

    def __str__(self) -> str:
        return f"<PersonnelOrder(id={self.id}, kind='{self.kind}', pos={self.position_id})>"
```

- [ ] **Step 4: Миграция**

Run: `../.venv/Scripts/python.exe manage.py makemigrations hr -n personnelorder` — докстринг по образцу задачи 1 (expand, тенантная аппка, не в `HOLDING_MODELS`).

- [ ] **Step 5: Хуки**

В `approval_hooks.py` — новая секция, плюс записи в обе таблицы:

```python
# ── строки 5, 6, 7: кадровый приказ ──────────────────────────────────────

_ORDER_EVENT = {
    PersonnelOrderKind.HIRE: PersonnelHistoryEventType.HIRED,
    PersonnelOrderKind.DISMISS: PersonnelHistoryEventType.DISMISSED,
    PersonnelOrderKind.TRANSFER: PersonnelHistoryEventType.TRANSFER,
}


def _describe_personnel_order(subject_id: int) -> dict | None:
    order = (PersonnelOrder.objects
             .select_related("position", "department", "employee")
             .filter(pk=subject_id).first())
    if order is None:
        return None
    who = (f"{order.employee.last_name} {order.employee.first_name}"
           if order.employee_id else order.candidate_name)
    return {
        "title": (f"{order.get_kind_display()}: {who} — {order.position.title}, "
                  f"{order.department.name}, с {order.effective_date.isoformat()}"),
        "url": f"/hr/orders/{order.pk}",
    }


def _personnel_order_facts(subject_id: int) -> dict:
    order = (PersonnelOrder.objects
             .select_related("position")
             .filter(pk=subject_id).first())
    if order is None:
        return {}
    return {
        "kind": order.kind,
        "position_id": order.position_id,
        # Категория должности (roadmap §6.2): уровень и признак руководителя
        # — то, чем строка 5 матрицы отличается от строки 6.
        "position_level": order.position.level,
        "is_manager": order.position.is_manager,
        # Пусто для своей компании. Строка 7 — назначение директора ДО.
        "target_company_slug": order.target_company_slug or None,
        "salary": order.salary,
        "effective_date": order.effective_date.isoformat(),
    }


def _personnel_order_fact_fields() -> list[dict]:
    return [
        {"key": "kind", "label": "Вид приказа", "type": "choice",
         "options": [{"value": v, "label": l} for v, l in PersonnelOrderKind.choices]},
        {"key": "position_id", "label": "Должность", "type": "number"},
        {"key": "position_level", "label": "Уровень должности", "type": "number"},
        {"key": "is_manager", "label": "Руководящая должность", "type": "boolean"},
        {"key": "target_company_slug", "label": "Компания назначения", "type": "string"},
        {"key": "salary", "label": "Оклад", "type": "number"},
        {"key": "effective_date", "label": "Дата вступления в силу", "type": "string"},
    ]


def _personnel_order_on_approved(subject_id: int) -> None:
    """Утверждённый приказ пишет запись в кадровую историю.

    Единственный автоматический эффект во всём блоке — и он заказан
    (решение заказчика 3). Приказ о приёме, у которого ещё нет карточки
    сотрудника, не пишет ничего: карточку заводит кадровик, глядя на
    утверждённый приказ.
    """
    order = PersonnelOrder.objects.filter(pk=subject_id).first()
    if order is None or order.employee_id is None:
        return
    PersonnelHistory.objects.create(
        employee_id=order.employee_id,
        event_type=_ORDER_EVENT.get(order.kind, PersonnelHistoryEventType.OTHER),
        event_date=order.effective_date,
        to_department_id=order.department_id,
        to_position_id=order.position_id,
        order_number=order.basis,
        comment=order.comment,
    )
```

Записи в таблицы:

```python
SUBJECT_MODELS = {
    …,
    PersonnelOrder.SIGNOFF_SUBJECT_TYPE: PersonnelOrder,
}

SUBJECT_SPECS = {
    …,
    PersonnelOrder.SIGNOFF_SUBJECT_TYPE: {
        "label": "Кадровый приказ",
        "describe": _describe_personnel_order,
        "facts": _personnel_order_facts,
        "fact_fields": _personnel_order_fact_fields,
        "on_approved": _personnel_order_on_approved,
    },
}
```

⚠️ `register()` из задачи 1 раскрывает спецификацию через `**`, поэтому `on_approved` доедет сам. Проверь по `register_subject`, что имя параметра совпадает.

- [ ] **Step 6: Прогон и коммит**

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_personnel_order.py apps/hr/tests/test_approval_subjects.py -q`

```bash
git add backend/apps/hr/models.py backend/apps/hr/migrations/0028_personnelorder.py backend/apps/hr/approval_hooks.py backend/apps/hr/tests/test_personnel_order.py
git commit -m "feat(hr): кадровый приказ согласуется и пишет историю при утверждении

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Премия и дисциплинарное взыскание (строки 8, 9)

**Files:** `models.py`, `migrations/0029_bonus_reprimand.py`, `approval_hooks.py`, `tests/test_bonus_reprimand.py`

**Interfaces:** `Bonus` (`hr.bonus`), `Reprimand` (`hr.reprimand`). Факты премии: `employee_id`, `department_id`, `position_level`, `amount`, `period`, `kind`. Факты взыскания: `employee_id`, `department_id`, `position_level`, `severity`, `event_date`.

- [ ] **Step 1: Тест**

`backend/apps/hr/tests/test_bonus_reprimand.py` — по образцу задачи 2. Обязательные проверки:
- оба предмета согласуемы и зарегистрированы под своими типами;
- набор ключей фактов пинится ТОЧНЫМ сравнением, и `fact_fields` описывает ровно их;
- **сумма премии присутствует в фактах** — roadmap §6.2 называет её поимённо; тест на то, что `facts["amount"]` равен сумме модели;
- премия с нулевой суммой отвергается на уровне БД (`CheckConstraint amount > 0`): «премия на 0 ₸» — это ошибка ввода, а не решение;
- у взыскания степень (`severity`) входит в факты, и маршрут по ней ветвится — тест на два разных значения;
- факты удалённого объекта — пустой словарь, `describe` — `None`;
- ни у одного из двух предметов НЕТ `on_approved` (решение 11): проверь, что в `SUBJECT_SPECS` для них этого ключа нет.

- [ ] **Step 2: Убедиться, что падает.** Run: тот же файл, ожидается ImportError.

- [ ] **Step 3: Модели**

```python
class BonusKind(models.TextChoices):
    KPI = "kpi", "По KPI"
    ONE_TIME = "one_time", "Разовая"
    ANNUAL = "annual", "Годовая"


class Bonus(signoff.Approvable, HrBase):
    """Премирование работника — строка 8 матрицы HR-FRM-004.

    Примечание документа: «По KPI и Положению о премировании» — отсюда
    ``kind`` и ``basis``: маршрут отличает премию по KPI от разовой, а
    ссылка на положение хранится рядом с суммой.

    Сумма — главный факт этого предмета (roadmap §6.2 называет её первой из
    трёх), поэтому она обязательна и строго положительна: «премия на 0 ₸» —
    ошибка ввода, а не решение, и согласовывать её нечего.
    """

    SIGNOFF_SUBJECT_TYPE = "hr.bonus"

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="bonuses")
    kind = models.CharField(
        max_length=16, choices=BonusKind.choices,
        default=BonusKind.ONE_TIME, db_default=BonusKind.ONE_TIME.value)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    period = models.CharField(max_length=32, default="", db_default="")
    basis = models.CharField(max_length=255, default="", db_default="")
    comment = models.TextField(default="", db_default="")

    class Meta:
        verbose_name = "Премия"
        verbose_name_plural = "Премии"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0),
                                   name="ck_bonus_amount_positive"),
        ]

    def __str__(self) -> str:
        return f"<Bonus(id={self.id}, employee_id={self.employee_id}, amount={self.amount})>"


class ReprimandSeverity(models.TextChoices):
    REMARK = "remark", "Замечание"
    REPRIMAND = "reprimand", "Выговор"
    SEVERE = "severe", "Строгий выговор"


class Reprimand(signoff.Approvable, HrBase):
    """Дисциплинарное взыскание — строка 9 матрицы HR-FRM-004.

    ``severity`` — не украшение: маршрут по нему ветвится (замечание и
    строгий выговор проходят разный круг согласования), и это тот самый
    случай, ради которого у предмета вообще есть факты.

    Автоматических последствий у утверждения нет (решение 11 плана блока G):
    взыскание объявляет приказ, а не платформа.
    """

    SIGNOFF_SUBJECT_TYPE = "hr.reprimand"

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="reprimands")
    severity = models.CharField(
        max_length=16, choices=ReprimandSeverity.choices,
        default=ReprimandSeverity.REMARK, db_default=ReprimandSeverity.REMARK.value,
        db_index=True)
    event_date = models.DateField()
    reason = models.TextField()
    basis = models.CharField(max_length=255, default="", db_default="")

    class Meta:
        verbose_name = "Дисциплинарное взыскание"
        verbose_name_plural = "Дисциплинарные взыскания"

    def __str__(self) -> str:
        return f"<Reprimand(id={self.id}, employee_id={self.employee_id}, severity='{self.severity}')>"
```

- [ ] **Step 4: Миграция** — `makemigrations hr -n bonus_reprimand`, докстринг по образцу задачи 1.

- [ ] **Step 5: Хуки.** Две секции по образцу задачи 2. Ключи фактов — ровно те, что в «Interfaces» выше. `position_level` берётся из `employee.position.level` (сотрудник у обоих предметов обязателен). Записи в `SUBJECT_MODELS`/`SUBJECT_SPECS`; **без `on_approved`**.

- [ ] **Step 6: Прогон и коммит.**

```bash
git commit -m "feat(hr): премия и дисциплинарное взыскание согласуются

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Отпуск и командировка (строка 10, части б и в)

**Files:** `models.py`, `migrations/0030_leaverequest_businesstrip.py`, `approval_hooks.py`, `htqweb/date_rules.py`, `tests/test_leave_and_trip.py`

**Interfaces:** `LeaveRequest` (`hr.leave_request`), `BusinessTrip` (`hr.business_trip`). Факты отпуска: `employee_id`, `department_id`, `kind`, `days`, `date_from`, `date_to`. Факты командировки: `employee_id`, `department_id`, `destination`, `country`, `days`, `estimated_cost`, `date_from`, `date_to`.

⚠️ **Здесь впервые в блоке появляются ПАРЫ ДАТ.** Платформенное правило (`htqweb/date_rules.py`) обязательно: пара в `DATE_PAIRS`, схемы наследуют `OrderedDates`, сервис зовёт `assert_instance_ordered` перед `save()`, вьюха переводит `DatesOutOfOrder` в 422, ограничение БД называется `ck_<модель>_dates` (иначе сторож `test_invariants.py::test_date_pairs_table_matches_the_database_constraints` его не увидит — на этом уже обожглись в блоке E). Обе модели используют ОДНУ пару имён `date_from`/`date_to` — значит в `DATE_PAIRS` добавляется одна строка на обе.

- [ ] **Step 1: Тест.** Обязательные проверки:
- оба предмета согласуемы и зарегистрированы;
- наборы ключей фактов пинятся точно; `fact_fields` описывает ровно их;
- **срок отпуска в фактах** (roadmap §6.2 называет его вторым из трёх): `days` считается как `(date_to - date_from).days + 1` — границы включительные, отпуск с 1 по 1 число это один день, а не ноль; отдельный тест ровно на этот случай;
- **сумма командировки в фактах** — по ней ветвится маршрут;
- перевёрнутый период отвергается: на уровне БД (`ck_leaverequest_dates`, `ck_businesstrip_dates`) и на уровне платформенного правила дат;
- пара `date_from`/`date_to` есть в `DATE_PAIRS`, и сторож `test_invariants` зелёный;
- факты удалённого объекта пусты.

- [ ] **Step 2: Убедиться, что падает.**

- [ ] **Step 3: Модели.** `LeaveRequest`: `employee`, `kind` (`LeaveKind`: `annual` «Ежегодный оплачиваемый», `unpaid` «Без содержания», `sick` «По болезни», `study` «Учебный», `parental` «По уходу за ребёнком»), `date_from`, `date_to`, `basis`, `comment`. `BusinessTrip`: `employee`, `destination` (город), `country` (двухбуквенный код, пусто = своя страна), `purpose`, `date_from`, `date_to`, `estimated_cost`, `basis`. У обеих — `CheckConstraint(date_to >= date_from, name="ck_<модель>_dates")`. Докстринги объясняют: что согласуется, почему включительные границы, и что предмет не трогает календарь и табель (решение 11 — автоматических эффектов нет; проставляет отсутствие кадровик после утверждения).

- [ ] **Step 4: Правило дат.** В `htqweb/date_rules.py::DATE_PAIRS` добавить `("date_from", "date_to", MESSAGE)`. Прогнать `apps/core/tests/test_invariants.py` — оба сторожа дат обязаны быть зелёными.

- [ ] **Step 5: Миграция** — `makemigrations hr -n leaverequest_businesstrip`.

- [ ] **Step 6: Хуки.** Две секции. `days` считается в `facts`, а не хранится: хранимое поле разъехалось бы с датами при первой же правке.

- [ ] **Step 7: Прогон и коммит.**

```bash
git commit -m "feat(hr): заявление на отпуск и командировка согласуются

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Годовой график отпусков (строка 10, часть а)

**Files:** `models.py`, `migrations/0031_vacationschedule.py`, `approval_hooks.py`, `tests/test_vacation_schedule.py`

**Interfaces:** `VacationSchedule` (`hr.vacation_schedule`) + `VacationScheduleLine`. Факты: `year`, `lines_count`, `employees_count`, `total_days`.

- [ ] **Step 1: Тест.** Обязательные проверки:
- график согласуется ЦЕЛИКОМ, строки отдельно не отправляются — у `VacationScheduleLine` нет `SIGNOFF_SUBJECT_TYPE` и она не в `SUBJECT_MODELS`;
- факты считают по строкам: число строк, число разных сотрудников, суммарное число дней;
- **пустой график отправить нельзя** — `describe` показывает «0 строк», а факты дают `lines_count = 0`, и тест фиксирует это как состояние, на которое маршрут вправе не сойтись (предметной проверки в сервисе не вводим — решение: у кадровых заявок нет собственного жизненного цикла, см. докстринг `approval_service`);
- год уникален (`UniqueConstraint(year)`): двух графиков на один год не бывает;
- строка графика ссылается на сотрудника и несёт период; перевёрнутый период отвергается;
- факты удалённого графика пусты.

- [ ] **Step 2: Убедиться, что падает.**

- [ ] **Step 3: Модели.**

```python
class VacationSchedule(signoff.Approvable, HrBase):
    """Годовой график отпусков — строка 10 матрицы HR-FRM-004.

    Согласуется ЦЕЛИКОМ: график утверждают раз в год на всю компанию, и
    согласовать половину графика нельзя — в этом и смысл контейнера. Строки
    (``VacationScheduleLine``) поэтому НЕ являются предметом согласования и
    в реестре не регистрируются.

    Отдельное заявление на отпуск (``LeaveRequest``) — другой предмет с
    другим маршрутом: график планирует год вперёд, заявление отпускает
    человека на конкретные даты. Документ соединяет их в одной строке, но
    это две разные процедуры (решение заказчика 2).
    """

    SIGNOFF_SUBJECT_TYPE = "hr.vacation_schedule"

    year = models.IntegerField(unique=True)
    basis = models.CharField(max_length=255, default="", db_default="")
    comment = models.TextField(default="", db_default="")
```

`VacationScheduleLine`: `schedule` (FK, `related_name="lines"`, CASCADE), `employee` (PROTECT), `date_from`, `date_to`, `days` не хранится. Ограничение `ck_vacationscheduleline_dates`.

- [ ] **Step 4: Миграция, хуки, прогон, коммит** — по образцу предыдущих задач.

```bash
git commit -m "feat(hr): годовой график отпусков согласуется целиком

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Локальные нормативные акты и должностные инструкции (строки 3, 4)

**Files:** `models.py`, `migrations/0032_policy_jobdescription.py`, `approval_hooks.py`, `tests/test_policy_job_description.py`

**Interfaces:** `Policy` (`hr.policy`), `JobDescription` (`hr.job_description`). Факты политики: `kind`, `version`, `effective_from`. Факты инструкции: `position_id`, `position_level`, `department_id`, `version`, `effective_from`.

- [ ] **Step 1: Тест.** Обязательные проверки:
- оба предмета согласуемы и зарегистрированы;
- наборы фактов пинятся точно; `fact_fields` описывает ровно их;
- **должностная инструкция привязана к должности**, и её уровень попадает в факты — строка 4 согласуется по-разному для разных категорий;
- версия обязательна и уникальна в паре с предметом (`UniqueConstraint(position, version)` у инструкции, `UniqueConstraint(kind, version)` у политики): «вторая версия 1.0» — ошибка ввода;
- факты удалённого объекта пусты.

- [ ] **Step 2: Убедиться, что падает.**

- [ ] **Step 3: Модели.**

```python
class PolicyKind(models.TextChoices):
    REGULATION = "regulation", "Положение"
    POLICY = "policy", "Политика"
    INSTRUCTION = "instruction", "Инструкция"
    ORDER = "order", "Приказ"


class Policy(signoff.Approvable, HrBase):
    """Локальный нормативный акт — строка 3 матрицы HR-FRM-004.

    Своя модель, а не ``Document``: тот привязан к СОТРУДНИКУ
    (``Document.employee``), а политика компании ничьей карточке не
    принадлежит. Переиспользовать его значило бы завести «документ ничей» и
    сломать смысл поля.

    Примечание документа к строке 3 — «Юр. экспертиза — юрконсультант»:
    это этап маршрута, а не поле модели; здесь он не отражается ничем, и
    это правильно — состав согласующих настраивается, а не зашивается.
    """

    SIGNOFF_SUBJECT_TYPE = "hr.policy"

    kind = models.CharField(max_length=16, choices=PolicyKind.choices,
                            default=PolicyKind.POLICY, db_default=PolicyKind.POLICY.value)
    title = models.CharField(max_length=255)
    version = models.CharField(max_length=32)
    effective_from = models.DateField()
    file_key = models.CharField(max_length=500, default="", db_default="")
    comment = models.TextField(default="", db_default="")

    class Meta:
        verbose_name = "Локальный нормативный акт"
        verbose_name_plural = "Локальные нормативные акты"
        constraints = [
            models.UniqueConstraint(fields=["kind", "version"], name="uq_policy_version"),
        ]


class JobDescription(signoff.Approvable, HrBase):
    """Должностная инструкция — строка 4 матрицы HR-FRM-004.

    Своя модель, а не поле ``Position.description``: инструкция
    утверждается ВЕРСИЯМИ и живёт своей историей, а описание должности —
    редактируемый текст карточки, который правят когда угодно и без
    согласования.
    """

    SIGNOFF_SUBJECT_TYPE = "hr.job_description"

    position = models.ForeignKey(
        Position, on_delete=models.CASCADE, related_name="job_descriptions")
    version = models.CharField(max_length=32)
    effective_from = models.DateField()
    body = models.TextField(default="", db_default="")
    file_key = models.CharField(max_length=500, default="", db_default="")

    class Meta:
        verbose_name = "Должностная инструкция"
        verbose_name_plural = "Должностные инструкции"
        constraints = [
            models.UniqueConstraint(fields=["position", "version"],
                                    name="uq_job_description_version"),
        ]
```

- [ ] **Step 4: Миграция, хуки, прогон, коммит.**

```bash
git commit -m "feat(hr): локальные нормативные акты и должностные инструкции согласуются

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Изменение оргструктуры (строка 1)

**Files:** `models.py`, `migrations/0033_orgchangerequest.py`, `approval_hooks.py`, `tests/test_org_change_request.py`

**Interfaces:** `OrgChangeRequest` (`hr.org_change`). Факты: `kind`, `department_id`, `effective_date`, `headcount_delta`.

- [ ] **Step 1: Тест.** Обязательные проверки:
- предмет согласуем и зарегистрирован;
- набор фактов пинится точно; `fact_fields` описывает ровно их;
- `headcount_delta` может быть отрицательным (сокращение) и попадает в факты как есть — маршрут вправе развести «добавить единицу» и «сократить»;
- **утверждение НИЧЕГО не меняет в дереве оргструктуры** — тест на то, что после `on_approved`… которого нет: в `SUBJECT_SPECS` для этого предмета ключа `on_approved` быть не должно, и тест это фиксирует прямо (это решение 6, и молча потерять его нельзя);
- факты удалённого объекта пусты.

- [ ] **Step 2: Убедиться, что падает.**

- [ ] **Step 3: Модель.**

```python
class OrgChangeKind(models.TextChoices):
    CREATE_UNIT = "create_unit", "Создать подразделение"
    RENAME_UNIT = "rename_unit", "Переименовать подразделение"
    MOVE_UNIT = "move_unit", "Перенести подразделение"
    CLOSE_UNIT = "close_unit", "Закрыть подразделение"
    CREATE_POSITION = "create_position", "Ввести должность"
    CLOSE_POSITION = "close_position", "Сократить должность"
    OTHER = "other", "Другое"


class OrgChangeRequest(signoff.Approvable, HrBase):
    """Заявка на изменение оргструктуры — строка 1 матрицы HR-FRM-004.

    Согласовать «дерево» нельзя: у дерева нет ни версии, ни момента. Эта
    модель — приказ: что меняем, с какой даты, кто инициатор, чем
    обосновано. После утверждения изменение вносит кадровик руками, и
    автоматического применения тут нет намеренно (решение 6 плана блока G):
    применение диффа оргструктуры — отдельный крупный проект, а
    «полуавтомат», молча правящий дерево по текстовому описанию, опаснее
    ручной работы.

    ``description`` — что именно меняется, словами. Это не слабость модели,
    а её честная граница: поля, достаточного для машинного применения
    любого из семи видов изменений, не существует.
    """

    SIGNOFF_SUBJECT_TYPE = "hr.org_change"

    kind = models.CharField(max_length=20, choices=OrgChangeKind.choices,
                            default=OrgChangeKind.OTHER, db_default=OrgChangeKind.OTHER.value)
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="org_change_requests")
    description = models.TextField()
    headcount_delta = models.IntegerField(default=0, db_default=0)
    effective_date = models.DateField()
    basis = models.CharField(max_length=255, default="", db_default="")
```

- [ ] **Step 4: Миграция, хуки, прогон, коммит.**

```bash
git commit -m "feat(hr): заявка на изменение оргструктуры согласуется

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Сводка для второго разработчика, сквозная проверка, документы

**Files:** `docs/plans/2026-09-14-group-structure-roadmap.md` (§4, §5.G, §6.2, §6.4, §7), `API.md`, `STRUCTURE.md`, `CLAUDE.md`, `backend/apps/hr/tests/test_approval_subjects.py` (сводный сторож)

- [ ] **Step 1: Сводный сторож.** Добавить в `test_approval_subjects.py` тест, который держит ВЕСЬ список предметов и их фактов:

```python
@pytest.mark.django_db
def test_every_matrix_row_has_its_subject_and_facts():
    """Контракт со вторым разработчиком (roadmap §6.4): список типов и
    ключей фактов. Он уезжает в чужой код маршрутами и условиями —
    переименовать ключ молча значит сломать настроенный маршрут.
    """
    from apps.hr import approval_hooks

    expected = {
        "hr.org_change": {"kind", "department_id", "effective_date", "headcount_delta"},
        "hr.staffing_position": {"department_id", "position_id", "position_level",
                                 "headcount", "salary", "payroll"},
        "hr.policy": {"kind", "version", "effective_from"},
        "hr.job_description": {"position_id", "position_level", "department_id",
                               "version", "effective_from"},
        "hr.personnel_order": {"kind", "position_id", "position_level", "is_manager",
                               "target_company_slug", "salary", "effective_date"},
        "hr.bonus": {"employee_id", "department_id", "position_level", "amount",
                     "period", "kind"},
        "hr.reprimand": {"employee_id", "department_id", "position_level",
                         "severity", "event_date"},
        "hr.vacation_schedule": {"year", "lines_count", "employees_count", "total_days"},
        "hr.leave_request": {"employee_id", "department_id", "kind", "days",
                             "date_from", "date_to"},
        "hr.business_trip": {"employee_id", "department_id", "destination", "country",
                             "days", "estimated_cost", "date_from", "date_to"},
    }
    assert set(approval_hooks.SUBJECT_MODELS) == set(expected)
    for subject_type, keys in expected.items():
        declared = {f["key"] for f in approval_hooks.SUBJECT_SPECS[subject_type]["fact_fields"]()}
        assert declared == keys, subject_type


@pytest.mark.django_db
def test_only_the_personnel_order_has_an_automatic_effect():
    """Решение 11: единственный автоматический эффект во всём блоке —
    запись в кадровую историю при утверждении приказа. Появление второго
    обязано быть осознанным, а не случайным."""
    from apps.hr import approval_hooks

    with_effects = {t for t, spec in approval_hooks.SUBJECT_SPECS.items()
                    if {"on_approved", "on_rejected", "on_rework",
                        "on_started", "on_cancelled"} & set(spec)}
    assert with_effects == {"hr.personnel_order"}
```

- [ ] **Step 2: Прогоны (гонит КОНТРОЛЛЕР).** Полный сьют — ожидается ровно 8 известных падений. Отдельно `apps/signoff` — ровно 5 известных: движок не должен пострадать от десяти новых субъектов.

- [ ] **Step 3: Сквозной прогон на dev-базе.** `migrate_companies --company hi-tech-group`; затем через Bash (не PowerShell) проверить, что в схеме холдинга появились таблицы `hr_personnelorder`, `hr_bonus`, `hr_reprimand`, `hr_leaverequest`, `hr_businesstrip`, `hr_vacationschedule`, `hr_vacationscheduleline`, `hr_policy`, `hr_jobdescription`, а у `hr_staffingposition` — столбец `approval_state`.

- [ ] **Step 4: Документы.**

Roadmap §4 — строка «Матрица полномочий»: «✅ десять кадровых предметов согласования (`hr.*`), факты для условий; финансовые строки 11–15 — зона contracts». §5.G — «(выполнено)» + перечень десяти типов. §6.2 — пункт «Принять субъекты `hr.*` … и согласовать `subject_facts`» отметить как выполненный с моей стороны: субъекты зарегистрированы, факты объявлены, список в §6.4. **§6.4 — заменить строку «список `hr.*` subject-типов и их фактов (после блока G)» на саму таблицу**: десять типов, их `label` и ключи фактов, с пометкой, что список закреплён тестом и менять его в одиночку нельзя. §7 — шаг про `migrate_companies` дополнить номерами `hr/0027`–`0033`.

`API.md` — ручка `POST /api/hr/v1/approvals/{subject_type}/{id}/submit` с правами (JWT, без админа).

`STRUCTURE.md` — `approval_hooks.py` и `services/approval_service.py` одной строкой в составе `apps/hr`.

`CLAUDE.md`, в раздел «Мультикомпанейность» после абзаца об ОСУ:

«**Кадровые решения согласуются движком signoff.** Десять предметов `hr.*` (матрица HR-FRM-004, строки 1–10) объявлены в `apps/hr/approval_hooks.py` и регистрируются из `HrConfig.ready()` — тем же приёмом, что в `apps.contracts`. Каждый несёт ФАКТЫ, по которым ветвится маршрут: сумма премии, срок отпуска, категория должности (`position_level`, `is_manager`). Набор ключей фактов — контракт со вторым разработчиком, закреплён тестом `test_every_matrix_row_has_its_subject_and_facts`; переименование ключа ломает настроенный маршрут. Единственный автоматический эффект утверждения во всём блоке — кадровый приказ пишет запись в `PersonnelHistory`; остальные девять предметов просто становятся утверждёнными.»

- [ ] **Step 5: Коммит.**

```bash
git commit -m "docs: блок G закрыт — десять кадровых предметов согласования

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Что осталось за рамками (названо заранее)

- **Экранов нет.** Блок даёт модели, регистрацию и ручку отправки; формы заведения заявок (премия, отпуск, приказ) — отдельная работа, и её объём сопоставим с этим блоком.
- **Маршруты не настраиваются.** Кто согласует каждую строку матрицы — данные, которые заводит второй разработчик через редактор маршрутов, опираясь на §6.4 и на `hr.participant_position()` (блок F) и `hr.substitutes_for()` (блок E).
- **Кросс-компанейский этап строки 7** (назначение директора ДО) — `ApprovalRouteStageRole.company_slug`, зона второго разработчика (§6.2). Блок G лишь кладёт `target_company_slug` в факты.
- **Применение изменения оргструктуры** после утверждения (решение 6) и **проставление отсутствий** в календаре после утверждения отпуска (решение 11) — оба намеренно ручные.
- **Строка 6 матрицы без инициатора** — открытый вопрос руководству (§8.4), на модель не влияет.

## Self-review

**Покрытие спеки.** §5.G просил пять предметов, регистрацию в `HrConfig.ready()`, ручки через `apps.signoff.interface` и «движок не трогаю» — всё это есть в задачах 1–8; предметов десять по решению заказчика от 16.09.2026. §6.2 просит факты «сумма премии, срок отпуска, категория должности» — `hr.bonus.amount` (задача 3), `hr.leave_request.days` (задача 4), `position_level`/`is_manager` (задачи 1, 2, 3, 6). §6.4 просит список типов и фактов — задача 8 кладёт его в roadmap и закрепляет тестом.

**Заглушек нет:** код моделей и хуков для задач 1–3, 6, 7 приведён целиком; в задачах 4 и 5 модели описаны полями и ограничениями поимённо, а хуки — точным перечнем ключей фактов, потому что их форма полностью задана образцом задачи 2 и списком «Interfaces». Тесты задач 3–7 заданы списком обязательных проверок, а не кодом: их шаблон — файл задачи 1, и копия того же кода в плане семь раз устарела бы раньше, чем её прочтут.

**Согласованность имён:** `SUBJECT_MODELS`/`SUBJECT_SPECS` (задача 1 → все); `approval_service.submit_for_approval`/`SubjectNotFound` (1 → 8); `SIGNOFF_SUBJECT_TYPE` строки `hr.*` совпадают между моделями, таблицами и сводным тестом задачи 8; `date_from`/`date_to` — одна пара имён на `LeaveRequest`, `BusinessTrip` и `VacationScheduleLine`, поэтому в `DATE_PAIRS` одна строка.

**Риски, названные заранее:** семь миграций подряд по тенантной аппке — каждая expand, но выкатка требует одного `migrate_companies` на все; девять новых таблиц в схеме КАЖДОЙ компании; правка `htqweb/date_rules.py` (общий фундамент) затрагивает сторож `test_invariants` — проверять его после задачи 4; `HrConfig.ready()` выполняется при каждом старте, и ошибка в `register()` уронит аппку целиком — поэтому регистрация идёт по таблице, а не десятью ручными вызовами.
