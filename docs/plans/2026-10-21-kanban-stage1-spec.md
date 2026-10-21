# Канбан-доски — спецификация этапа 1: видимость и права (K1.1 … K1.5)

21.10.2026 · ветка `sanzhar` @ `218b62dc` · поверх [мастер-плана](2026-10-21-kanban-boards-master-plan.md) (решения K-01…K-33, ответы заказчика 21.10). Порядок старшинства — мастер-план → эта спека. Новые решения этапа — **S1-01…S1-27** (§6; S1-15…S1-27 — по итогам трёх проверок плана 21.10); открытых вопросов к заказчику у этапа нет.

**Цель этапа.** Бэкенд видимости и прав, на котором потом стоят доски: сотрудник видит все задачи своего отдела и подотделов, глава отдела правит и переносит задачи своего поддерева, ОД и ГД видят все доски отделов и проектов со всеми задачами, держатели «Доски задач проекта» видят задачи внутри досок. Плюс «Взять в работу» и перенос в другой отдел. Досок как ручек, порядка карточек, чек-листов, уведомлений участникам и запросов доступа в этапе нет — это этапы 2–3.

**Что есть в коде на 21.10** (подробно — мастер-план §2):
- Видимость задачи — `task_service.visibility_q` (`tasks/services/task_service.py:136-147`): `elevated` — всё; иначе `_participant_q` (`:85-94`: исполнитель, автор, руководитель, соисполнители, делегаты, наблюдатели) + неразобранные `backlog`/`todo` основного отдела (`:117-124`). Отдел сотрудника — `hydration.employee_department_id` (`hydration.py:138-151`, `None` при выключенном `hr`).
- Права — `can_edit`/`can_progress` (`:296-311`) и `require_full_edit`/`require_soft_edit` (`:314-326`); все мутирующие ручки зовут `load_for_action(task_id, token)` (`:280-289`) — 40 мест в `tasks/views.py`.
- Узел `project.board` (`project/access_functions.py:13`) расширяет только список досок и роудмапов (`board_scope.py`, `project_service._visible` `:40-54`, `roadmap_service._visible` `:39-54`), задачи внутри — «по своим правилам».
- `create_task` принимает любой отдел, автора и начальный статус с клиента (`:394-398`, `:420`, `schemas.py:828-835`); `department_id` не в `TRACKED_FIELDS` (`:62-68`).
- «Принять» в `EmployeeTasks.tsx:63-78` шлёт `PATCH {assignee_id, status}` → полная правка → 403 у не-участника. Обе вкладки фильтруют первые 50 задач на клиенте (`:54-60`, `:87-106`).
- Последние миграции: `tasks/0026_engagement_bpp_agreement`, `access/0027_tender_roles`.

---

## 1. Сквозные правила

**`TaskScope` — один расчёт на запрос.** Видимость и права главы считаются из одного объекта (§K1.3), который строится один раз на запрос и кладётся на `request.task_scope = (company, user_id, scope)`, где `company` — `current_company_or_none()` в момент вызова (как у `access_resolution`, `http.py:180-202`) — приём `request.access_resolution` (`htqweb/http.py:201-203`): явный атрибут запроса, переиспользуется только при совпадении компании и `user_id` токена. Вне HTTP (сервисные вызовы, тесты сервисов) — `task_scope.build(token, company)` без кэша.

**Ошибки — `DomainError`** (`htqweb/errors.py:12-31` → `{detail, code, fields}`, `api_view` уже его разбирает, `http.py:254-258`). Прежние ответы `{"detail"}` не меняются: новые коды — только у новых правил.

| Код | Статус | Когда |
|---|---|---|
| `task_department_forbidden` | 403 | рядовой ставит отдел вне своего поддерева (создание, `PATCH`) |
| `task_department_use_transfer` | 422 | глава `PATCH`-ем уводит отдел задачи за пределы управляемых поддеревьев — для этого есть перенос (S1-13, S1-19) |
| `task_reporter_forbidden` | 422 | не-`elevated` меняет `reporter_id` в `PATCH` (S1-21) |
| `task_department_inactive` | 422 | отдел-цель неактивен или не существует |
| `task_transfer_forbidden` | 403 | перенос — не глава отдела задачи и не `elevated` |
| `task_transfer_terminal` | 409 | перенос `done`/`cancelled` |
| `task_transfer_same` | 422 | цель совпадает с текущим основным отделом |
| `task_transfer_assignees` | 422 | глава создаёт задачу в чужой отдел с исполнителями |
| `task_claim_unavailable` | 409 | «Взять в работу»: уже есть исполнитель или статус не `backlog`/`todo` |
| `task_claim_forbidden` | 403 | «Взять в работу» задачу не своего отдела (связь `origin`, «все отделы», доска проекта — S1-07) |
| `task_status_initial` | 422 | рядовой создаёт задачу сразу не в `backlog`/`todo` |

**`hr` выключен.** `TaskScope` при выключенном `hr` (`ServiceDisabled` из `require_service`) — без отдела и без управляемых отделов: видимость сужается до участия и досок проектов (fail-closed, как сейчас `hydration._safe`), через `htqweb.fallback(..., expected=True)` с сайтом `tasks.task_scope.hr_unavailable`. Запись с отделом (создание, `PATCH` отдела, перенос) при выключенном `hr` — 503 `service_disabled`: проверить право без `hr` нельзя (S1-05).

**Где ещё действует видимость (S1-17, S1-18, S1-23).** Кроме списка и `load_for_action` — лента календаря, Ганта отчётов, связи и подзадачи в карточке, `parent_id`, списки досок проектов и роудмапов (поддерево отдела), задачи роудмапа и цели ресурсов (`refs` держателя `project.board`).

**Тенантность.** Всё — в `apps/tasks` (схемы `co_<slug>`) и `apps/access` (`public`); `hr` читается только через `hr.interface`; сводки холдинга не затронуты (у `Task` и `Project` столбцы не меняются).

**Совместимость.** Старый интерфейс (`HRTasks`, `EmployeeTasks`, `HRTaskDetail`, `EmployeeTaskDetail`, `HRProjects`) работает без изменений, кроме двух правок `EmployeeTasks` и диалога переноса (K1.5). Пользователи видят больше задач — это ожидаемое следствие (мастер-план §11 п.1).

---

## 2. Модель данных и миграции

| Миграция | Что | Где |
|---|---|---|
| `access/0028_tasks_board_nodes` | данные: строки `tasks.departments.all` у всех системных ролей кроме `platform-admin` (`can_view` — `bpp-od`, `bpp-gd`); `project.board`: `bpp-gd` → `can_view`; пустые строки `project.board` у системных ролей без строки, кроме `platform-admin` | `public`, `migrate_shared` |
| `tasks/0027_department_link_kind` | `TaskDepartmentLink.kind` `CharField(10, choices=member\|origin, default="member", db_default="member", db_index=True)` | `co_<slug>`, `migrate_companies` |

`hr` — без миграций, если на стенде есть `_like`-индекс `path` (Django создаёт `varchar_pattern_ops`-индекс для `unique` `CharField`; проверить `\d hr_department` в схеме компании). Нет — `hr/00xx_department_path_like` (`AddIndex(fields=["path"], opclasses=["varchar_pattern_ops"])`).

---

## 3. Задачи

### K1.1 — `hr.interface`: поддерево и отделы главы (первой)

```python
def department_subtree_ids(department_ids: list[int]) -> dict[int, list[int]]:
    """{id: [id, …потомки]} по Department.path: path = P OR path LIKE 'P.%'.
    Неактивные включаются (S1-02). Неизвестный id — ключа нет. Пустой вход — {}."""

def managed_department_ids(user_id: int) -> list[int]:
    """Отделы, где Department.manager — сотрудник с этим user_id
    (is_deleted=False, status=ACTIVE), сам отдел is_active=True. Отсортированы по id."""

def department_manager_user_ids(department_ids: list[int]) -> dict[int, int]:
    """{id отдела: user_id главы} — только у отделов, где глава есть, действует
    и имеет учётную запись. Для уведомления главе отдела-получателя (K1.5)."""
```
- Все три — первой строкой `require_service("hr")`, словари/списки, не ORM (контракт `hr/interface.py:1-14`).
- `department_subtree_ids`: запрос 1 — `values("id","path")` по входу; запрос 2 — `Department.objects.filter(reduce(or_, [Q(path=p) | Q(path__startswith=f"{p}.") for p in paths])).values("id","path")`, раскладка по корням в Python (строка может попасть в несколько корней — если вход содержит и предка, и потомка).
- Временных исполнителей и замещающих нет (K-09).
- Тесты `hr/tests/test_interface_departments.py`: поддерево `it` → `it`, `it.dev`, `it.dev.backend`, но не `itops`, не `it_x`; неактивный подотдел входит; два корня одним вызовом; неизвестный id; `managed_department_ids` — глава двух отделов, уволенный глава (`status=INACTIVE`) — пусто, удалённый сотрудник — пусто, неактивный отдел — не входит; `department_manager_user_ids` — отдел без главы и с главой без учётной записи в ответ не попадают; выключенный `hr` — `ServiceDisabled` у всех трёх.

### K1.2 — узлы прав

**Код.**
- `apps/tasks/access_functions.py`: + `("tasks.departments", "Доски отделов")`, `("tasks.departments.all", "Доски всех отделов", ("view",))`; + `EXPLICIT_ONLY = frozenset({"tasks.departments.all"})` (атрибута сейчас нет).
- `apps/project/access_functions.py`: `EXPLICIT_ONLY = frozenset({"project.structure", "project.roles", "project.board"})` + комментарий: узел открывает задачи (K-14), поэтому не наследуется от `project` (K-15, Q-K02).
- `registry.explicit_only()` под `lru_cache` (`access/registry.py:109`) — в тестах, меняющих реестр, не трогать; новых таких тестов нет.

**Миграция `access/0028_tasks_board_nodes`** — по образцу `access/0024` (`seed`/`unseed`, `RunPython`, зависимость от `0027_tender_roles`):
```python
FLAGS = ("can_view", "can_create", "can_edit", "can_delete")
ALL_DEPTS, BOARD = "tasks.departments.all", "project.board"
DIRECTORS = ("bpp-od", "bpp-gd")
BOARD_VIEWERS = ("bpp-td", "bpp-od", "bpp-gd", "bpp-pm", "bpp-adm")

def seed(apps, schema_editor):
    for role in system_roles.exclude(code="platform-admin"):
        update_or_create(role, ALL_DEPTS, view=role.code in DIRECTORS)
        if role.code.startswith("bpp-"):
            update_or_create(role, BOARD, view=role.code in BOARD_VIEWERS)   # меняется только bpp-gd
        else:
            get_or_create(role, BOARD, все False)                           # не затирать ручную строку

def unseed(apps, schema_editor):
    RolePermission.filter(node=ALL_DEPTS).delete()
    update_or_create(bpp-gd, BOARD, все False)
    RolePermission.filter(node=BOARD).exclude(role__code__startswith="bpp-").filter(все False).delete()
```
- Кастомные роли (`is_system=False`) не трогаются: у `EXPLICIT_ONLY`-узла отсутствие строки — запрет.
- `platform-admin` строк не получает: узлы `EXPLICIT_ONLY` ему без строки закрыты (приём `0024`) — он теряет унаследованный от `project` `project.board` (Q-K02).

**Документы.** Матрица `docs/plans/2026-09-27-bpp-roles-matrix.md`: строка `project.board` — ГД `V`; абзац «21.10 (решение заказчика, канбан-доски): ГД видит доски задач проектов; новый узел `tasks.departments.all` — ОД и ГД».

**Тесты** `access/tests/test_tasks_board_nodes.py`:
- у каждой системной роли, кроме `platform-admin`, есть строка `tasks.departments.all`; `view` — ровно у `bpp-od`, `bpp-gd`; прочих флагов нет ни у кого;
- у каждой системной роли, кроме `platform-admin`, есть строка `project.board`; `view` — ровно `bpp-td`, `bpp-od`, `bpp-gd`, `bpp-pm`, `bpp-adm`;
- оба узла в `registry.explicit_only()`;
- кастомная роль с `tasks` `full` не получает `tasks.departments.all`; кастомная роль с `project` `full` не получает `project.board` (`resolve.flags_for`);
- `unseed` → `seed` идемпотентны.
Правка существующего: `access/tests/test_bpp_roles.py:96-102` — ожидаемый список `["bpp-td", "bpp-od", "bpp-gd", "bpp-pm", "bpp-adm"]`, докстринг с ссылкой на `0028`; `test_every_role_has_an_explicit_row_on_every_operation` (`:30`) — без изменений (строки остаются).

### K1.3 — `TaskScope`, видимость, права главы

**Новый модуль `tasks/services/task_scope.py`:**
```python
@dataclass(frozen=True)
class TaskScope:
    user_id: int
    elevated: bool
    own_department_id: int | None
    managed_ids: frozenset[int]          # hr.managed_department_ids
    department_ids: frozenset[int]       # поддеревья own + managed (видимость)
    managed_subtree: frozenset[int]      # поддеревья только managed (права главы)
    all_departments: bool                # view на tasks.departments.all
    board_refs: object                   # board_scope: None | ALL_LINKED | list[str]

def build(token, company: str | None, *, resolution=None) -> TaskScope: ...
def for_request(request) -> TaskScope: ...   # кэш request.task_scope
```
- `elevated` — без обращений к `hr` и `access` (всё и так видно).
- Иначе: `own_department_id` — `hydration.employee_department_id` (как сейчас); `managed_ids` — `hr.managed_department_ids`; одно `department_subtree_ids(own ∪ managed)`; `all_departments` и `board_refs` — `access.flags_for(..., resolution=request.access_resolution[2])`, если тройка совпадает (компания и `user_id`), иначе без неё. `board_scope.board_refs_for` получает параметр `resolution=None` и передаёт его в оба `flags_for`.
- Запросов на `TaskScope` рядового: `hr` — 3 (сотрудник, главы, поддерево), `access` — 0 при гейте ручки.

**`task_service`:**
```python
def visibility_q(scope: TaskScope | None) -> Q | None:
    # None — без ограничений (внутренние вызовы, elevated)
def filtered_tasks(*, scope=None, reports=False, …прежние фильтры…)
def list_tasks(*, scope=None, …) / get_task(task_id, *, scope=None)
def scope_for(token, *, reports=False)        # остаётся ТОЛЬКО для task_stats (S1-11)
def load_for_action(task_id: int, request) -> Task          # было (task_id, token)
def can_edit(task, scope) -> bool / can_progress(task, scope) -> bool
def require_full_edit(task, request) / require_soft_edit(task, request)
```
Формула `visibility_q` (мастер-план §5.2):
```
elevated                → None
иначе  Q_part(u)
     | department_id ∈ S | Exists(TaskDepartmentLink(task=OuterRef("pk"), department_id ∈ S))      (S = department_ids, если непусто)
     | department_id IS NOT NULL | Exists(TaskDepartmentLink(task=OuterRef("pk")))                  (если all_departments)
     | board_scope.board_q(board_refs, prefix="project__")                                           (если board_refs не None)
```
`_employee_visibility_q` и ветка «неразобранные `backlog`/`todo`» удаляются: поддерево отдела их покрывает. `_report_visibility_q` и режимы `"employee"`/`"reports"` остаются для `task_stats` (S1-11).

Права главы (K-06):
```
can_edit(task, scope)   = elevated | reporter | supervisor | delegate
                        | task.department_id ∈ scope.managed_subtree
                        | Exists(member-связь задачи с отделом ∈ scope.managed_subtree)     # origin прав не даёт
can_progress(task, scope) = can_edit | assignee | соисполнитель
```
`soft_edit_q` (`:97-114`, доска ежедневных отчётов) **не меняется** (S1-09).

**Переход вызывающих** (механический, одним коммитом):
- 40 вызовов `load_for_action(…, request.token)` / `require_*(task, request.token)` в `tasks/views.py` → `(…, request)`;
- списки: `_list_tasks` (`views.py:448`), задачи объекта (`:1452`), роудмапа (`:1833`), доски проекта (`:1867`) — `scope=task_scope.for_request(request)` вместо пары `visibility`/`department_id`;
- `task_response.build_detail` (`:214-271`): `can_edit`/`can_progress` — через `scope`; новый блок `can` (K1.5) считается там же;
- `_report_for_write` (`views.py:818-835`) — без изменений по существу (автор отчёта, руководитель задачи, `elevated`), но `load_for_action(report.task_id, request)`.

**Тесты** `tasks/tests/test_board_visibility.py` (фикстура `org`: отделы `it`, `it.dev`, `ops`, `itops` через модели `hr` — в тестах прямой импорт разрешён, `test_app_isolation` их пропускает; сотрудники с `user_id`; задачи в разных статусах; `auth()` из `helpers.py` + `assign` для узлов):
- сотрудник `it` видит задачу `it.dev` в `in_progress` с чужим исполнителем — `GET tasks/`, `GET tasks/<id>`, `GET tasks/<id>/comments`, `POST comments` → 201;
- сотрудник `it.dev` не видит задачу `it` (404) и задачу `itops`;
- задача видна через связь `member` и через `origin`;
- глава `it`, числящийся в `ops`, видит поддерево `it`; глава двух отделов — оба;
- глава `it` (не участник): `PATCH` полей, `PATCH supervisor`, `assignees`, `progress`, статус, `DELETE` задачи `it.dev` → 2xx; задачи `ops` → 404; задачи, где у `it` только связь `origin`, → 403 на `PATCH`;
- ОД (`bpp-od` с `tasks.departments.all` и `project.board`+`project.all`) видит задачи любого отдела и любой связанной доски; `PATCH` → 403; комментарий → 201; задача без отдела, проекта и связей — 404;
- ГД — то же, что ОД (после `0028`);
- ТД, АДМ — все задачи всех связанных досок; ПМ — только досок своих проектов; задача доски чужого проекта у ПМ — 404;
- чужая личная задача (без проекта, отдела и связей) не видна ОД, ГД, ТД, ПМ, главе — detail 404, нет в списке, 404 в `comments` и `activity`; `elevated` видит (K-17);
- задача проекта без `project_ref` (доска не связана) не видна через `project.board`;
- `hr` выключен: участие видно, задача отдела — нет;
- `test_board_scope.py`: держатель `project.board` теперь видит **задачи** доски в `projects/<id>/tasks/` (новый тест), правка доски — по-прежнему 404 (существующий тест);
- число запросов `GET tasks/?limit=50` у рядового с поддеревом из 5 отделов не больше, чем при одном (`django_assert_max_num_queries`, порог фиксируется по факту);
- `request.task_scope` строится один раз: две проверки в одной ручке (`load_for_action` + `require_full_edit`) — один вызов `hr.managed_department_ids` (мок-счётчик).

### K1.4 — отдел задачи, автор, начальный статус

**`tasks/services/department_rules.py`:**
```python
def assert_department_allowed(scope: TaskScope, department_ids: Iterable[int]) -> None
def assert_department_change(scope: TaskScope, task: Task, new_primary: int | None) -> None
```
- Пустой набор — можно всем.
- `elevated` — любой набор (S1-12: администратор правит как раньше, `PATCH`-ем в том числе между отделами).
- **Порядок проверок (S1-05):** для непустого набора сначала существование и активность — `hr.interface.get_departments_brief` (один запрос; `hr` выключен — 503 `service_disabled` раньше любого 403), нет или `is_active=False` — 422 `task_department_inactive`; затем право.
- Глава (`managed_ids` непусто): любой действующий отдел при **создании**; при `PATCH` — каждый id набора ∈ `scope.managed_subtree` (только управляемые поддеревья, не его собственный отдел-место), иначе 422 `task_department_use_transfer` (S1-13, S1-19).
- Рядовой: каждый id ∈ `scope.department_ids` (своё поддерево), иначе 403 `task_department_forbidden`.
- **Действующий основной отдел после `PATCH`** считается до проверки: `department_ids` без `department_id` перекладывает основной в `department_ids[0]` (`task_service.py:478-479`) — проверяется именно он (S1-19).

**`create_task`** (`task_service.py:380-459`), получает `scope`:
- `assert_department_allowed(scope, dept_ids)`;
- `reporter_id` — `data.reporter_id` только у `elevated`, иначе `user_id` (K-25);
- начальный статус — у не-`elevated` только `backlog`/`todo`, иначе 422 `task_status_initial`;
- глава создаёт задачу в отдел вне своего (`department_id ∉ department_ids`): исполнители в теле — 422 `task_transfer_assignees`; связь `origin` на отдел-отправитель = первый из `managed_ids`, в чьё поддерево **не** входит цель (обычно — его отдел), строкой рядом с `member`.

**`update_task`** (`:462-563`), получает `scope`:
- `department_id` и `department_ids` — через `assert_department_change`/`assert_department_allowed`;
- `department_ids` заменяет только строки `kind="member"` (`task.department_links.filter(kind="member").delete()`), строки `origin` не трогает; если новый набор содержит отдел со строкой `origin`, она становится `member`;
- `"department_id"` добавляется в `TRACKED_FIELDS` (`:62-68`).

Вьюхи `_create_task` (`views.py:458-468`) и `_update_task` (`:505-524`) передают `scope`; `DomainError` проходит сквозь `api_view` сам.

**Тесты** `tasks/tests/test_department_rules.py`: рядовой `it.dev` создаёт в `it.dev.backend` → 201, в `it` → 403, в `ops` → 403, без отдела → 201; `department_ids` с одним чужим → 403; глава `it` создаёт в `ops` → 201 с `member`(`ops`) и `origin`(`it`), с исполнителями → 422; глава `PATCH` отдела `it.dev` → `it` → 200, `it` → `ops` → 422 `task_department_use_transfer`; `elevated` `PATCH` в любой → 200; неактивный отдел → 422; `reporter_id` чужой от рядового — игнорируется (автор = вызывающий), от `elevated` — принимается; статус `in_progress` при создании рядовым → 422, `elevated` → 201; `PATCH department_ids` сохраняет `origin`; смена отдела пишет `TaskActivity(field_name="department_id")`; `hr` выключен + отдел в теле → 503.

### K1.5 — перенос, «Взять в работу», серверные вкладки, `can`, фронт

**`tasks/services/transfer.py`:**
```python
def transfer(task_id: int, target_department_id: int, request, *, sender_department_id: int | None = None) -> Task
```
Сначала `load_for_action(task_id, request)` (невидимая — 404, а не 403), затем одна транзакция с блокировкой **отдельным** запросом `Task.objects.select_for_update().get(pk=task_id, is_deleted=False)` — `filtered_tasks` всегда `.distinct()`, а `FOR UPDATE` с `DISTINCT` Postgres не принимает (мастер-план §5.5):
1. право: `elevated`, или основной отдел задачи ∈ `scope.managed_subtree`, или у задачи нет отдела и `can_edit` + глава (`managed_ids` непусто) — иначе 403 `task_transfer_forbidden`;
2. статус `done`/`cancelled` — 409 `task_transfer_terminal`; цель = текущий основной — 422 `task_transfer_same`; цель неактивна — 422 `task_department_inactive`;
3. отправитель = прежний основной отдел; нет — `sender_department_id` (должен быть ∈ `managed_ids`, иначе 422), по умолчанию первый из `managed_ids`; у `elevated` без управляемых — без `origin`;
4. связи: отправитель → `origin` (`update_or_create`), прежняя `member`-строка основного снимается, цель → `member` (если была `origin` — становится `member`); `department_id = target`;
5. `assignee_id = None`, `TaskAssignee` задачи удаляются; руководитель, автор, делегаты, наблюдатели остаются;
6. статус ≠ `todo` → `todo` прямым присваиванием (S1-06; `completed_at` не трогается — терминальные сюда не доходят);
7. журнал: `transfer` (`old_value` — отправитель, `new_value` — цель), `department_id`, `assignee_id` (если был), `status` (если менялся);
8. уведомление главе отдела-получателя (`hr.interface.department_manager_user_ids`, K1.1) через существующий `_notify` (`task_service.py:356-368`) **синхронно в транзакции**, как все уведомления задач (без `on_commit`: ошибка после коммита превратила бы сохранённый перенос в 503); `ServiceDisabled` поиска главы — `fallback("tasks.transfer.manager_lookup", …, expected=True)`, перенос не падает; текст `task_transferred:<key>`; единая рассылка участникам — этап 3 (S1-10);
9. ранги досок — в этапе 2 (таблицы ещё нет).

**«Взять в работу» — `tasks/services/task_service.claim(task_id, request) -> Task`:**
- задача видна (иначе 404) и **принадлежит своему отделу**: `department_id ∈ scope.department_ids` или связь `kind="member"` с отделом из них; связь `origin`, «все отделы» и доска проекта не считаются (S1-07) — иначе 403 `task_claim_forbidden`;
- блокировка задачи отдельным `select_for_update` (как у переноса) — две одновременные попытки не дают двух основных исполнителей;
- нет `assignee_id` и строк `TaskAssignee`, статус `backlog`/`todo` — иначе 409 `task_claim_unavailable`;
- `TaskAssignee(primary)` + `assignee_id`, `apply_transition("in_progress")` (FSM пускает из обоих статусов), журнал `claim`, `assignee_id`, `status`.

**Ручки** (`tasks/urls.py`, рядом с `tasks/<id>/transitions/`; гейт `api_view(module="tasks", level="write")`, диспетчер только по методу):

| Ручка | Тело | Ответ |
|---|---|---|
| `POST tasks/<id>/transfer[/]` | `{department_id: int, sender_department_id?: int}` (`extra="forbid"`) | 200 — `build_detail` |
| `POST tasks/<id>/claim[/]` | — | 200 — `build_detail` |

**Список `GET tasks/`** — параметр `scope` (`_list_tasks`, `views.py:419-455`, S1-04):
- `scope=mine` — `Q_part(u)` поверх видимости (то, что станет личной доской, K-03);
- `scope=department` — задачи поддерева своего отдела и управляемых (`Q_dept(scope.department_ids)`), без учёта `all_departments` и досок проектов;
- другое значение — 422; без параметра — как раньше (вся видимость).

**`build_detail` → `can`** (`task_response.py`): `{full_edit, soft_edit, comment, transfer, claim, delete}` — те же функции, что проверяют ручки (`can_edit`, `can_progress`, видимость, правило переноса, правило `claim`, `can_edit`); + `department_links: [{department_id, name, kind}]` (имена — `hydration.department_briefs`, уже батчем). `scope` у `build_detail` — **обязательный** keyword, все 10 вызовов (`views.py:468, 499, 523, 557, 566, 578, 598, 605, 612, 630`) передают `for_request(request)`; поля объявляются в `schemas.TaskDetailResponse` (иначе pydantic их отбросит) и в `tests/fixtures/contracts.json` (сторож `test_contract_parity.py`). `department_ids`/`departments` ответа строятся **только из связей `member`** (S1-20). **`build_list` → `can: {claim}`** — тот же предикат, что у ручки, из уже загруженных строк (`department_links` в prefetch), без новых запросов; поле — в `TaskListResponse` и `contracts.json`.

**Фронт** (минимум, старые страницы остаются до этапа 6):
- `fe/api/tasks.ts`: `fetchTasks(params)` принимает `scope`; новые `claimTask(id)`, `transferTask(id, {department_id, sender_department_id?})`; `fe/types/tasks.ts`: `Task.can?`, `Task.department_links?`.
- `fe/pages/hr/EmployeeTasks.tsx`: запрос по вкладке — `fetchTasks({scope: activeTab === 'my-tasks' ? 'mine' : 'department'})`, клиентские фильтры отдела и «моих» (`:87-106`) удаляются (остаётся поиск); на вкладке отдела — все задачи отдела, кнопка «Взять в работу» только у карточек с `can.claim`; `acceptMutation` → `claimTask`; инвалидация `['employee-tasks']` и `['hr-tasks']`; строки «Kanban»/«Table»/«Loading...» (`:245, :253, :262`) — заодно в i18n. Подпись вкладки `hr.tasks.departmentFree` («Свободные задачи отдела») → `hr.tasks.department` («Задачи отдела»).
- `fe/features/tasks/board/TransferDialog.tsx` (первая версия, этап 5 переиспользует): выбор отдела (список `GET hr/v1/departments`, поиск по названию, текущий отдел и неактивные скрыты), отдел-отправитель (если у задачи нет отдела и у главы их несколько), пояснение «Исполнители будут сняты, задача встанет в "К выполнению"»; ответы 403/409/422 — текст сервера (`lib/apiError`).
- `HRTaskDetail.tsx` и `EmployeeTaskDetail.tsx`: кнопка «Отправить в отдел» при `task.can.transfer`; ответ `task_department_use_transfer` на смене отдела в `HRTaskDetail` — тост с предложением открыть диалог переноса.
- i18n (`ru`, `en`): `tasks.transfer.*` (заголовок, поля, пояснение, успех), `tasks.claim.*`, `hr.tasks.department`, `tasks.errors.<код>` для кодов §1 (фронт берёт текст по `code`, иначе `detail`).

**Тесты:**
- `tasks/tests/test_transfer.py` — мастер-план §9 «Этап 1» (перенос `in_review` с исполнителем: снятые исполнители, `todo`, `origin`, журнал, уведомление главе-получателю; рядовой → 403; глава соседнего отдела → 403; `done` → 409; та же цель → 422; обратный перенос: `origin` → `member`; `elevated` без управляемых отделов — без `origin`; задача без отдела: глава с полной правкой переносит, `sender_department_id` вне его отделов → 422; тело с лишним полем → 422);
- `tasks/tests/test_claim.py` — неразобранная `todo` своего подотдела → primary, `in_progress`, журнал; с исполнителем → 409; `in_progress` → 409; задача видна только через доску проекта → 403; ОД (видит через `all_departments`) → 403; невидимая → 404;
- `tasks/tests/test_list_scope.py` — `scope=mine` у сотрудника, у которого в отделе 60 задач новее его собственной, возвращает его задачу первой страницей; `scope=department` — без задач доски проекта; `scope=x` → 422;
- `tasks/tests/test_detail_can.py` — `can` у участника, главы, рядового коллеги, ОД, `elevated` совпадает с фактическими ответами ручек (для каждого флага — вызов соответствующей ручки);
- vitest: `EmployeeTasks` шлёт `scope` по вкладке и `claim` по кнопке; `TransferDialog` — список без текущего отдела, текст ошибки сервера; `translationKeys.test.ts` зелёный.

---

## 4. Порядок и раскладка

| Шаг | Задача | Файлы | Зависит |
|---|---|---|---|
| 1 | K1.1 | `hr/interface.py`, `hr/tests/test_interface_departments.py` | — |
| 2 | K1.2 | `tasks/access_functions.py`, `project/access_functions.py`, `access/migrations/0028_tasks_board_nodes.py`, `access/tests/test_tasks_board_nodes.py`, `access/tests/test_bpp_roles.py`, матрица ролей | — |
| 3 | K1.3 | `tasks/services/task_scope.py` (новый), `task_service.py`, `board_scope.py`, `task_response.py`, `views.py` (40 вызовов + 4 списка), тесты | 1, 2 |
| 4 | K1.4 | `tasks/migrations/0027_department_link_kind.py`, `models.py`, `services/department_rules.py` (новый), `task_service.py`, `views.py`, тесты | 3 |
| 5 | K1.5 | `services/transfer.py` (новый), `task_service.claim`, `urls.py`, `views.py`, `schemas.py`, `task_response.py`, фронт, i18n, тесты | 4 |
| 6 | закрытие | `API.md` («apps.tasks»: `transfer`, `claim`, `scope`, `can`, `department_links`, коды; строка `projects/` — задачи доски видны держателю узла), `STRUCTURE.md` §4.2 (видимость и права главы), `CLAUDE.md` (короткий абзац «Канбан-доски, этап 1»: узлы, `TaskScope`, `load_for_action(task_id, request)`), `harness-review` | 5 |

Шаги 1 и 2 независимы — можно параллельно. Коммит на шаг; шаг 3 — один коммит на механическую замену `token` → `request` отдельно от смены правила видимости, чтобы ревью видело правило без шума.

---

## 5. Проверки этапа

- `pytest apps/tasks apps/hr/tests/test_interface_departments.py apps/access apps/project` на `:55432`, Python 3.14 (`.venv`), один прогон за раз;
- сторожа: `apps/core/tests/test_app_isolation.py`, `test_invariants.py`, `test_platform_today.py`, `test_metrics*`, `apps/access/tests/test_gate.py` (новые ручки под `module="tasks", level="write"`; `test_employee_basic_passes_every_non_admin_handle` — пропускает), `apps/access/tests/test_depth.py`;
- `manage.py makemigrations --check` чист; на стенде `migrate_shared` + `migrate_companies` (новая колонка в `co_<slug>`), `manage.py tenancy_status` до и после;
- фронт: `npm run lint`, `npx tsc --noEmit -p tsconfig.app.json` (не больше базы на старте — снять число), `npx vitest run src/pages/hr src/features/tasks src/lib/i18n`;
- руками на стенде (`group.localhost:3000`, `seed_hr_demo` + `seed_tasks_demo`): сотрудник подотдела видит взятые в работу задачи отдела; «Взять в работу»; глава переносит задачу из `/tasks/:id`; ОД видит задачи досок проектов в `/manage/projects` → «Задачи».

---

## 6. Решения этапа

| № | Решение | Почему |
|---|---|---|
| S1-01 | `load_for_action`, `require_full_edit`, `require_soft_edit` принимают `request`, а не `token` (40 мест в `views.py`) | `TaskScope` кэшируется на запросе; `TokenPayload` — `pydantic.BaseModel`, на нём кэш не повесить; contextvar проект не использует для таких целей (приём `access_resolution`) |
| S1-02 | Поддерево отдела включает неактивные подотделы | Задачи закрытого подотдела не должны пропасть с доски родителя (Q-K17) |
| S1-03 | Связь `origin` даёт видимость, но не права | Отправитель следит за ходом работ; править после переноса — дело отдела-получателя (K-06, K-08) |
| S1-04 | Параметр списка — `scope=mine\|department` (а не `department_board=me`, как было в мастер-плане) | Обе вкладки `EmployeeTasks` теряют задачи после расширения видимости, не только вкладка отдела |
| S1-05 | При выключенном `hr` запись с отделом — 503, видимость — сужение | Проверка права без `hr` невозможна; молча принять отдел — обойти правило K-07 |
| S1-06 | Перенос ставит `todo` прямым присваиванием, мимо FSM | Из `in_review` FSM в `todo` не пускает (`models.py:98-99`), а задача у получателя должна начинаться заново (K-08) |
| S1-07 | «Взять в работу» — только задачу, видимую через свой отдел (поддерево, связи); через «все отделы» или доску проекта — нет | Это действие сотрудника отдела над его общей работой; директорам и держателям досок проектов — запрос доступа (K-31, этап 3) |
| S1-08 | Сторож строк — на два узла этапа, а не общий по всем `EXPLICIT_ONLY` | Общий упал бы на `bpp.*.all` (строки только у `bpp-*`), а для `EXPLICIT_ONLY` отсутствие строки и так запрет (мастер-план §2.2 п.12) |
| S1-09 | `soft_edit_q` не расширяется на поддерево главы | Доска ежедневных отчётов — «где я отчитываюсь», а не «где мне можно»; расхождение в сторону «можно, но не в списке» безопасно (обратное — 403 на сохранении — нет) |
| S1-10 | Уведомление о переносе — существующим `_notify` главе получателя; общая рассылка участникам (`task_notify`, K-29/K-30) — этап 3 | Не тянуть в этап 1 выключатель по доскам и его таблицу |
| S1-11 | `/tasks/stats` остаётся на прежнем правиле (`_report_visibility_q`) | Q-K15; статистику не перестраиваем в этапе прав |
| S1-12 | `elevated` правит отдел `PATCH`-ем без ограничений, как сейчас | Администраторский инструмент (`HRTasks`) не ломаем; перенос со связью `origin` — отдельное действие и для него |
| S1-13 | Глава `PATCH`-ем не уводит задачу за пределы своих поддеревьев — 422 `task_department_use_transfer` | Иначе два пути переноса: один снимает исполнителей и ставит `origin`, другой — нет |
| S1-14 | `can` и `department_links` в ответе карточки и простой `TransferDialog` — в этапе 1, а не 3/5 | Главы должны переносить задачи сразу после выкатки этапа 1, а не после окна карточки |
| S1-15 | Наблюдатель остаётся участником (`Q_part`) и после переноса и смены отдела | «Наблюдать» — явный выбор человека, и личная доска их включает (K-03); видимость наблюдателя — следствие его подписки. Снять наблюдение может сам он |
| S1-16 | Автор, руководитель и делегаты сохраняют права после переноса и при создании задачи в чужой отдел | Это роли задачи (K-08: «руководитель и автор остаются»); S1-03 — про связь `origin`, а не про роли. Отдать задачу целиком — снять себя руководителем |
| S1-17 | Видимость получают ручки, которые сейчас отдают задачи без неё: лента календаря (`calendar_service.py:233-241`, `views.py:2246`), Ганта отчётов (`gantt_service.py:64-83`, `views.py:2106-2120`) и график ресурсов (`gantt_service.resource_gantt`, найдено ревью K1.4), связи и подзадачи в карточке (`task_response.py:193-210, 253-270`) | Иначе гарантия «чужая личная задача не видна» ложна уже сейчас, а расширение видимости размножит утечку |
| S1-18 | `parent_id` при создании и правке — только видимая задача (404 иначе) | Иначе подзадачу можно подвесить под чужую задачу и узнать её ключ |
| S1-19 | Глава `PATCH`-ем переводит задачу только внутри управляемых поддеревьев; основной отдел после `PATCH` проверяется и при переданном одном `department_ids` | Закрывает два обхода переноса: через `department_ids` и через собственный отдел-место главы |
| S1-20 | В `department_ids`/`departments` ответа — только связи `member`; `origin` — только в `department_links[].kind` | Иначе интерфейс, отправив список обратно, превратит отправителя в участника (S1-03) |
| S1-21 | `reporter_id` в `PATCH` — только `elevated` (остальным — 422 `task_reporter_forbidden`) | Глава с полной правкой мог бы стать автором и сохранить права после переноса |
| S1-22 | Уволенный сотрудник (`status != ACTIVE`) — без отдела в `TaskScope`; свой отдел, о котором `hr` не знает, всё равно входит в `department_ids` | Уволенный не должен получить весь отдел; отсутствие строки в `hr` не должно сужать до пустого |
| S1-23 | Доски проектов и роудмапы видны по поддереву отдела (`project_service._visible`, `roadmap_service._visible` получают `scope.department_ids`); `roadmap_tasks` (`views.py:1829`) и `_read_resource_target` (`:1903`) получают `refs` держателя | Иначе задача подотдела видна в списке, а доска её проекта и задачи роудмапа — 404 |
| S1-24 | Глава отдела добавляет и снимает делегатов задач поддерева (`views.py:574`, `:594`: «руководитель или `elevated`» дополняется главой) | K-06: глава равен руководителю задачи |
| S1-25 | Фильтры `GET tasks/?assignee_id=…` у ОД и ГД возвращают нагрузку человека по отделам и проектам — допустимо | Видимость директоров — решение заказчика (K-10); задачи без проекта и отдела в выборку не попадают |
| S1-26 | Связь задач по-прежнему требует полной правки источника и только видимости цели | Сложившееся поведение не меняем; заголовок своей задачи на чужой карточке — следствие видимости |
| S1-27 | Модель и миграция `TaskDepartmentLink.kind` (`tasks/0027`) — в задаче видимости (план Task 4), а не правил отдела | Видимость через `origin` и «связь `origin` прав не даёт» требуют поля уже там |

Открытых вопросов к заказчику нет. Выкатка — мастер-план §10 (бой — в окне выкатки БЗО или после него: `access/0028` стоит на цепочке миграций БЗО).
