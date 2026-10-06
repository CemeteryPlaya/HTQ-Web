# Проектная структура сотрудников — план реализации (подпроект 1)

> **Для исполнителя:** выполнять по задачам, по порядку; шаги — чекбоксы. Исполнение — в этой сессии (native, superpowers:executing-plans), ветка `sanzhar`, веток не создавать.

**Цель:** у каждого «Проекта» — своя структура людей: справочник проектных ролей L1–L4, места с подчинением и планом, датированные назначения сотрудников, экран-оргсхема на карточке проекта.

**Архитектура:** три новые модели в тенантной `apps.project` (`ProjectRole`, `ProjectSlot`, `ProjectAssignment`), логика — `apps/project/services/structure.py`, ручки — `apps/project/views_structure.py` (под `api_view(module="project", …)`), права — узлы `project.structure`/`project.roles` (`EXPLICIT_ONLY`, миграция `access/0024`). Сотрудники — только через `hr.interface` (новая функция чтения `employees_brief`), `hr` не меняется. Фронт — секция «Структура проекта» на карточке и страница «Проектные роли» в `features/bpp/projects`.

**Стек:** Django 5.2.7 / Python 3.14 (корневой `.venv`), pytest-django на Postgres `:55432`; React + Vite + TanStack Query, vitest.

**Спек:** [2026-10-06-project-structure-spec.md](2026-10-06-project-structure-spec.md).

## Global Constraints

- `hr` не меняется, кроме одной функции чтения в `apps/hr/interface.py`; соседи — только через `apps.<x>.interface` (сторож `test_app_isolation`).
- Каждая ручка — `api_view(module="project", level="read"|"write")` с явным `level=`; диспетчеры в `urls.py`/`views_*.py` — голые цепочки по `request.method` (сторож `test_gate.py`); оба написания пути — со слэшем и без.
- Ошибки: `E-PRJ-05` 409 — правила дерева/плана/дат; `E-PRJ-06` 422 — сотрудник не действующий / не найден; `E-PRJ-07` 409 — справочник ролей; 403 `E-ACC-01` — нет права; 404 — невидимый проект.
- Узлы `project.structure` и `project.roles` — флаг `("edit",)`, `EXPLICIT_ONLY`; строки `can_edit` у `bpp-fd`, `bpp-td`, `bpp-od`, `bpp-gd`, `bpp-adm`, `hr-lead`, пустые — у остальных системных ролей, кроме `platform-admin` (образец `access/0022`).
- Тенантная аппка: миграции expand-only; data-сид справочника — только в схеме `co_*` и только в пустую таблицу (приём `hr/0024`).
- Тесты — по одному прогону pytest за раз, интерпретатор `../.venv/Scripts/python.exe` (3.14).
- Число ошибок `npx tsc --noEmit -p tsconfig.app.json` после правки не больше, чем до.

## Review Focus

1. Руководитель проекта без узла `project.structure`, но с `project:write` правит **свой** проект и получает 403 на чужом — тест в задаче 5.
2. Держатель `project.structure` без `project.all` (например `hr-lead`) видит любой проект (иначе «правит любой» не работает — `_project` отдал бы 404) — тест в задаче 5.
3. Назначение на место с планом 1, когда старое назначение закрыто вчера, — разрешено (пересечение дат считается включительно, но не дальше `date_to`) — тест в задаче 3.
4. Удаление «Проекта» (`project.interface.delete_project`) со структурой не падает на `PROTECT` подчинения мест — `parent` объявлен `RESTRICT`, тест в задаче 1.
5. Сотрудник, удалённый из кадров мягко (`is_deleted`), на схеме — «уволен», а не исчезает и не роняет ответ — тест в задаче 3.

---

### Задача 1: модели и миграции `project`

**Файлы:**
- Изменить: `backend/apps/project/models.py`
- Создать: `backend/apps/project/migrations/0004_project_structure.py` (`makemigrations`), `backend/apps/project/migrations/0005_seed_project_roles.py`
- Тест: `backend/apps/project/tests/test_structure_models.py`

**Производит:** `ProjectPart` (`office`/`site`), `ProjectRole(name, level, default_part, sort_order, is_active)`, `ProjectSlot(id UUID, project, role, part, title, parent, planned_headcount, closed_on, created_by)`, `ProjectAssignment(id UUID, slot, employee_id, date_from, date_to, created_by)`; related names `project.slots`, `role.slots`, `slot.children`, `slot.assignments`.

- [ ] Тесты: (а) `CheckConstraint` уровня роли 1…4 и `planned_headcount ≥ 1`, `date_to ≥ date_from`; (б) `Project.objects.filter(pk=…).delete()` с деревом из двух мест и назначением проходит (parent — `RESTRICT`); (в) `seed` из `0005` в схеме компании при пустой таблице заводит 5 ролей, при непустой — ничего, в `public` — ничего.
- [ ] Прогнать — падают (нет моделей).
- [ ] Модели:

```python
class ProjectPart(models.TextChoices):
    OFFICE = "office", "Офис"
    SITE = "site", "Объект"


class ProjectRole(models.Model):
    name = models.CharField(max_length=100, unique=True)
    level = models.PositiveSmallIntegerField()
    default_part = models.CharField(max_length=8, choices=ProjectPart.choices,
                                    default=ProjectPart.OFFICE, db_default=ProjectPart.OFFICE.value)
    sort_order = models.IntegerField(default=0, db_default=0)
    is_active = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("level", "sort_order", "name")
        constraints = [models.CheckConstraint(condition=models.Q(level__gte=1, level__lte=4),
                                              name="ck_project_role_level")]


class ProjectSlot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="slots")
    role = models.ForeignKey(ProjectRole, on_delete=models.PROTECT, related_name="slots")
    part = models.CharField(max_length=8, choices=ProjectPart.choices)
    title = models.CharField(max_length=255, default="", blank=True)
    parent = models.ForeignKey("self", on_delete=models.RESTRICT, null=True, blank=True,
                               related_name="children")
    planned_headcount = models.PositiveSmallIntegerField(default=1, db_default=1)
    closed_on = models.DateField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(planned_headcount__gte=1),
                                              name="ck_project_slot_planned")]


class ProjectAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slot = models.ForeignKey(ProjectSlot, on_delete=models.CASCADE, related_name="assignments")
    employee_id = models.IntegerField(db_index=True)
    date_from = models.DateField()
    date_to = models.DateField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        constraints = [models.CheckConstraint(
            condition=models.Q(date_to__isnull=True) | models.Q(date_to__gte=models.F("date_from")),
            name="ck_project_assignment_dates")]
```

- [ ] `makemigrations project` → `0004_project_structure.py`; `0005_seed_project_roles.py` — `seed` по образцу `hr/0024` (`_in_company_schema` по первому элементу `search_path`, `SCHEMA_PREFIX`, `.using(connection.alias)`, обратная — `noop`), роли: («Руководитель проекта (ГД)», 1, office, 10), («Заместитель директора», 2, office, 20), («Технический директор», 2, office, 30), («Специалист», 3, office, 40), («Рабочий», 4, site, 50).
- [ ] Тесты зелёные; коммит.

### Задача 2: `hr.interface.employees_brief` (только чтение)

**Файлы:** изменить `backend/apps/hr/interface.py`; тест `backend/apps/hr/tests/test_interface_employees_brief.py`.

**Производит:** `employees_brief(ids: list[int] | None = None, *, query: str = "", limit: int = 20) -> list[dict]` — элементы `{"id", "full_name", "user_id", "position_title", "active"}`. С `ids` — эти сотрудники, включая уволенных и мягко удалённых (`active=False`); без `ids` — поиск действующих (`status=active`, не удалён) по словам запроса в фамилии/имени/отчестве, сортировка по ФИО, не больше `limit`.

- [ ] Тест: по `ids` приходят действующий (`active=True`), уволенный (`status=terminated`) и удалённый (`is_deleted`) — оба `active=False`; поиск «Ив Пет» находит «Иванов Пётр» и не находит уволенного; `limit` соблюдается.
- [ ] Реализация:

```python
def employees_brief(ids: list[int] | None = None, *, query: str = "",
                    limit: int = 20) -> list[dict]:
    """Сотрудники для проектной структуры (``apps.project``): по списку ``id``
    (включая уволенных — схема проекта помечает их, а не теряет) или поиском
    действующих по ФИО. Только чтение; кадровых прав вызывающего не требует —
    права решает вызывающая аппка."""
    require_service("hr")
    rows = Employee.objects.select_related("position")
    if ids is not None:
        rows = rows.filter(id__in=list(ids))
    else:
        rows = rows.filter(is_deleted=False, status=EmployeeStatus.ACTIVE)
        for word in query.split():
            rows = rows.filter(Q(last_name__icontains=word) | Q(first_name__icontains=word)
                               | Q(middle_name__icontains=word))
        rows = rows.order_by("last_name", "first_name", "id")[:limit]
    return [{
        "id": e.id,
        "full_name": " ".join(p for p in (e.last_name, e.first_name, e.middle_name or "") if p),
        "user_id": e.user_id,
        "position_title": e.position.title,
        "active": (not e.is_deleted) and e.status == EmployeeStatus.ACTIVE,
    } for e in rows]
```

- [ ] Тест зелёный; коммит.

### Задача 3: сервис структуры

**Файлы:** создать `backend/apps/project/services/structure.py`; тест `backend/apps/project/tests/test_structure_service.py`.

**Потребляет:** модели задачи 1, `hr.interface.employees_brief`, `services.projects.add_member`.

**Производит:**
- исключения `StructureError` (→ `E-PRJ-05` 409), `EmployeeError` (→ `E-PRJ-06` 422), `RoleError` (→ `E-PRJ-07` 409);
- `list_roles(active_only=False) -> list[dict]`, `create_role(*, name, level, default_part, sort_order=0) -> dict`, `update_role(role: ProjectRole, **fields) -> dict`, `role_out(role) -> dict`;
- `create_slot(project, *, role_id, actor_id, parent_id=None, part=None, title="", planned_headcount=1) -> ProjectSlot`, `update_slot(slot, *, actor_id, **fields) -> ProjectSlot` (ключи: `parent_id`, `part`, `title`, `planned_headcount`, `closed_on`);
- `create_assignment(slot, *, employee_id, date_from, actor_id, date_to=None) -> ProjectAssignment`, `update_assignment(assignment, *, actor_id, **fields)`, `delete_assignment(assignment, *, today)`;
- `structure(project, on: date) -> list[dict]` — места (открытые на `on`) с назначениями, действующими на `on`.

Правила (все записи — в `transaction.atomic` под `select_for_update` строки проекта):
- роль места — действующая; `parent` — открытое место того же проекта с уровнем роли строго меньше; без `parent` — только L1 (цикл при строгом убывании уровня невозможен — отдельной проверки нет, тест «подчинённого назначить руководителем» падает на уровне);
- закрытое место не правится; закрыть нельзя при назначениях с `date_to` пусто или `≥ closed_on` и при открытых подчинённых;
- план не ниже числа назначений, действующих сегодня;
- назначение: сотрудник найден и `active`, место открыто, тот же сотрудник на месте без пересечения дат, лимит плана на всём периоде (точки проверки — `date_from` и `date_from` пересекающихся назначений), сотрудник с `user_id` — в участники проекта;
- удалить — только `date_from > today`.

- [ ] Тесты (по одному на правило выше + «закрытое вчера назначение не мешает новому на плане 1» + «уволенный и удалённый в `structure` — `dismissed=True`» + «совмещение двух мест одним сотрудником» + «`structure` на дату не отдаёт закрытые места и назначения вне периода» + «справочник: смена уровня и удаление используемой роли — `RoleError`»).
- [ ] Реализация (ядро):

```python
def _overlapping(qs, date_from, date_to):
    qs = qs.filter(Q(date_to__isnull=True) | Q(date_to__gte=date_from))
    return qs if date_to is None else qs.filter(date_from__lte=date_to)


def _check_capacity(slot, date_from, date_to, exclude_id=None):
    others = list(_overlapping(slot.assignments.exclude(pk=exclude_id), date_from, date_to))
    points = {date_from} | {a.date_from for a in others if a.date_from > date_from}
    for point in points:
        busy = sum(1 for a in others if a.date_from <= point and (a.date_to is None or a.date_to >= point))
        if busy >= slot.planned_headcount:
            raise StructureError(f"На месте уже {busy} из {slot.planned_headcount} по плану на "
                                 f"{point:%d.%m.%Y} — сначала увеличьте план.")
```

- [ ] Тесты зелёные; коммит.

### Задача 4: права — узлы и миграция `access/0024`

**Файлы:** изменить `backend/apps/project/access_functions.py`; создать `backend/apps/access/migrations/0024_project_structure_nodes.py`; тест `backend/apps/access/tests/test_project_structure_nodes.py`.

- [ ] Тест: у каждой системной роли, кроме `platform-admin`, есть строки обоих узлов; `edit` ровно у шести ролей Global Constraints, у остальных флагов нет; узлы в `registry.explicit_only()`; держатель `project:admin` без строки — `flags_for(... "project.structure")` пуст.
- [ ] `FUNCTIONS += (("project.structure", "Структура любого проекта: правка", ("edit",)), ("project.roles", "Справочник проектных ролей: правка", ("edit",)))`, `EXPLICIT_ONLY = frozenset({"project.structure", "project.roles"})`.
- [ ] Миграция — копия `0022` с `NODES = ("project.structure", "project.roles")`, `EDITORS`, зависимость `("access", "0023_bpp_holding_node")`.
- [ ] Тесты + `apps/access/tests/test_bpp_roles.py` + `test_backfill_positions.py` зелёные; коммит.

### Задача 5: API

**Файлы:** изменить `backend/apps/project/schemas.py`, `backend/apps/project/urls.py`, `backend/apps/project/views.py` (`_sees_all`); создать `backend/apps/project/views_structure.py`; тест `backend/apps/project/tests/test_structure_api.py`.

**Производит (пути от `/api/project/v1/`):** `GET|POST project-roles`, `PATCH project-roles/<int:role_id>`, `GET projects/<id>/structure?on=`, `POST projects/<id>/slots`, `PATCH slots/<id>`, `POST slots/<id>/assignments`, `PATCH|DELETE assignments/<id>`, `GET employees?q=`. Ответ `structure`: `{project_id, on, can_edit, slots: [...]}` по спеку §4.

Права:
- `_sees_all(request)` = `project.all:view` **или** `project.structure:edit` (Review Focus 2);
- правка структуры = `project.manager_user_id == user_id` или `project.structure:edit`, иначе 403 `E-ACC-01`;
- справочник: чтение — `project:read`, правка — `project.roles:edit`;
- `employees` — держатель `project.structure:edit` или руководитель хоть одного проекта, иначе 403.

- [ ] Тесты: каждый путь (201/200/204), коды `E-PRJ-05/06/07`, 403 участнику на запись, 404 невидимому, Review Focus 1–2, `structure` с `can_edit`, `employees` 403 рядовому.
- [ ] Реализация; `test_structure_api.py`, `apps/project/tests`, `apps/access/tests/test_gate.py`, `apps/core/tests/test_app_isolation.py` зелёные; коммит.

### Задача 6: фронт

**Файлы:** создать `frontend/src/features/bpp/projects/structureApi.ts`, `ProjectStructureSection.tsx`, `ProjectStructureSection.test.tsx`, `ProjectRolesPage.tsx`, `ProjectRolesPage.test.tsx`; изменить `ProjectCardPage.tsx` (секция под участниками), `ProjectsPage.tsx` (кнопка «Проектные роли» при `can('project.roles','edit')`), `module.tsx` (маршрут `projects/roles` перед `projects/:id`).

Отступления от спека §5 (сознательные, упрощение): «вкладка» — секция на карточке (у карточки нет вкладок); «линии к руководителю» — подпись «↑ руководитель: …» на карточке места; страница ролей — кнопкой со списка проектов (у подмодуля один пункт меню).

- [ ] Тесты: ярусы L1–L4 с подписями, фильтр «Офис/Объект», «вакансия» при факте 0, «уволен», место с планом > 3 свёрнуто и раскрывается, кнопки правки только при `can_edit`; страница ролей — список и форма добавления, без права — «Недостаточно прав».
- [ ] Реализация; `npx vitest run src/features/bpp/projects`, `npm run lint`, `npx tsc --noEmit -p tsconfig.app.json` (сверка числа ошибок); коммит.

### Задача 7: документы и сквозная проверка

**Файлы:** `API.md` (раздел «Проектная структура»), `STRUCTURE.md` (аппка `project`), `CLAUDE.md` (абзац под «Модулем БЗО»: модели, узлы, `migrate_companies`).

- [ ] Прогон: `apps/project apps/access apps/hr/tests/test_interface_employees_brief.py apps/core/tests/test_app_isolation.py apps/core/tests/test_invariants.py` — зелёные; фронт — vitest целиком по `features/bpp`.
- [ ] Коммит документов.
