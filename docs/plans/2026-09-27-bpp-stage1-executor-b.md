# БЗО, этап 1 — исполнитель B (Руслан, ветка `new-module-BPP-ruslan`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Довести движок согласования до правил ТЗ §16:
- временный исполнитель должности;
- флаги маршрута: запрет самосогласования, комментарий при отказе, ленивое разрешение исполнителей, «Нет исполнителя»;
- массовые решения и «Сейчас у»;
- очередь «ждёт меня» для ежедневной сводки;
- выбор варианта и предсогласованные этапы.

При этом ничего не меняется для маршрутов, где флаги выключены: кадровые `hr.*`, заявки `approvals`, договоры `contracts`.

**Architecture:**
- **Флаги** хранятся на маршруте (`ApprovalRoute`). На запуске они снимком копируются в процесс (`ApprovalProcess.route_flags`) — как этапы. Выключены по умолчанию (D-21).
- **Временный исполнитель** — строка в `hr`. Движок получает его через `hr.interface.resolve_position_users(..., on_date=…)`: исполнитель просто входит в держатели должности на период.
- **Ленивое разрешение.** Исполнители этапа находятся при его активации, а не на запуске. Этап без исполнителя получает состояние «Нет исполнителя», ждёт и перепроверяется Celery каждые 15 минут.

**Tech Stack:** Django 5.2.7, PostgreSQL (схема на компанию), Celery + django-celery-beat, pytest-django (Postgres на `:55432`), React + TypeScript + vitest.

**Spec:** [мастер-план](2026-09-26-bpp-master-plan.md): §1 (D-12, D-21, D-22, D-23, D-26), §2.6 (контракты signoff и hr), §5 «Этап 1» (B1.1–B1.3); ТЗ [§16](../tz/TZ-budget-procurement-payments-v1.0.md) (маршруты), BR-060, BR-061.

**Как задачи этого плана соотносятся с мастер-планом:**

| Мастер-план | Этот план |
|---|---|
| B1.1 | задача 1 |
| B1.2 | задачи 2, 3, 4, 5 |
| B1.3 | задачи 6, 7 |

**Ветки и синхронизация.** Работа идёт в `new-module-BPP-ruslan`, поверх этапа 0 B (строковый `subject_id`). Ветки мерджит пользователь, до этого A и B друг к другу не мерджат. Поэтому:
- ошибки движка — свои исключения signoff (`htqweb.errors.DomainError` появляется в ветке A);
- уведомления — прежний `_notify` через мессенджер; переход на центр уведомлений — задача этапа 2 после мерджа;
- очередь «ждёт меня» регистрируется источником ежедневной сводки, только если аппка `apps.notifications` установлена (задача 6): в ветке B её нет, после мерджа связь включится сама.

**Изменения signoff** B присылает A на подтверждение до мерджа (мастер-план §0, правило 3).

⚠️ **Правка маршрутов ролями ФД и АДМ (В-09) в этап не входит.** Сейчас ручки маршрутов signoff стоят под `admin=True`. Перевод signoff под гейт модуля — отдельная задача, её нужно согласовать с A: это меняет `apps/access/tests/test_gate.py::_OUT_OF_SCOPE_APPS`. До неё маршруты БЗО настраивает администратор.

---

## Global Constraints

- Интерпретатор — корневой `.venv`. Backend-команды — из `backend/`: `../.venv/Scripts/python.exe -m pytest …`. Postgres: `docker compose -f docker-compose.test-local.yml up -d db`. Одновременно — один прогон pytest на машине.
- Ветки не создавать. Коммитить только файлы своей задачи.
- Межаппный доступ — только `apps.<x>.interface`. Первая строка каждой функции `interface.py` и Celery-задачи — `require_service("<сервис>")`; задачи тенантной аппки — `@company_task` / `@company_dispatch_task`.
- signoff и hr — тенантные. Миграции применяются к схемам компаний через `manage.py migrate_companies`. Изменения схемы — только добавление (expand): столбцы с `default`/`db_default`, без переименований.
- **Поведение маршрута без флагов не меняется.** Весь текущий набор тестов signoff, approvals, contracts и hr остаётся зелёным без правок.
- Комментарий при «Отклонить» и «Вернуть» — не короче `reject_comment_min` символов (у маршрутов БЗО — 10, BR-060). Текст ошибки — «Опишите причину: комментарий не короче N символов».
- «Сегодня» в `hr` — `django.utils.timezone.localdate()` (сторож `apps/core/tests/test_platform_today.py`).
- Новые строки фронта — `t('<ключ>', 'Русский текст')`, переводы не добавлять. Typecheck — `npx tsc --noEmit -p tsconfig.app.json`, сравнивать число ошибок до и после.

## Review Focus

1. **Маршрут без флагов.** Старые маршруты `hr.*`, `approvals.request`, `contracts.*` запускаются и проходят как раньше: исполнители разрешаются на запуске, отсутствие исполнителя — 409 при отправке. Тест — задача 2 (`test_route_without_flags_behaves_as_before`) плюс весь существующий набор signoff.
2. **Автор — единственный держатель должности этапа.** ТД — автор заявки, других ТД нет, временного исполнителя нет. Этап уходит ГД; а если автор — сам ГД, этап пропускается с записью и уведомлением ФД, и процесс не зависает. Тест — задача 3 (`test_author_alone_on_stage_goes_to_fallback`, `test_general_director_author_skips_stage`).
3. **Первый этап сразу без исполнителя.** Процесс создаётся, документ «На согласовании», этап «Нет исполнителя», эскалация уведомлена. Назначили временного исполнителя — через проверку задача появилась у него. Тест — задача 4 (`test_first_stage_without_executor_waits_and_recovers`).
4. **Временный исполнитель вне периода.** Назначение на 1–10 октября: 11 октября его уже нет в разрешении должности, а прошлые задачи не переписываются. Тест — задача 1 (`test_acting_only_inside_period`).
5. **Массовое решение с частичным отказом.** Из трёх задач одна чужая: две решены, по третьей — ошибка с причиной, решения первых двух не откатываются. Тест — задача 6 (`test_decide_many_keeps_successes`).

---

## Task 1: Временный исполнитель должности (`hr.ActingAssignment`)

**Files:**
- Modify: `backend/apps/hr/models.py` (новая модель после `Substitution`)
- Create migration: `backend/apps/hr/migrations/0038_acting_assignment.py` (makemigrations)
- Create: `backend/apps/hr/services/acting_service.py`
- Modify: `backend/apps/hr/interface.py` (`resolve_position_users(..., on_date=None)`, `acting_holders`), `backend/apps/hr/schemas.py`, `backend/apps/hr/views.py`, `backend/apps/hr/urls.py`, `backend/apps/hr/admin.py`
- Test: `backend/apps/hr/tests/test_acting_assignment.py`

**Interfaces:**
- Produces (мастер-план §2.6):
  - `hr.interface.resolve_position_users(position_ids, *, on_date: date | None = None) -> dict[int, list[int]]` — держатели плюс временные исполнители на дату (по умолчанию сегодня);
  - `hr.interface.acting_holders(position_id: int, on_date: date) -> list[int]` — только временные исполнители;
  - ручки `GET/POST /api/hr/v1/positions/<id>/acting`, `PATCH/DELETE /api/hr/v1/acting/<id>` (модуль `hr`, уровень `admin`).

- [ ] **Step 1: Падающие тесты**

Create `backend/apps/hr/tests/test_acting_assignment.py`:

```python
"""Временный исполнитель должности на период (D-22, В-16, Q-B19 (б))."""

from datetime import date

import pytest

from apps.hr import interface
from apps.hr.models import ActingAssignment, Department, Employee, EmployeeStatus, Position
from apps.hr.services import acting_service
from apps.users.models import User, UserStatus


def _employee(username: str, position: Position | None = None) -> Employee:
    user = User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=UserStatus.ACTIVE)
    dep, _ = Department.objects.get_or_create(path="acting", defaults={"name": "Отдел"})
    pos = position or Position.objects.create(title=f"Должность {username}", department=dep,
                                              weight=500 + user.pk)
    return Employee.objects.create(user_id=user.pk, first_name=username, last_name="Т",
                                   email=f"e-{username}@htq.test", department=dep,
                                   position=pos, hire_date="2024-01-01",
                                   status=EmployeeStatus.ACTIVE)


@pytest.fixture
def td(db):
    return _employee("td")


@pytest.mark.django_db
def test_acting_only_inside_period(td):
    deputy = _employee("deputy")
    acting_service.create(position_id=td.position_id, employee_id=deputy.id,
                          date_from=date(2026, 10, 1), date_to=date(2026, 10, 10),
                          basis="Приказ №12", assigned_by=1)
    inside = interface.resolve_position_users([td.position_id], on_date=date(2026, 10, 5))
    outside = interface.resolve_position_users([td.position_id], on_date=date(2026, 10, 11))
    assert sorted(inside[td.position_id]) == sorted([td.user_id, deputy.user_id])
    assert outside[td.position_id] == [td.user_id]
    assert interface.acting_holders(td.position_id, date(2026, 10, 5)) == [deputy.user_id]


@pytest.mark.django_db
def test_empty_position_gets_its_acting_executor(db):
    holder = _employee("gone")
    Employee.objects.filter(pk=holder.pk).update(status=EmployeeStatus.DISMISSED)
    deputy = _employee("deputy")
    acting_service.create(position_id=holder.position_id, employee_id=deputy.id,
                          date_from=date(2026, 1, 1), date_to=None, basis="Приказ",
                          assigned_by=1)
    got = interface.resolve_position_users([holder.position_id], on_date=date(2026, 5, 1))
    assert got[holder.position_id] == [deputy.user_id]


@pytest.mark.django_db
def test_dates_out_of_order_are_refused(td):
    deputy = _employee("deputy")
    with pytest.raises(acting_service.ActingError):
        acting_service.create(position_id=td.position_id, employee_id=deputy.id,
                              date_from=date(2026, 10, 10), date_to=date(2026, 10, 1),
                              basis="Приказ", assigned_by=1)


@pytest.mark.django_db
def test_overlap_for_same_person_and_position_is_refused(td):
    deputy = _employee("deputy")
    acting_service.create(position_id=td.position_id, employee_id=deputy.id,
                          date_from=date(2026, 10, 1), date_to=date(2026, 10, 10),
                          basis="Приказ", assigned_by=1)
    with pytest.raises(acting_service.ActingError):
        acting_service.create(position_id=td.position_id, employee_id=deputy.id,
                              date_from=date(2026, 10, 5), date_to=date(2026, 10, 20),
                              basis="Приказ", assigned_by=1)
    assert ActingAssignment.objects.count() == 1
```

⚠️ Название статуса уволенного — проверить в `EmployeeStatus` (`grep -n "class EmployeeStatus" -A8 backend/apps/hr/models.py`) и подставить фактическое.

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_acting_assignment.py -q`
Expected: ошибка сбора — `cannot import name 'ActingAssignment'`.

- [ ] **Step 2: Модель и миграция**

In `backend/apps/hr/models.py` после класса `Substitution`:

```python
class ActingAssignment(HrBase):
    """Временный исполнитель должности на период (D-22, В-16, Q-B19 (б)).

    Закрывает оба случая одной сущностью:
    - должность пуста — этапы согласования получает временный исполнитель;
    - держатель отсутствует — «заместитель пользователя на период»
      оформляется временным исполнителем его должности на те же даты.

    Назначают АДМ и HR вручную, без матрицы ``Substitution``. Движок
    согласования видит исполнителя через ``hr.interface.resolve_position_users``:
    на период он просто входит в держатели должности. Прошлые задачи не
    переписываются — разрешение идёт при создании задачи.
    """

    position = models.ForeignKey(Position, on_delete=models.CASCADE,
                                 related_name="acting_assignments")
    employee = models.ForeignKey("Employee", on_delete=models.CASCADE,
                                 related_name="acting_assignments")
    date_from = models.DateField()
    date_to = models.DateField(null=True, blank=True)
    basis = models.CharField(max_length=255)
    assigned_by = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["position", "date_from"], name="ix_hr_acting_pos")]
        verbose_name = "Временный исполнитель должности"
        verbose_name_plural = "Временные исполнители должностей"
```

Сгенерировать миграцию:

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py makemigrations hr --name acting_assignment
```

Expected: `apps/hr/migrations/0038_acting_assignment.py` с одной `CreateModel`.

- [ ] **Step 3: Сервис**

Create `backend/apps/hr/services/acting_service.py`:

```python
"""Временные исполнители должностей (D-22)."""

from __future__ import annotations

from datetime import date

from django.db.models import Q

from apps.hr.models import ActingAssignment


class ActingError(Exception):
    pass


def _check(position_id: int, employee_id: int, date_from: date, date_to: date | None,
           *, exclude_id: int | None = None) -> None:
    if date_to is not None and date_to < date_from:
        raise ActingError("Дата окончания раньше даты начала")
    overlapping = ActingAssignment.objects.filter(position_id=position_id,
                                                  employee_id=employee_id)
    if exclude_id is not None:
        overlapping = overlapping.exclude(pk=exclude_id)
    if date_to is not None:
        overlapping = overlapping.filter(date_from__lte=date_to)
    overlapping = overlapping.filter(Q(date_to__isnull=True) | Q(date_to__gte=date_from))
    if overlapping.exists():
        raise ActingError("У сотрудника уже есть назначение на эту должность в этот период")


def create(*, position_id: int, employee_id: int, date_from: date, date_to: date | None,
           basis: str, assigned_by: int | None) -> ActingAssignment:
    _check(position_id, employee_id, date_from, date_to)
    return ActingAssignment.objects.create(position_id=position_id, employee_id=employee_id,
                                           date_from=date_from, date_to=date_to, basis=basis,
                                           assigned_by=assigned_by)


def update(row: ActingAssignment, **fields) -> ActingAssignment:
    for key, value in fields.items():
        setattr(row, key, value)
    _check(row.position_id, row.employee_id, row.date_from, row.date_to, exclude_id=row.pk)
    row.save()
    return row


def active_on(position_ids: list[int], on_date: date):
    return (ActingAssignment.objects
            .filter(position_id__in=position_ids, date_from__lte=on_date)
            .filter(Q(date_to__isnull=True) | Q(date_to__gte=on_date))
            .select_related("employee"))


def serialize(row: ActingAssignment) -> dict:
    return {"id": row.id, "position_id": row.position_id, "employee_id": row.employee_id,
            "user_id": row.employee.user_id, "date_from": row.date_from.isoformat(),
            "date_to": row.date_to.isoformat() if row.date_to else None,
            "basis": row.basis, "assigned_by": row.assigned_by}
```

- [ ] **Step 4: Интерфейс**

In `backend/apps/hr/interface.py` заменить `resolve_position_users` и добавить `acting_holders`:

```python
def resolve_position_users(position_ids: list[int], *,
                           on_date: date | None = None) -> dict[int, list[int]]:
    """Resolve HR positions to their current, usable platform accounts.

    The answer deliberately contains only employees who are active, not soft
    deleted, linked to an account, and whose account is active.  This keeps a
    route declarative ("financial controller") while a live approval task
    remains attributable to one concrete JWT identity.

    Временные исполнители должности (``ActingAssignment``) на ``on_date``
    (по умолчанию — сегодня) входят в держателей наравне с сотрудниками на
    должности (D-22). Порядок — сначала держатели, затем исполнители.
    """
    require_service("hr")
    from .services import acting_service

    ids = list(dict.fromkeys(position_ids))
    if not ids:
        return {}
    on_date = on_date or timezone.localdate()

    rows = list(
        Employee.objects.filter(
            position_id__in=ids,
            status=EmployeeStatus.ACTIVE,
            is_deleted=False,
            user_id__isnull=False,
            position__is_active=True,
        ).values("position_id", "user_id")
    )
    rows += [
        {"position_id": acting.position_id, "user_id": acting.employee.user_id}
        for acting in acting_service.active_on(ids, on_date)
        if acting.employee.status == EmployeeStatus.ACTIVE and not acting.employee.is_deleted
        and acting.employee.user_id
    ]
    briefs = {row["id"]: row for row in users.get_users_brief(
        [row["user_id"] for row in rows]
    )}
    resolved: dict[int, list[int]] = {position_id: [] for position_id in ids}
    for row in rows:
        brief = briefs.get(row["user_id"])
        if brief and brief.get("is_active") and row["user_id"] not in resolved[row["position_id"]]:
            resolved[row["position_id"]].append(row["user_id"])
    return resolved


def acting_holders(position_id: int, on_date: date) -> list[int]:
    """Только временные исполнители должности на дату — для самосогласования."""
    require_service("hr")
    from .services import acting_service

    return [row.employee.user_id for row in acting_service.active_on([position_id], on_date)
            if row.employee.user_id]
```

Проверить импорты в начале `interface.py`: `from datetime import date` и `from django.utils import timezone` (добавить, если нет).

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_acting_assignment.py apps/signoff/tests -q`
Expected: всё PASS.

- [ ] **Step 5: Ручки**

In `backend/apps/hr/schemas.py`:

```python
class ActingCreate(BaseModel):
    employee_id: int
    date_from: date
    date_to: Optional[date] = None
    basis: str = Field(..., min_length=1, max_length=255)


class ActingUpdate(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    basis: Optional[str] = Field(None, min_length=1, max_length=255)
```

In `backend/apps/hr/views.py` рядом с блоком замещений (`position_substitutions`) — по тому же образцу:

```python
# ── /positions/{id}/acting, /acting/{id} — временные исполнители (D-22) ─────

@api_view(methods=("GET",), auth="jwt", module="hr", level="read")
def _list_acting(request, id: int):
    from .models import ActingAssignment

    rows = ActingAssignment.objects.filter(position_id=id).select_related("employee")
    return [acting_svc.serialize(row) for row in rows.order_by("-date_from")]


@api_view(methods=("POST",), auth="jwt", body=schemas.ActingCreate, status=201,
          module="hr", level="admin")
def _create_acting(request, id: int, data: schemas.ActingCreate):
    try:
        row = acting_svc.create(position_id=id, employee_id=data.employee_id,
                                date_from=data.date_from, date_to=data.date_to,
                                basis=data.basis, assigned_by=request.token.user_id)
    except acting_svc.ActingError as exc:
        return json_error(str(exc), 422)
    return acting_svc.serialize(row)


def position_acting(request, id: int):
    if request.method == "GET":
        return _list_acting(request, id=id)
    if request.method == "POST":
        return _create_acting(request, id=id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PATCH",), auth="jwt", body=schemas.ActingUpdate, module="hr",
          level="admin")
def _update_acting(request, acting_id: int, data: schemas.ActingUpdate):
    from .models import ActingAssignment

    row = ActingAssignment.objects.filter(pk=acting_id).first()
    if row is None:
        return json_error("Назначение не найдено", 404)
    try:
        row = acting_svc.update(row, **data.model_dump(exclude_unset=True))
    except acting_svc.ActingError as exc:
        return json_error(str(exc), 422)
    return acting_svc.serialize(row)


@api_view(methods=("DELETE",), auth="jwt", module="hr", level="admin", status=204)
def _delete_acting(request, acting_id: int):
    from .models import ActingAssignment

    ActingAssignment.objects.filter(pk=acting_id).delete()
    return _no_content()


def acting_detail(request, acting_id: int):
    if request.method == "PATCH":
        return _update_acting(request, acting_id=acting_id)
    if request.method == "DELETE":
        return _delete_acting(request, acting_id=acting_id)
    return json_error("Method Not Allowed", 405)
```

⚠️ Импорт `from .services import acting_service as acting_svc` — наверху `views.py`, рядом с `sub_svc`. Как `views.py` отдаёт пустой 204 — посмотреть у `_delete_substitution` и повторить.

In `backend/apps/hr/urls.py` рядом с маршрутами замещений:

```python
    path("positions/<int:id>/acting", views.position_acting),
    path("positions/<int:id>/acting/", views.position_acting),
    path("acting/<int:acting_id>", views.acting_detail),
    path("acting/<int:acting_id>/", views.acting_detail),
```

`backend/apps/hr/admin.py` — регистрация `ActingAssignment` с `ServiceGatedAdminMixin`.

Run: `../.venv/Scripts/python.exe -m pytest apps/hr/tests apps/access/tests/test_gate.py apps/core/tests/test_invariants.py -q`
Expected: всё PASS.

- [ ] **Step 6: Документация и коммит**

`CLAUDE.md`, раздел «Мультикомпанейность», после абзаца «Замещение ключевых должностей»:

```markdown
- **Временный исполнитель должности** — `hr.ActingAssignment` (миграция `hr/0038`, D-22): должность, сотрудник, период, основание; назначают АДМ и HR (`/api/hr/v1/positions/<id>/acting`). В отличие от матрицы `Substitution` это не правило, а факт на период: `hr.interface.resolve_position_users(..., on_date=)` включает исполнителя в держатели должности, и маршруты согласования видят его без доработок. Закрывает и пустую должность (В-16), и «заместителя пользователя на период» (Q-B19 (б)).
```

```bash
git add backend/apps/hr CLAUDE.md
git commit -m "feat(hr): временный исполнитель должности на период — входит в держатели должности для согласований"
```

---

## Task 2: Флаги маршрута и комментарий при отказе

**Files:**
- Modify: `backend/apps/signoff/models.py` (`ApprovalRoute` — флаги; `ApprovalProcess.route_flags`)
- Create migration: `backend/apps/signoff/migrations/0012_route_flags.py` (makemigrations)
- Modify: `backend/apps/signoff/services/engine.py` (`start` — снимок флагов; `act` — длина комментария; исключение `CommentTooShort`), `services/route_service.py` (`create_route`, `update_route`, `serialize_route`), `schemas.py` (`RouteCreate`, `RouteUpdate`, `RouteRead`), `views.py` (422 на `CommentTooShort`)
- Test: `backend/apps/signoff/tests/test_route_flags.py`

**Interfaces:**
- Produces:
  - поля маршрута `forbid_self_approval: bool`, `reject_comment_min: int`, `lazy_resolution: bool`, `self_approval_position_id: int | None`, `no_executor_notify_position_ids: list[int]`, `self_skip_notify_position_ids: list[int]`;
  - `ApprovalProcess.route_flags: dict` — снимок этих полей на запуске;
  - `engine.CommentTooShort(SignoffError)` — ручки отвечают 422.

- [ ] **Step 1: Падающие тесты**

Create `backend/apps/signoff/tests/test_route_flags.py`:

```python
"""Флаги маршрута: снимок в процессе, комментарий при отказе (BR-060)."""

import pytest

from apps.signoff.models import ApprovalProcess, ApprovalRoute, Quorum
from apps.signoff.services import engine
from apps.signoff.tests.helpers import SUBJECT, make_doc, make_route, make_user, task_for
from apps.signoff.tests.testapp import hooks

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset():
    hooks.reset()
    yield
    hooks.reset()


def test_route_without_flags_behaves_as_before():
    a = make_user("a")
    route = make_route([(1, "Один", Quorum.ALL, [a.pk])])
    assert (route.forbid_self_approval, route.reject_comment_min, route.lazy_resolution) \
        == (False, 0, False)
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk, initiator_id=a.pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.REJECT,
               comment="")
    assert ApprovalProcess.objects.get(pk=process.pk).state == "rejected"


def test_flags_are_snapshotted_at_start():
    a = make_user("a")
    route = make_route([(1, "Один", Quorum.ALL, [a.pk])])
    ApprovalRoute.objects.filter(pk=route.pk).update(reject_comment_min=10,
                                                     forbid_self_approval=True)
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    ApprovalRoute.objects.filter(pk=route.pk).update(reject_comment_min=0)
    assert ApprovalProcess.objects.get(pk=process.pk).route_flags["reject_comment_min"] == 10


@pytest.mark.parametrize("decision", [engine.REJECT, engine.REWORK])
def test_short_comment_is_refused(decision):
    a = make_user("a")
    route = make_route([(1, "Один", Quorum.ALL, [a.pk])])
    ApprovalRoute.objects.filter(pk=route.pk).update(reject_comment_min=10)
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    task = task_for(process, a.pk)
    with pytest.raises(engine.CommentTooShort) as exc:
        engine.act(task_id=task.pk, actor_id=a.pk, decision=decision, comment="   коротко ")
    assert "не короче 10 символов" in str(exc.value)
    engine.act(task_id=task.pk, actor_id=a.pk, decision=decision,
               comment="Нет обоснования цены")


def test_approve_needs_no_comment_even_with_minimum():
    a = make_user("a")
    route = make_route([(1, "Один", Quorum.ALL, [a.pk])])
    ApprovalRoute.objects.filter(pk=route.pk).update(reject_comment_min=10)
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)


def test_api_answers_422_for_short_comment(client):
    from apps.signoff.tests.helpers import BASE, auth, post_json, user_token

    a = make_user("a")
    route = make_route([(1, "Один", Quorum.ALL, [a.pk])])
    ApprovalRoute.objects.filter(pk=route.pk).update(reject_comment_min=10)
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    response = post_json(client, f"{BASE}/tasks/{task_for(process, a.pk).pk}/decision",
                         {"decision": "reject", "comment": "нет"}, **auth(user_token(a)))
    assert response.status_code == 422
```

⚠️ Путь ручки решения — проверить в `backend/apps/signoff/urls.py` (`tasks/<int:task_id>/decision`).

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests/test_route_flags.py -q`
Expected: FAIL — у `ApprovalRoute` нет `forbid_self_approval`.

- [ ] **Step 2: Модель и миграция**

In `backend/apps/signoff/models.py`, класс `ApprovalRoute`, после `is_active`:

```python
    # ── Флаги маршрута (D-21, ТЗ §16). Выключены по умолчанию: маршруты
    # кадровых предметов, заявок и договоров их не включают и ведут себя как
    # раньше. На запуске копируются снимком в ApprovalProcess.route_flags.
    forbid_self_approval = models.BooleanField(
        default=False, db_default=False, verbose_name="Запрет самосогласования (BR-061)")
    self_approval_position_id = models.IntegerField(
        null=True, blank=True, verbose_name="Кому уходит этап автора (обычно ГД)")
    self_skip_notify_position_ids = models.JSONField(
        default=list, blank=True, db_default=[],
        verbose_name="Кого уведомить о пропуске этапа автора (обычно ФД)")
    reject_comment_min = models.PositiveSmallIntegerField(
        default=0, db_default=0, verbose_name="Минимум символов комментария при отказе (BR-060)")
    lazy_resolution = models.BooleanField(
        default=False, db_default=False, verbose_name="Исполнитель — при активации этапа")
    no_executor_notify_position_ids = models.JSONField(
        default=list, blank=True, db_default=[],
        verbose_name="Кого уведомить о «Нет исполнителя» (обычно АДМ и ГД)")

    FLAG_FIELDS = ("forbid_self_approval", "self_approval_position_id",
                   "self_skip_notify_position_ids", "reject_comment_min",
                   "lazy_resolution", "no_executor_notify_position_ids")

    def flags(self) -> dict:
        return {name: getattr(self, name) for name in self.FLAG_FIELDS}
```

In `ApprovalProcess` после `subject_facts`:

```python
    # Флаги маршрута на момент запуска — снимком, как этапы: правка маршрута
    # не меняет правила идущего согласования.
    route_flags = models.JSONField(default=dict, blank=True, db_default={})
```

⚠️ Если `JSONField(db_default=[])` не принимается этой версией Django — использовать `db_default=Value([], output_field=models.JSONField())` из `django.db.models` или убрать `db_default` у JSON-полей (Django сам проставит `default` при вставке через ORM).

Сгенерировать миграцию:

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py makemigrations signoff --name route_flags
```

Expected: `0012_route_flags.py` — только `AddField`.

- [ ] **Step 3: Снимок флагов и проверка комментария**

In `backend/apps/signoff/services/engine.py`:

1. Рядом с остальными исключениями:

```python
class CommentTooShort(SignoffError):
    """Комментарий при «Отклонить» / «Вернуть» короче минимума маршрута (BR-060)."""
```

2. В `start`, в `ApprovalProcess.objects.create(...)` добавить `route_flags=route.flags(),`.
3. В `act` сразу после проверки `requirement_key` (перед `task.state = …`):

```python
    min_length = int((process.route_flags or {}).get("reject_comment_min") or 0)
    if decision in (REJECT, REWORK) and min_length and len(comment.strip()) < min_length:
        raise CommentTooShort(
            f"Опишите причину: комментарий не короче {min_length} символов")
```

⚠️ В `act` переменная `process` к этому месту — процесс под блокировкой (`_lock`); в блоке `requirement_key` она переприсваивается `stage.process` — тот же объект по id; `route_flags` читать с любого.

- [ ] **Step 4: Маршрут в API**

In `backend/apps/signoff/schemas.py`:

```python
class RouteFlags(BaseModel):
    forbid_self_approval: Optional[bool] = None
    self_approval_position_id: Optional[int] = None
    self_skip_notify_position_ids: Optional[list[int]] = None
    reject_comment_min: Optional[int] = Field(None, ge=0, le=500)
    lazy_resolution: Optional[bool] = None
    no_executor_notify_position_ids: Optional[list[int]] = None
```

`RouteCreate` и `RouteUpdate` наследуют `RouteFlags` (`class RouteCreate(RouteFlags):`, `class RouteUpdate(RouteFlags):`). В `RouteRead` добавить поля без `Optional`: `forbid_self_approval: bool = False`, `self_approval_position_id: Optional[int] = None`, `self_skip_notify_position_ids: list[int] = []`, `reject_comment_min: int = 0`, `lazy_resolution: bool = False`, `no_executor_notify_position_ids: list[int] = []`.

In `backend/apps/signoff/services/route_service.py`:
- `create_route` принимает `**flags` и передаёт в `ApprovalRoute.objects.create(...)` значения, которые не `None`;
- `update_route` уже ставит любые не-`None` поля — проверить, что вьюха передаёт ему флаги из схемы (`data.model_dump(exclude_unset=True)`);
- `serialize_route` добавляет `**route.flags()` в словарь;
- позиции в `self_approval_position_id` и в обоих списках проверяются `_check_positions_exist(...)`, как у этапов.

In `backend/apps/signoff/views.py`, в ручке решения по задаче и в `TaskBatchDecisionView` перехватить `engine.CommentTooShort` ДО общего `CONFLICTS` и ответить `json_error(str(exc), 422)`.

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests -q`
Expected: всё PASS — и новые, и старые.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/signoff
git commit -m "feat(signoff): флаги маршрута со снимком в процессе; комментарий при отказе не короче минимума (BR-060)"
```

---

## Task 3: Запрет самосогласования

**Files:**
- Modify: `backend/apps/signoff/services/engine.py` (`_resolve_stages`, `start`, `_advance`, новый `_skip_forward`, `_notify_self_skip`)
- Test: `backend/apps/signoff/tests/test_self_approval.py`

**Interfaces:**
- Consumes: `hr.interface.resolve_position_users(..., on_date=)` (задача 1), `route_flags` (задача 2).
- Produces: при `forbid_self_approval` автор не получает задачу на этапе. Этап уходит:
  - другим держателям должности, включая временного исполнителя;
  - иначе — должности `self_approval_position_id` (ГД);
  - если автор и есть ГД — этап `skipped` с событием `self_approval_skipped` и уведомлением `self_skip_notify_position_ids`.

- [ ] **Step 1: Падающие тесты**

Create `backend/apps/signoff/tests/test_self_approval.py`:

```python
"""Запрет самосогласования (BR-061, D-22, умолчание Q-E25)."""

import pytest

from apps.signoff.models import (ApprovalEvent, ApprovalProcess, ApprovalRoute,
                                 ApprovalTask, Quorum, StageState)
from apps.signoff.services import engine
from apps.signoff.tests.helpers import make_doc, make_route, make_user, stage_states
from apps.signoff.tests.testapp import hooks
from apps.signoff.tests.testapp.models import ProbeDoc

pytestmark = pytest.mark.django_db
SUBJECT = ProbeDoc.SIGNOFF_SUBJECT_TYPE


@pytest.fixture(autouse=True)
def _reset():
    hooks.reset()
    yield
    hooks.reset()


def _route(stages, **flags):
    route = make_route(stages)
    ApprovalRoute.objects.filter(pk=route.pk).update(forbid_self_approval=True, **flags)
    return route


def _users(process) -> set[int]:
    return set(ApprovalTask.objects.filter(stage__process=process)
               .values_list("user_id", flat=True))


def test_flag_off_keeps_the_author_on_his_stage():
    td = make_user("td")
    make_route([(1, "ТД", Quorum.ALL, [td.pk])])
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk, initiator_id=td.pk)
    assert _users(process) == {td.pk}


def test_author_alone_on_stage_goes_to_fallback():
    td, gd = make_user("td"), make_user("gd")
    _route([(1, "ТД", Quorum.ALL, [td.pk])], self_approval_position_id=gd.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk, initiator_id=td.pk)
    assert _users(process) == {gd.pk}


def test_general_director_author_skips_stage():
    gd, od = make_user("gd"), make_user("od")
    _route([(1, "ГД", Quorum.ALL, [gd.pk]), (2, "ОД", Quorum.ALL, [od.pk])],
           self_approval_position_id=gd.pk, self_skip_notify_position_ids=[od.pk])
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk, initiator_id=gd.pk)
    assert stage_states(process) == [StageState.SKIPPED, StageState.ACTIVE]
    assert _users(process) == {od.pk}
    assert ApprovalEvent.objects.filter(process=process, kind="self_approval_skipped").exists()


def test_only_stage_skipped_approves_the_process():
    gd = make_user("gd")
    _route([(1, "ГД", Quorum.ALL, [gd.pk])], self_approval_position_id=gd.pk)
    doc = make_doc()
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk, initiator_id=gd.pk)
    assert ApprovalProcess.objects.get(pk=process.pk).state == "approved"
    assert ("approved", doc.pk) in hooks.CALLS


def test_author_is_removed_from_a_shared_stage():
    a, b = make_user("a"), make_user("b")
    _route([(1, "Двое", Quorum.ANY, [a.pk, b.pk])])
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk, initiator_id=a.pk)
    assert _users(process) == {b.pk}
```

⚠️ `make_route` связывает этап с должностью `id == user.pk` (`apps/signoff/tests/helpers.py::make_user`), поэтому `self_approval_position_id=gd.pk` — должность ГД.

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests/test_self_approval.py -q`
Expected: FAIL — автор получает задачу.

- [ ] **Step 2: Разрешение с учётом автора**

In `backend/apps/signoff/services/engine.py`:

1. `_resolve_stages` получает `flags: dict` (из `route.flags()` в `start`) и после вычисления `approvers_by_position` для этапа вызывает:

```python
        approvers_by_position, self_skipped = _exclude_author(
            stage, approvers_by_position, initiator_id=initiator_id, flags=flags)
        plan.append((stage.order, stage, item.matched_by, approvers_by_position,
                     self_skipped))
```

(кортеж плана становится пятиэлементным — поправить все места, где он распаковывается в `start`, и проверку активности ниже: у пропущенного этапа проверять нечего).

2. Новая функция:

```python
def _exclude_author(stage, approvers_by_position: dict, *, initiator_id: int | None,
                    flags: dict) -> tuple[dict, bool]:
    """BR-061: автор не согласует свой документ.

    Автор снимается со своих задач этапа. Если после этого на этапе никого
    нет, этап уходит должности ``self_approval_position_id`` (ГД), кроме
    самого автора. Если и там никого — автор и есть ГД: этап пропускается
    (``True`` во втором значении), и ``start`` пишет событие и уведомляет ФД.
    Временный исполнитель должности уже входит в держателей
    (``hr.resolve_position_users``), поэтому отдельно не ищется.
    """
    if not flags.get("forbid_self_approval") or initiator_id is None:
        return approvers_by_position, False
    cleaned = {position: [u for u in users if u != initiator_id]
               for position, users in approvers_by_position.items()}
    cleaned = {position: users for position, users in cleaned.items() if users}
    if cleaned:
        return cleaned, False
    fallback_position = flags.get("self_approval_position_id")
    if fallback_position:
        fallback_users = [u for u in hr.resolve_position_users([fallback_position])
                          .get(fallback_position, []) if u != initiator_id]
        if fallback_users:
            return {fallback_position: fallback_users}, False
    return {}, True
```

3. В `start` при создании этапов: этап с `self_skipped=True` создаётся в состоянии `StageState.SKIPPED`, без задач, и пишется событие:

```python
            _log(process, "self_approval_skipped", actor_id=initiator_id,
                 payload={"stage": stage.name, "order": order})
```

`first_order` считается по этапам, которые не пропущены; если пропущены все — процесс сразу завершается согласованием (`_finish(process, ProcessState.APPROVED, actor_id=initiator_id)`), см. шаг 3. Уведомление о пропуске — после коммита:

```python
def _notify_self_skip(process: ApprovalProcess, stage_name: str) -> None:
    position_ids = list((process.route_flags or {}).get("self_skip_notify_position_ids") or [])
    if not position_ids:
        return
    resolved = hr.resolve_position_users(position_ids)
    user_ids = sorted({u for users in resolved.values() for u in users})
    described = _describe(process)
    _notify(user_ids, {"type": "signoff.self_approval_skipped", "process_id": process.pk,
                       "subject_type": process.subject_type,
                       "subject_id": process.subject_id, "stage": stage_name,
                       "title": described.get("title"), "url": described.get("url")})
```

- [ ] **Step 3: Пропущенные этапы не держат процесс**

1. В `_advance`: `if not all(stage.state in (StageState.APPROVED, StageState.SKIPPED) for stage in current):`.
2. Новая функция — «пройти вперёд, пока текущая группа закрыта»:

```python
def _skip_forward(process: ApprovalProcess, *, actor_id: int | None) -> None:
    """После запуска: если первая группа целиком пропущена, двигаться дальше."""
    current = list(process.stages.filter(order=process.current_order))
    if current and all(stage.state == StageState.SKIPPED for stage in current):
        _advance(process, actor_id=actor_id)
```

3. В `start`: `first_order` — минимальный `order` среди НЕ пропущенных этапов; если таких нет, `first_order` — минимальный из всех, этапы создаются, и сразу после создания вызывается `_skip_forward(process, actor_id=initiator_id)` (он дойдёт до `_finish`). Состояние `ACTIVE` получают только непропущенные этапы группы `first_order`.
4. В `_advance`, при активации следующей группы: пропущенные при запуске этапы этой группы остаются `SKIPPED` (`.exclude(state=StageState.SKIPPED)` в `update(state=ACTIVE)`), и если после этого в группе нет активных — снова `_advance`.

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests -q`
Expected: всё PASS.

- [ ] **Step 4: Коммит**

```bash
git add backend/apps/signoff
git commit -m "feat(signoff): запрет самосогласования — этап уходит другим держателям, ГД или пропускается с уведомлением ФД (BR-061)"
```

---

## Task 4: Ленивое разрешение исполнителей и «Нет исполнителя»

**Files:**
- Modify: `backend/apps/signoff/models.py` (`StageState.NO_EXECUTOR`, `ApprovalProcessStage.activated_at`)
- Create migration: `backend/apps/signoff/migrations/0013_lazy_stages.py` (makemigrations)
- Modify: `backend/apps/signoff/services/engine.py` (`start`, `_advance`, новые `_activate_group`, `resolve_waiting`), `backend/apps/signoff/interface.py` (`resolve_waiting_stages`), `backend/apps/signoff/tasks.py` (новый или дополнить)
- Create migration: `backend/apps/signoff/migrations/0014_resolve_waiting_periodic_task.py`
- Test: `backend/apps/signoff/tests/test_lazy_resolution.py`

**Interfaces:**
- Produces:
  - `StageState.NO_EXECUTOR = "no_executor"` («Нет исполнителя»);
  - `ApprovalProcessStage.activated_at`;
  - `engine.resolve_waiting(process_id: int) -> bool`;
  - `interface.resolve_waiting_stages() -> int`;
  - Celery `apps.signoff.tasks.resolve_waiting_dispatch` (каждые 15 минут, веер по компаниям).

- [ ] **Step 1: Падающие тесты**

Create `backend/apps/signoff/tests/test_lazy_resolution.py`:

```python
"""Ленивое разрешение исполнителей и «Нет исполнителя» (Q-C10, Q-B22)."""

import pytest

from apps.hr.models import Employee, EmployeeStatus
from apps.signoff.models import ApprovalProcess, ApprovalRoute, ApprovalTask, Quorum, StageState
from apps.signoff.services import engine
from apps.signoff.tests.helpers import (SUBJECT, make_doc, make_route, make_user,
                                        stage_states, task_for)
from apps.signoff.tests.testapp import hooks

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset():
    hooks.reset()
    yield
    hooks.reset()


def _lazy(stages, **flags):
    route = make_route(stages)
    ApprovalRoute.objects.filter(pk=route.pk).update(lazy_resolution=True, **flags)
    return route


def test_without_lazy_missing_executor_still_refuses_to_start():
    a = make_user("a")
    Employee.objects.filter(user_id=a.pk).update(status=EmployeeStatus.SUSPENDED)
    make_route([(1, "Один", Quorum.ALL, [a.pk])])
    with pytest.raises(engine.RouteUnusable):
        engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)


def test_later_stage_is_resolved_on_activation():
    a, b = make_user("a"), make_user("b")
    _lazy([(1, "Первый", Quorum.ALL, [a.pk]), (2, "Второй", Quorum.ALL, [b.pk])])
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    assert set(ApprovalTask.objects.filter(stage__process=process)
               .values_list("user_id", flat=True)) == {a.pk}
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)
    assert task_for(process, b.pk).stage.activated_at is not None


def test_first_stage_without_executor_waits_and_recovers():
    a, adm = make_user("a"), make_user("adm")
    Employee.objects.filter(user_id=a.pk).update(status=EmployeeStatus.SUSPENDED)
    _lazy([(1, "Первый", Quorum.ALL, [a.pk])], no_executor_notify_position_ids=[adm.pk])
    doc = make_doc()
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)
    assert ApprovalProcess.objects.get(pk=process.pk).state == "pending"
    assert stage_states(process) == [StageState.NO_EXECUTOR]
    assert not engine.resolve_waiting(process.pk)  # всё ещё некому

    Employee.objects.filter(user_id=a.pk).update(status=EmployeeStatus.ACTIVE)
    assert engine.resolve_waiting(process.pk)
    assert stage_states(process) == [StageState.ACTIVE]
    assert task_for(process, a.pk)


def test_later_stage_without_executor_waits():
    a, b = make_user("a"), make_user("b")
    _lazy([(1, "Первый", Quorum.ALL, [a.pk]), (2, "Второй", Quorum.ALL, [b.pk])])
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    Employee.objects.filter(user_id=b.pk).update(status=EmployeeStatus.SUSPENDED)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)
    assert stage_states(process) == [StageState.APPROVED, StageState.NO_EXECUTOR]
```

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests/test_lazy_resolution.py -q`
Expected: FAIL — нет `StageState.NO_EXECUTOR`.

- [ ] **Step 2: Состояние и время активации**

In `backend/apps/signoff/models.py`:
- в `StageState` добавить `NO_EXECUTOR = "no_executor", "Нет исполнителя"` с комментарием «этап активен, но разрешить исполнителя не удалось; документ ждёт (Q-B22)»;
- в `ApprovalProcessStage` добавить `activated_at = models.DateTimeField(null=True, blank=True)` («когда этап стал активным — «Сейчас у … с»»).

Сгенерировать миграцию `0013_lazy_stages` (makemigrations, как в задаче 2).

- [ ] **Step 3: Движок**

In `backend/apps/signoff/services/engine.py`:

1. `_resolve_stages(..., flags)`: при `flags.get("lazy_resolution")` разрешает ТОЛЬКО этапы первой группы (минимальный `order` среди отобранных). Для остальных в план кладётся `None` вместо словаря исполнителей. Для этапа первой группы, где разрешение дало пустой набор, `RouteUnusable` не поднимается — в план кладётся пустой словарь и признак «нет исполнителя». Для этого `_approver_ids` получает параметр `strict: bool = True`: при `strict=False` отсутствие держателей даёт `{}` вместо `RouteUnusable`. Проверка «неактивный согласующий» ниже в `_resolve_stages` к ленивым этапам не применяется.
2. `start`: этап первой группы с пустыми исполнителями создаётся в состоянии `NO_EXECUTOR`, остальные активные — `ACTIVE` с `activated_at=now`; этапы групп дальше — `WAITING` без задач. После создания — `_notify_no_executor(process, stage)` для каждого этапа `NO_EXECUTOR`.
3. Новая функция активации группы (зовётся из `_advance` вместо `process.stages.filter(order=next_order).update(state=ACTIVE)`):

```python
def _activate_group(process: ApprovalProcess, order: int, *, actor_id: int | None) -> None:
    """Сделать группу этапов текущей; при ленивом маршруте — разрешить исполнителей."""
    lazy = bool((process.route_flags or {}).get("lazy_resolution"))
    for stage in process.stages.filter(order=order).exclude(state=StageState.SKIPPED):
        if lazy and not stage.tasks.exists():
            _resolve_into(stage, process)
        else:
            stage.state, stage.activated_at = StageState.ACTIVE, _now()
            stage.save(update_fields=["state", "activated_at"])


def _resolve_into(stage: ApprovalProcessStage, process: ApprovalProcess) -> bool:
    """Разрешить исполнителей этапа снимка и создать задачи; нет — «Нет исполнителя»."""
    approvers = _approver_ids(stage, initiator_id=process.initiator_id,
                              subject_type=process.subject_type,
                              subject_id=process.subject_id, strict=False)
    approvers, skipped = _exclude_author(stage, approvers, initiator_id=process.initiator_id,
                                         flags=process.route_flags or {})
    if skipped:
        stage.state = StageState.SKIPPED
        stage.save(update_fields=["state"])
        _log(process, "self_approval_skipped", actor_id=None, payload={"stage": stage.name})
        _notify_self_skip(process, stage.name)
        return True
    if not any(approvers.values()):
        stage.state = StageState.NO_EXECUTOR
        stage.save(update_fields=["state"])
        _notify_no_executor(process, stage)
        return False
    ApprovalTask.objects.bulk_create([
        ApprovalTask(stage=stage, user_id=user_id, position_id=position_id)
        for position_id, user_ids in approvers.items() for user_id in user_ids])
    stage.state, stage.activated_at = StageState.ACTIVE, _now()
    stage.save(update_fields=["state", "activated_at"])
    return True
```

⚠️ `_approver_ids` сейчас читает `stage.roles.all()` / `stage.user_ids` / `stage.approver_key` у ЭТАПА МАРШРУТА. Этап снимка (`ApprovalProcessStage`) хранит то же в `role_ids`, `user_ids`, `approver_key`, `approver_kind`. Добавить в `_approver_ids` чтение из снимка: если у объекта есть `role_ids` (этап снимка) — позиции брать из него, иначе — из `roles.all()`.

4. `_notify_no_executor` — по образцу `_notify_self_skip` из задачи 3, тип `"signoff.no_executor"`, получатели — держатели `no_executor_notify_position_ids`. Событие журнала: `_log(process, "no_executor", actor_id=None, payload={"stage": stage.name})`.
5. `_advance`: группа закрыта, если каждый этап `APPROVED` или `SKIPPED`. Этап `NO_EXECUTOR` группу не закрывает — процесс ждёт.
6. Повторная попытка:

```python
@transaction.atomic
def resolve_waiting(process_id: int) -> bool:
    """Перепроверить этапы «Нет исполнителя»; True — у всех появились исполнители."""
    process = _lock(process_id)
    if process.state != ProcessState.PENDING:
        return True
    waiting = list(process.stages.filter(state=StageState.NO_EXECUTOR))
    resolved = [_resolve_into(stage, process) for stage in waiting]
    if waiting and all(resolved):
        _notify_active_stages(process)
        _advance(process, actor_id=None)
    return all(resolved)
```

- [ ] **Step 4: Интерфейс и периодическая проверка**

In `backend/apps/signoff/interface.py`:

```python
def resolve_waiting_stages() -> int:
    """Перепроверить все процессы с этапами «Нет исполнителя» в текущей компании."""
    require_service("signoff")
    from apps.signoff.models import ApprovalProcess

    ids = list(ApprovalProcess.objects.filter(state=ProcessState.PENDING,
                                              stages__state=StageState.NO_EXECUTOR)
               .values_list("pk", flat=True).distinct())
    return sum(1 for pid in ids if engine.resolve_waiting(pid))
```

In `backend/apps/signoff/tasks.py` (создать, если нет) — по образцу `htqweb/tenancy/celery.py` (докстринг модуля):

```python
from celery import shared_task

from apps.core.services import require_service
from htqweb.tenancy.celery import company_dispatch_task, company_task, fan_out_to_companies


@shared_task
@company_task
def resolve_waiting() -> int:
    require_service("signoff")
    from apps.signoff import interface

    return interface.resolve_waiting_stages()


@shared_task
@company_dispatch_task
def resolve_waiting_dispatch():
    require_service("signoff")
    return fan_out_to_companies(resolve_waiting, label="resolve_waiting_dispatch")
```

Create `backend/apps/signoff/migrations/0014_resolve_waiting_periodic_task.py` по образцу `apps/core/migrations/0005_daily_digest_periodic_task.py`: `TASK_NAME = "signoff.resolve_waiting_dispatch"`, cron `minute="*/15"`, `hour="*"`, `day_of_week="*"`, `"task": "apps.signoff.tasks.resolve_waiting_dispatch"`.

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests apps/core/tests/test_invariants.py -q`
Expected: всё PASS.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/signoff
git commit -m "feat(signoff): ленивое разрешение исполнителей и состояние «Нет исполнителя» с эскалацией и перепроверкой"
```

---

## Task 5: Флаги в редакторе маршрута (фронт)

**Files:**
- Modify: `frontend/src/types/signoff.ts` (поля маршрута и `StageState`), `frontend/src/api/signoff.ts` (тело правки маршрута), `frontend/src/components/signoff/RouteEditorPanel.tsx`, `frontend/src/components/signoff/states.tsx` (подпись «Нет исполнителя»)
- Create: `frontend/src/components/signoff/RouteFlagsForm.tsx`, `frontend/src/components/signoff/RouteFlagsForm.test.tsx`

**Interfaces:**
- Consumes: поля маршрута из задачи 2, состояние `no_executor` из задачи 4.

- [ ] **Step 1: Падающий тест**

Create `frontend/src/components/signoff/RouteFlagsForm.test.tsx`:

```tsx
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { RouteFlagsForm } from './RouteFlagsForm';

const flags = {
  forbid_self_approval: false, self_approval_position_id: null,
  self_skip_notify_position_ids: [], reject_comment_min: 0, lazy_resolution: false,
  no_executor_notify_position_ids: [],
};

describe('RouteFlagsForm', () => {
  it('включает правила БЗО одной кнопкой', async () => {
    const onSave = vi.fn();
    renderWithProviders(<RouteFlagsForm value={flags} onSave={onSave} />);
    await userEvent.click(screen.getByRole('button', { name: /правила модуля бзо/i }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      forbid_self_approval: true, reject_comment_min: 10, lazy_resolution: true,
    }));
  });

  it('минимум комментария — число от 0', async () => {
    const onSave = vi.fn();
    renderWithProviders(<RouteFlagsForm value={flags} onSave={onSave} />);
    const input = screen.getByLabelText(/символов комментария/i);
    await userEvent.clear(input);
    await userEvent.type(input, '15');
    await userEvent.click(screen.getByRole('button', { name: /сохранить правила/i }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ reject_comment_min: 15 }));
  });
});
```

Run (из `frontend/`): `npx vitest run src/components/signoff/RouteFlagsForm.test.tsx`
Expected: FAIL — нет компонента.

- [ ] **Step 2: Типы и компонент**

In `frontend/src/types/signoff.ts`:
- добавить интерфейс `RouteFlags` с шестью полями задачи 2 (`self_approval_position_id: number | null`, списки — `number[]`);
- расширить тип маршрута: `extends RouteFlags`;
- добавить `'no_executor'` в тип состояния этапа.

In `frontend/src/components/signoff/states.tsx` — подпись `no_executor`: `t('signoff.stage.noExecutor', 'Нет исполнителя')`, предупреждающий цвет.

Create `frontend/src/components/signoff/RouteFlagsForm.tsx`:
- три переключателя: «Запрет самосогласования», «Исполнитель — при активации этапа», и число «Минимум символов комментария при отказе»;
- выбор должностей для «Кому уходит этап автора» и двух списков уведомлений — через существующий `PositionPicker` (`frontend/src/components/signoff/PositionPicker.tsx`);
- кнопка «Правила модуля БЗО» ставит `forbid_self_approval=true`, `reject_comment_min=10`, `lazy_resolution=true` и вызывает `onSave`;
- кнопка «Сохранить правила» вызывает `onSave(текущие значения)`.

Пропсы: `{ value: RouteFlags; onSave: (next: RouteFlags) => void; disabled?: boolean }`. Все строки — через `t('signoff.routeFlags.*', '…')`, у числа — `<Label htmlFor>` с текстом «Минимум символов комментария при отказе».

In `RouteEditorPanel.tsx` — показать `RouteFlagsForm` над списком этапов. `onSave` вызывает мутацию правки маршрута (тот же вызов API, что меняет `name`/`is_active`) с флагами в теле. После успеха — инвалидировать запрос маршрута.

Run: `npx vitest run src/components/signoff && npm run lint && npx tsc --noEmit -p tsconfig.app.json | grep -c "error TS"`
Expected: тесты PASS, линт без новых ошибок, число ошибок typecheck не выросло.

- [ ] **Step 3: Коммит**

```bash
git add frontend/src/types/signoff.ts frontend/src/api/signoff.ts frontend/src/components/signoff
git commit -m "feat(signoff): правила маршрута в редакторе — самосогласование, комментарий, ленивое разрешение"
```

---

## Task 6: API движка для модуля — массовые решения, «Сейчас у», «ждёт меня», сводка

**Files:**
- Modify: `backend/apps/signoff/interface.py` (`decide_many`, `current_holders`, `pending_for_user`), `backend/apps/signoff/apps.py` (регистрация источника сводки), `backend/apps/signoff/services/presentation.py` (переиспользование `describe_many`)
- Test: `backend/apps/signoff/tests/test_module_api.py`

**Interfaces:**
- Consumes: `ApprovalProcessStage.activated_at` (задача 4).
- Produces (мастер-план §2.6):
  - `decide_many(*, actor_id: int, items: list[dict]) -> list[dict]` — `items`: `{task_id, decision, comment, option_key?}`; ответ: `{task_id, ok, error?}`. Каждое решение — в своей транзакции;
  - `current_holders(subject_type: str, subject_ids: list[str]) -> dict[str, dict]` — `{sid: {stage, users: [{id, name}], position, since}}` только для идущих процессов;
  - `pending_for_user(user_id: int) -> list[dict]` — `{task_id, subject_type, subject_id, title, url, since}`;
  - регистрация `notifications.register_digest_source("signoff.pending", …, tenant=True)`, если `apps.notifications` установлена и функция есть.

- [ ] **Step 1: Падающие тесты**

Create `backend/apps/signoff/tests/test_module_api.py`:

```python
"""Интерфейс движка для модуля БЗО (мастер-план §2.6)."""

import pytest

from apps.signoff import interface
from apps.signoff.models import Quorum
from apps.signoff.services import engine
from apps.signoff.tests.helpers import SUBJECT, make_doc, make_route, make_user, task_for
from apps.signoff.tests.testapp import hooks

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset():
    hooks.reset()
    yield
    hooks.reset()


def test_decide_many_keeps_successes():
    a, b = make_user("a"), make_user("b")
    make_route([(1, "Один", Quorum.ALL, [a.pk])])
    mine1 = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    mine2 = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    other = make_doc()
    results = interface.decide_many(actor_id=a.pk, items=[
        {"task_id": task_for(mine1, a.pk).pk, "decision": "approve", "comment": ""},
        {"task_id": 999999, "decision": "approve", "comment": ""},
        {"task_id": task_for(mine2, a.pk).pk, "decision": "approve", "comment": ""},
    ])
    assert [r["ok"] for r in results] == [True, False, True]
    assert results[1]["error"]
    assert interface.approval_state_of(SUBJECT, other.pk) == "draft"


def test_current_holders_shows_who_and_since():
    a = make_user("a")
    make_route([(1, "Проверка ТД", Quorum.ALL, [a.pk])])
    doc = make_doc()
    engine.start(subject_type=SUBJECT, subject_id=doc.pk)
    holders = interface.current_holders(SUBJECT, [str(doc.pk)])[str(doc.pk)]
    assert holders["stage"] == "Проверка ТД"
    assert [u["id"] for u in holders["users"]] == [a.pk]
    assert holders["since"]


def test_current_holders_omits_finished_processes():
    a = make_user("a")
    make_route([(1, "Один", Quorum.ALL, [a.pk])])
    doc = make_doc()
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)
    assert interface.current_holders(SUBJECT, [str(doc.pk)]) == {}


def test_pending_for_user():
    a = make_user("a")
    make_route([(1, "Один", Quorum.ALL, [a.pk])])
    doc = make_doc(title="Пробный счёт")
    engine.start(subject_type=SUBJECT, subject_id=doc.pk)
    rows = interface.pending_for_user(a.pk)
    assert [(r["subject_id"], r["title"]) for r in rows] == [(str(doc.pk), "Пробный счёт")]
    assert rows[0]["url"] == f"/probe/{doc.pk}" and rows[0]["since"]


def test_digest_registration_is_optional():
    """В ветке без apps.notifications регистрация молча пропускается."""
    from django.apps import apps as django_apps

    from apps.signoff.apps import register_digest_source_if_available

    assert register_digest_source_if_available() is \
        django_apps.is_installed("apps.notifications")
```

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests/test_module_api.py -q`
Expected: FAIL — нет `decide_many`.

- [ ] **Step 2: Функции интерфейса**

In `backend/apps/signoff/interface.py`:

```python
def decide_many(*, actor_id: int, items: list[dict]) -> list[dict]:
    """Решения пачкой — каждое в своей транзакции (Q-C13): отказ по одному
    (не ваш запрос, уже закрыт) не откатывает остальные."""
    require_service("signoff")
    from django.http import Http404

    results = []
    for item in items:
        try:
            engine.act(task_id=int(item["task_id"]), actor_id=actor_id,
                       decision=item["decision"], comment=item.get("comment") or "")
            results.append({"task_id": item["task_id"], "ok": True})
        except (Http404, engine.SignoffError, UnknownSubject) as exc:
            results.append({"task_id": item["task_id"], "ok": False, "error": str(exc)})
    return results


def current_holders(subject_type: str, subject_ids: list) -> dict[str, dict]:
    """«Сейчас у»: этап, согласующие, должность, с какого времени (REQ-031)."""
    require_service("signoff")
    from apps.hr import interface as hr
    from apps.users import interface as users
    from apps.signoff.models import ApprovalTask

    keys = [registry.storage_key(subject_type, sid) for sid in subject_ids]
    tasks = list(ApprovalTask.objects.select_related("stage", "stage__process")
                 .filter(state=TaskState.PENDING, stage__state=StageState.ACTIVE,
                         stage__process__state=ProcessState.PENDING,
                         stage__process__subject_type=subject_type,
                         stage__process__subject_id__in=keys))
    names = {row["id"]: row["full_name"] for row in
             users.get_users_brief({t.user_id for t in tasks})}
    positions = {row["id"]: row["title"] for row in
                 hr.get_positions_brief([t.position_id for t in tasks if t.position_id])}
    out: dict[str, dict] = {}
    for task in tasks:
        sid = task.stage.process.subject_id
        entry = out.setdefault(sid, {
            "stage": task.stage.name, "users": [],
            "position": positions.get(task.position_id),
            "since": (task.stage.activated_at or task.stage.process.created_at).isoformat(),
        })
        entry["users"].append({"id": task.user_id, "name": names.get(task.user_id)})
    return out


def pending_for_user(user_id: int) -> list[dict]:
    """Что ждёт решения пользователя в текущей компании — для сводки (D-23)."""
    require_service("signoff")
    from apps.signoff.models import ApprovalTask

    tasks = list(ApprovalTask.objects.select_related("stage", "stage__process")
                 .filter(user_id=user_id, state=TaskState.PENDING,
                         stage__state=StageState.ACTIVE,
                         stage__process__state=ProcessState.PENDING)
                 .order_by("stage__activated_at", "id"))
    described = presentation.describe_many(
        [(t.stage.process.subject_type, t.stage.process.subject_id) for t in tasks])
    rows = []
    for task in tasks:
        process = task.stage.process
        info = described.get((process.subject_type, process.subject_id), {})
        rows.append({"task_id": task.pk, "subject_type": process.subject_type,
                     "subject_id": process.subject_id, "title": info.get("title"),
                     "url": info.get("url"),
                     "since": (task.stage.activated_at or process.created_at).isoformat()})
    return rows
```

⚠️ Имена `TaskState`, `StageState`, `ProcessState`, `UnknownSubject`, `presentation`, `registry` в `interface.py` уже импортированы (строки 29–49) — проверить и дополнить.

- [ ] **Step 3: Источник ежедневной сводки**

In `backend/apps/signoff/apps.py` добавить функцию модуля и вызов из `ready()`:

```python
def register_digest_source_if_available() -> bool:
    """Отдать очередь «ждёт меня» ежедневной сводке центра уведомлений (D-23).

    Центр уведомлений (``apps.notifications``) — в ветке исполнителя A; до
    мерджа веток его здесь нет, и регистрация молча пропускается. После
    мерджа связь включается сама — без правки этого файла.
    """
    from django.apps import apps as django_apps

    if not django_apps.is_installed("apps.notifications"):
        return False
    from apps.notifications import interface as notifications

    if not hasattr(notifications, "register_digest_source"):
        return False
    from . import interface

    notifications.register_digest_source(
        "signoff.pending",
        lambda user_id: [{"title": row["title"] or row["subject_type"],
                          "url": row["url"] or f"/signoff/tasks/{row['task_id']}",
                          "since": row["since"]}
                         for row in interface.pending_for_user(user_id)],
        tenant=True)
    return True
```

В `SignoffConfig.ready()` добавить `register_digest_source_if_available()`.

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests apps/core/tests/test_app_isolation.py -q`
Expected: всё PASS.

- [ ] **Step 4: Коммит**

```bash
git add backend/apps/signoff
git commit -m "feat(signoff): решения пачкой, «Сейчас у», очередь «ждёт меня» и её регистрация в ежедневной сводке"
```

---

## Task 7: Выбор варианта и предсогласованные этапы

**Files:**
- Modify: `backend/apps/signoff/models.py` (`ApprovalRouteStage.choose_option`, `ApprovalProcessStage.choose_option`, `ApprovalTask.option_key`)
- Create migration: `backend/apps/signoff/migrations/0015_options.py` (makemigrations)
- Modify: `backend/apps/signoff/services/registry.py` (`Subject.options`, `Subject.on_option`, параметры `register_subject`), `services/engine.py` (`act(..., option_key=None)`, `start(..., preapproved=None)`), `interface.py` (`start_process(..., preapproved=None)`), `schemas.py` (`Decision.option_key`, этап — `choose_option`), `views.py` (передача `option_key`), `services/route_service.py` (поле этапа)
- Modify: `backend/apps/signoff/tests/testapp/hooks.py` (варианты у пробного документа)
- Test: `backend/apps/signoff/tests/test_options.py`

**Interfaces:**
- Produces (Q-C12, D-26):
  - `register_subject(..., options=fn(subject_id) -> list[{key, label}], on_option=fn(subject_id, stage_order, user_id, option_key))`;
  - этап маршрута `choose_option: bool`;
  - `act(..., option_key: str | None = None)` — на этапе с выбором `approve` требует `option_key` из `options()`;
  - `start_process(..., preapproved: list[{"order": int, "comment": str}] | None)` — этапы с этими `order` создаются согласованными, с событием `preapproved`.

- [ ] **Step 1: Падающие тесты**

Create `backend/apps/signoff/tests/test_options.py`:

```python
"""Голос за вариант и предсогласованные этапы (Q-C12, D-26)."""

import pytest

from apps.signoff.models import (ApprovalEvent, ApprovalRouteStage, ApprovalTask, Quorum,
                                 StageState)
from apps.signoff.services import engine
from apps.signoff.tests.helpers import SUBJECT, make_doc, make_route, make_user, stage_states, task_for
from apps.signoff.tests.testapp import hooks

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset():
    hooks.reset()
    yield
    hooks.reset()


def _choosing_route(user):
    route = make_route([(1, "Выбор", Quorum.ALL, [user.pk])])
    ApprovalRouteStage.objects.filter(route=route).update(choose_option=True)
    return route


def test_approve_needs_a_known_option():
    gd = make_user("gd")
    _choosing_route(gd)
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    task = task_for(process, gd.pk)
    with pytest.raises(engine.OptionRequired):
        engine.act(task_id=task.pk, actor_id=gd.pk, decision=engine.APPROVE)
    with pytest.raises(engine.OptionRequired):
        engine.act(task_id=task.pk, actor_id=gd.pk, decision=engine.APPROVE,
                   option_key="нет-такого")
    engine.act(task_id=task.pk, actor_id=gd.pk, decision=engine.APPROVE, option_key="alt-1")
    assert ApprovalTask.objects.get(pk=task.pk).option_key == "alt-1"
    assert ("option", "alt-1") in [(c[0], c[2]) for c in hooks.OPTION_CALLS]


def test_stage_without_choice_ignores_option():
    a = make_user("a")
    make_route([(1, "Обычный", Quorum.ALL, [a.pk])])
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)


def test_preapproved_stages():
    fd, gd = make_user("fd"), make_user("gd")
    make_route([(1, "ФД", Quorum.ALL, [fd.pk]), (2, "ГД", Quorum.ALL, [gd.pk])])
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk,
                           preapproved=[{"order": 2,
                                         "comment": "Согласовано при выборе альтернативы"}])
    assert stage_states(process) == [StageState.ACTIVE, StageState.APPROVED]
    assert not ApprovalTask.objects.filter(stage__process=process, stage__order=2).exists()
    assert ApprovalEvent.objects.filter(process=process, kind="preapproved").exists()
    engine.act(task_id=task_for(process, fd.pk).pk, actor_id=fd.pk, decision=engine.APPROVE)
    assert process.__class__.objects.get(pk=process.pk).state == "approved"
```

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests/test_options.py -q`
Expected: FAIL — нет `choose_option`.

- [ ] **Step 2: Модели, реестр, пробный документ**

In `backend/apps/signoff/models.py`:
- `ApprovalRouteStage` и `ApprovalProcessStage`: `choose_option = models.BooleanField(default=False, db_default=False)` («на этапе выбирают вариант, объявленный объектом»);
- `ApprovalTask`: `option_key = models.CharField(max_length=64, default="", blank=True, db_default="")`.

Миграция `0015_options` (makemigrations). В `start` при создании этапа снимка копировать `choose_option=stage.choose_option`.

In `backend/apps/signoff/services/registry.py`:
- в `Subject` добавить `options: Callable[[Any], list[dict]] | None = None` и `on_option: Callable[[Any, int, int, str], None] | None = None`;
- в `register_subject` — параметры `options=None, on_option=None`, передать в `Subject(...)`;
- функция `options_for(subject_type: str, subject_id) -> list[str]` — ключи вариантов (`[]`, если `options` не задан), ключ объекта через `_native`.

In `backend/apps/signoff/tests/testapp/hooks.py`:

```python
OPTION_CALLS: list[tuple] = []


def _options(subject_id) -> list[dict]:
    return [{"key": "source", "label": "Исходный документ"},
            {"key": "alt-1", "label": "Альтернатива 1"}]


def _on_option(subject_id, stage_order: int, user_id: int, option_key: str) -> None:
    OPTION_CALLS.append(("option", subject_id, option_key))
```

`reset()` чистит `OPTION_CALLS`; регистрация `ProbeDoc` получает `options=_options, on_option=_on_option`.

- [ ] **Step 3: Движок**

In `backend/apps/signoff/services/engine.py`:

1. Исключение:

```python
class OptionRequired(SignoffError):
    """На этапе выбора варианта согласование — только с одним из вариантов объекта."""
```

2. `act(..., option_key: str | None = None)`: перед записью решения, при `decision == APPROVE and stage.choose_option`:

```python
        allowed = registry.options_for(process.subject_type, process.subject_id)
        if option_key not in allowed:
            raise OptionRequired(
                f"На этапе «{stage.name}» выберите вариант: " + ", ".join(allowed))
```

После `task.save(...)`: при заданном варианте — `task.option_key = option_key` (добавить в `update_fields`) и вызвать колбэк:

```python
    if decision == APPROVE and stage.choose_option:
        subject = registry.get_subject(process.subject_type)
        if subject.on_option is not None:
            subject.on_option(registry.native_id(process.subject_type, process.subject_id),
                              stage.order, actor_id, option_key)
```

(колбэк — внутри транзакции решения: доменная запись голоса обязана откатиться вместе с решением).

3. `start(..., preapproved: list[dict] | None = None)`: порядковые номера из `preapproved` — множество `pre_orders`, комментарии — словарь. Этапы плана с `order in pre_orders` создаются в `StageState.APPROVED` без задач, и для каждого — `_log(process, "preapproved", actor_id=initiator_id, payload={"stage": stage.name, "comment": comment})`. `first_order` — минимальный `order` среди не предсогласованных и не пропущенных этапов. Если таких нет — `_skip_forward`/`_advance` из задачи 3 доводит процесс до конца. В `_skip_forward` и `_advance` «закрытой» считается группа, где каждый этап `APPROVED` или `SKIPPED`.

In `backend/apps/signoff/interface.py`, `start_process(..., preapproved: list[dict] | None = None)` — передать в `engine.start`.

In `schemas.py`: `Decision.option_key: Optional[str] = Field(None, max_length=64)`; `StageCreate`/`StageUpdate`/`StageRead` — `choose_option: bool`. In `views.py` передать `option_key=data.option_key` в `engine.act`; `OptionRequired` — в `CONFLICTS`, ответ 409. In `route_service.add_stage/update_stage/serialize_stage` — поле `choose_option`.

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests apps/contracts/tests apps/approvals/tests -q`
Expected: всё PASS (известные падения из `backend/ci-known-failures.txt` исключить, как в CI).

- [ ] **Step 4: Документация и коммит**

`STRUCTURE.md` §3.6 (signoff) — дописать абзац:

```markdown
**Флаги маршрута (с этапа 1 БЗО, выключены по умолчанию):** `forbid_self_approval` + `self_approval_position_id` + `self_skip_notify_position_ids` (BR-061), `reject_comment_min` (BR-060, 422), `lazy_resolution` + `no_executor_notify_position_ids` (исполнитель — при активации этапа, `StageState.NO_EXECUTOR`, перепроверка `signoff.resolve_waiting_dispatch` каждые 15 минут). Снимок флагов — `ApprovalProcess.route_flags`. Этап с `choose_option` требует вариант из `Subject.options` и зовёт `on_option`; `start_process(preapproved=[{order, comment}])` создаёт этапы согласованными. Для модуля: `decide_many`, `current_holders` («Сейчас у»), `pending_for_user` — источник ежедневной сводки центра уведомлений.
```

```bash
git add backend/apps/signoff STRUCTURE.md
git commit -m "feat(signoff): голос за вариант объекта и предсогласованные этапы"
```

---

## После этапа

- [ ] Полный прогон backend (с исключением известных падений, как в `.github/workflows/backend-full.yml`) и `npx vitest run` — зелёные, кроме падений, которые воспроизводятся на базовом коммите.
- [ ] Финальное ревью ветки отдельным ревьюером.
- [ ] Диф `apps/signoff` и `apps/hr` отправлен A на подтверждение (мастер-план §0, правило 3).
