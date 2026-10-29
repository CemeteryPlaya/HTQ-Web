# Канбан-доски — этап 1 (Plans K1.1–K1.8): пошаговый план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** видимость задач по поддереву отдела, права главы отдела на задачи своего поддерева, ОД и ГД видят все доски отделов и проектов со всеми задачами, держатели «Доски задач проекта» видят задачи внутри досок; «Взять в работу» и перенос задачи в другой отдел с сохранением отдела-отправителя; закрыты существующие утечки задач мимо видимости (календарь, Ганта, связи, подзадачи).

**Architecture:** один расчёт на запрос — `tasks/services/task_scope.py::TaskScope` (кэш на `request.task_scope`), из него `task_service.visibility_q` и права (`can_edit`/`can_progress`). Оргструктура — только через `hr.interface` (три новые функции), права — узлы `access` (`tasks.departments.all`, `project.board`, оба `EXPLICIT_ONLY`). Новые сервисы `department_rules.py`, `transfer.py`; ручки `transfer`, `claim`, параметр списка `scope`, флаги `can`. Фронт — минимум: `EmployeeTasks` на серверных вкладках, `TransferDialog` на `/tasks/:id`.

**Tech Stack:** Django 5.2.7 / Python 3.14 (корневой `.venv`), pytest-django на Postgres `:55432`, React 18 + Vite + TanStack Query + vitest.

**Spec:** [2026-10-21-kanban-stage1-spec.md](2026-10-21-kanban-stage1-spec.md) — правила §1, модель §2, задачи §3, решения S1-01…S1-27 §6. Над ней — [мастер-план](2026-10-21-kanban-boards-master-plan.md) (K-01…K-33, формулы §5.2, таблица прав §5.3). Соответствие: Task N плана = Plans K1.N; разделы спеки — K1.1 (hr) → Task 1, K1.2 (узлы) → Task 2, K1.3 (видимость) → Tasks 3–4, K1.4 (отдел) → Task 5, K1.5 (перенос, фронт) → Tasks 6–7.

**Как получен.** Черновик проверен против кода тремя независимыми проверками (`harness-plan`, `team_validation_mode: subagent`): архитектура и критик, безопасность и права, тестируемость — 54 находки, из них 7 критичных; принятые — в этом плане и в спеке (S1-15…S1-27).

## Global Constraints

- Ветка — `sanzhar` (дана пользователем); **веток не создавать**; коммиты локальные, пуш — только по команде пользователя.
- Все команды бэкенда — из `backend/`: `../.venv/Scripts/python.exe -m pytest …`, `../.venv/Scripts/python.exe manage.py makemigrations --check --dry-run`. Postgres — `docker compose -f docker-compose.test-local.yml up -d db` (`:55432`). Один прогон pytest за раз; прогон дольше 10 минут — `nohup bash <скрипт> > <лог> 2>&1 &` в каталоге сессии.
- Соседи — только через `apps.<x>.interface` (сторож `test_app_isolation`); в `task_scope.py` — `from apps.hr import interface as hr` (модуль, не имена: тесты подменяют атрибут). Тесты могут создавать модели соседей напрямую (сторож пропускает `tests/`; тесты `tasks` идут в `public`, там же таблицы `hr` — образец фикстуры `test_seed_tasks_demo.py:60-82`).
- Новые ручки — `api_view(module="tasks", level="write")`, диспетчер в `urls.py` — только ветвление по `request.method` (сторож `apps/access/tests/test_gate.py`).
- Ошибки новых правил — `htqweb.errors.DomainError(code, message, status=…)` → `{detail, code, fields}`; прежние ответы `{"detail"}` не меняются. Коды — спека §1.
- Миграции: `tasks/0027` — expand с `db_default`, на стенде затем `docker exec htqweb-local-backend-web-1 python manage.py migrate_companies`; `access/0028` — `public`, `migrate_shared`.
- Новые поля ответов — в `schemas.py` (`TaskDetailResponse`, `TaskListResponse`) **и** в `apps/tasks/tests/fixtures/contracts.json` (сторож `test_contract_parity.py` сверяет набор ключей).
- Уведомления задач — синхронно, через `task_service._notify` (он сам глотает ошибки); `transaction.on_commit` в `tasks` не используется.
- `is_elevated` видит всё, как сейчас (K-17). Связь `origin` даёт видимость, не права и не «Взять в работу» (S1-03, S1-07).
- Фронт: `npx tsc --noEmit -p tsconfig.app.json` и `npm run typecheck:tests` — не больше числа ошибок на старте (снять в Task 7, шаг 1); строки — `t('tasks.…', 'фолбэк')` в обоих `public/locales/*/translation.json`.
- Коммиты — по-русски, `feat(tasks):`/`fix(tasks):`/`refactor(tasks):`/`feat(hr):`/`feat(access):`/`docs(tasks):`, в конце `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Стенд: `docker compose -f docker-compose.test-local.yml up -d --build`, затем в `backend-web`: `seed_hr_demo --company hi-tech-group`, `seed_tasks_demo --company hi-tech-group`, `bpp_assign_roles --company hi-tech-group`.

## Review Focus

1. **Задача подотдела в работе видна сотруднику отдела-родителя, но не наоборот**; `it` не захватывает `itops`, `a_b` не захватывает `aXb`. Тест — Task 1, Task 4.
2. **Ни одна роль, кроме участников и `elevated`, не видит чужую личную задачу** — ни в списке, ни в карточке, комментариях, журнале, **ленте календаря, Ганте, связях и подзадачах чужой карточки**. Тест — Task 4.
3. **ОД и ГД только читают:** видят всё, но `PATCH`, перенос и «Взять в работу» — 403; проверено и на настоящих ролях `bpp-od`/`bpp-gd` из миграции. Тест — Task 4, Task 6.
4. **Перенос:** исполнители сняты, статус `todo` даже из `in_review`, отправитель видит задачу, но не может ни править её, ни взять в работу; обходы переноса (`department_ids`, свой отдел-место главы, `reporter_id`) закрыты. Тест — Task 5, Task 6.
5. **Права главы считаются один раз на запрос** и флаги `can` (карточка и список) совпадают с исходом ручек. Тест — Task 4, Task 6.
6. **Механическая замена `token` → `request`** в 40 вызовах не меняет поведения. Тест — Task 3.

---

### Task 1: `hr.interface` — поддерево, отделы главы, главы отделов (Plans K1.1)

**Files:**
- Modify: `backend/apps/hr/interface.py`
- Test: `backend/apps/hr/tests/test_interface_departments.py` (новый)

**Interfaces:**
- Produces:
  - `hr.interface.department_subtree_ids(department_ids: list[int]) -> dict[int, list[int]]`
  - `hr.interface.managed_department_ids(user_id: int) -> list[int]`
  - `hr.interface.department_manager_user_ids(department_ids: list[int]) -> dict[int, int]`

- [ ] **Step 1: Тесты (красные).** Фикстура: отделы `it`, `it.dev`, `it.dev.backend`, `itops`, `a_b`, `aXb`, `aXb.c`, неактивный `it.old`; должность (уникальные `title`, `weight`); сотрудники с `user_id` и уникальным `email` (глава `it` и `itops` — один человек; уволенный глава `a_b`; удалённый сотрудник). Тесты:
  - `test_subtree_by_dot_separator` — `{it: [it, it.dev, it.dev.backend, it.old]}`, без `itops`;
  - `test_underscore_is_not_a_wildcard` — поддерево `a_b` = `[a_b]`, без `aXb.c`;
  - `test_subtree_two_roots_one_call`, `test_subtree_unknown_id_absent`, `test_subtree_empty_input`;
  - `test_managed_two_departments`, `test_managed_inactive_employee_none`, `test_managed_deleted_employee_none`, `test_managed_inactive_department_excluded`;
  - `test_manager_user_ids_same_filter_as_managed` — тот же набор отделов, что даёт `managed_department_ids` по их главам; без главы и с главой без `user_id` — нет ключа;
  - `test_hr_disabled_raises` — `ServiceStatus` `hr` выключен → `ServiceDisabled` у всех трёх;
  - `test_path_has_like_index` — `pg_indexes` содержит индекс `hr_department_path…_like` (Django создаёт его для `unique` `CharField`; миграция не нужна).
- [ ] **Step 2:** `../.venv/Scripts/python.exe -m pytest -q apps/hr/tests/test_interface_departments.py` — красные.
- [ ] **Step 3: Реализация.** Первая строка каждой — `require_service("hr")`. Общий помощник `_active_managers()` (`manager__isnull=False, manager__user_id__isnull=False, manager__is_deleted=False, manager__status=EmployeeStatus.ACTIVE, is_active=True`) — им пользуются обе функции глав. Поддерево: `values("id","path")` по входу, затем один запрос `reduce(or_, [Q(path=p) | Q(path__startswith=f"{p}.") …])` и раскладка по корням (Django экранирует `_` и `%` в `startswith`).
- [ ] **Step 4:** тот же прогон + `apps/hr/tests/test_interface.py apps/hr/tests/test_interface_substitutes.py` — зелёные.
- [ ] **Step 5: Коммит** — `feat(hr): поддерево отдела и отделы главы в hr.interface (канбан K1.1)`.

---

### Task 2: Узлы прав `tasks.departments.all` и `project.board` (Plans K1.2)

**Files:**
- Modify: `backend/apps/tasks/access_functions.py`, `backend/apps/project/access_functions.py`
- Create: `backend/apps/access/migrations/0028_tasks_board_nodes.py`
- Modify: `backend/apps/access/tests/test_bpp_roles.py` (`test_board_link_is_for_td_od_pm_and_adm`, `:96-102`)
- Modify: `docs/plans/2026-09-27-bpp-roles-matrix.md`
- Test: `backend/apps/access/tests/test_tasks_board_nodes.py` (новый)

- [ ] **Step 1: Тесты (красные)** — `test_all_departments_row_at_every_system_role` (кроме `platform-admin`; `view` ровно у `bpp-od`, `bpp-gd`); `test_board_row_at_every_system_role` (`view` ровно `bpp-td`, `bpp-od`, `bpp-gd`, `bpp-pm`, `bpp-adm`); `test_both_nodes_explicit_only`; `test_custom_role_with_tasks_full_lacks_all_departments`, `test_custom_role_with_project_full_lacks_board` (`resolve.flags_for`); `test_platform_admin_has_no_rows_on_new_nodes`; `test_unseed_then_seed_is_idempotent` (функции миграции через `importlib.import_module("apps.access.migrations.0028_tasks_board_nodes")`, `apps` из `django.apps`, как `conftest.py:386-391`; нетранзакционный тест). Правка `test_bpp_roles.py`: список с `bpp-gd`, имя — `test_board_link_is_for_td_od_gd_pm_and_adm`.
- [ ] **Step 2:** `../.venv/Scripts/python.exe -m pytest -q apps/access/tests/test_tasks_board_nodes.py apps/access/tests/test_bpp_roles.py` — красные.
- [ ] **Step 3: Реестр.** `tasks/access_functions.py`: `("tasks.departments", "Доски отделов")`, `("tasks.departments.all", "Доски всех отделов", ("view",))`, `EXPLICIT_ONLY = frozenset({"tasks.departments.all"})` с комментарием (K-12). `project/access_functions.py`: `project.board` в `EXPLICIT_ONLY` + комментарий (K-15).
- [ ] **Step 4: Миграция** по образцу `0024` (спека §K1.2): `seed` — цикл по `is_system=True` кроме `platform-admin`; `tasks.departments.all` — `update_or_create`; `project.board` — у `bpp-*` `update_or_create` с `BOARD_VIEWERS`, у остальных `get_or_create` с пустыми флагами. `unseed` — обратное. Зависимость — `("access", "0027_tender_roles")`.
- [ ] **Step 5:** прогон шага 2 + `apps/access apps/project apps/tender/tests/test_roles.py` — зелёные; `manage.py makemigrations --check --dry-run` чист.
- [ ] **Step 6: Матрица ролей** — строка `project.board`: ГД `V`; абзац «21.10 — канбан-доски» (спека §K1.2), включая «`project.board` выдаётся только явно: `platform-admin` и кастомные роли с модулем `project` без строки доски не видят».
- [ ] **Step 7: Коммит** — `feat(access): узел «Доски всех отделов» и доска проекта у ГД (канбан K1.2)`.

---

### Task 3: Механическая замена `token` → `request` в проверках задач (Plans K1.3)

**Files:**
- Modify: `backend/apps/tasks/services/task_service.py` (`load_for_action`, `require_full_edit`, `require_soft_edit`), `backend/apps/tasks/views.py` (40 вызовов, в том числе многострочный `:1127-1128`)

- [ ] **Step 1: База.** `nohup` прогон `../.venv/Scripts/python.exe -m pytest -q apps/tasks -p no:cacheprovider -rf` (~740 тестов, ~8 минут); сохранить в журнал задачи **итог и id упавших** (`-rf`), а не только числа.
- [ ] **Step 2:** заменить сигнатуры (`load_for_action(task_id, request)`, `require_*(task, request)`; внутри пока `request.token`) и все вызовы.
- [ ] **Step 3: Проверка замены** — `grep -n "request.token" apps/tasks/views.py`: остаются только строки, не относящиеся к этим трём функциям (`scope_for`, `_report_for_write`, `board_scope`, `user_id`); `grep -c "load_for_action(\|require_full_edit(\|require_soft_edit(" apps/tasks/views.py` — 40.
- [ ] **Step 4:** тот же прогон шага 1 + `apps/access/tests/test_gate.py` — те же id упавших, что в базе.
- [ ] **Step 5: Коммит** — `refactor(tasks): проверки задачи получают запрос, а не токен (канбан K1.3)`.

---

### Task 4: `TaskScope`, видимость по поддереву, права главы, закрытие утечек (Plans K1.4)

**Files:**
- Create: `backend/apps/tasks/services/task_scope.py`, `backend/apps/tasks/migrations/0027_department_link_kind.py`
- Modify: `backend/apps/tasks/models.py` (`DepartmentLinkKind`, `TaskDepartmentLink.kind`), `services/task_service.py`, `board_scope.py`, `project_service.py`, `roadmap_service.py`, `calendar_service.py` (`:233-241`), `gantt_service.py` (`:64-83`), `task_response.py` (связи, подзадачи), `views.py` (списки `:448`, `:1452`, `:1833`, `:1867`; `roadmap_tasks` `:1829`; `_read_resource_target` `:1903`; делегаты `:574`, `:594`; календарь `:2246`; Ганта `:2106-2120`; 10 вызовов `build_detail`)
- Test: `backend/apps/tasks/tests/org_fixtures.py` (новый помощник), `test_board_visibility.py`, `test_head_rights.py`, `test_leaks_closed.py`, `test_migration_0027.py` (новые); `test_board_scope.py` (новые тесты)

**Interfaces:**
- Consumes: Task 1, Task 2, Task 3.
- Produces:
  - `models.DepartmentLinkKind.MEMBER|ORIGIN`, `TaskDepartmentLink.kind` (S1-27);
  - `task_scope.TaskScope` (поля — спека §K1.3), `task_scope.build(token, company, *, resolution=None)`, `task_scope.for_request(request)`;
  - `task_service.visibility_q(scope) -> Q | None`; `filtered_tasks(*, scope=None, legacy_q=None, …)` (`legacy_q` — только для `task_stats`, S1-11); `list_tasks(*, scope=None, …)`; `get_task(task_id, *, scope=None)`;
  - `task_service.can_edit(task, scope)`, `can_progress(task, scope)`, `is_head_of(task, scope) -> bool`;
  - `task_response.build_detail(task, *, scope)` — `scope` обязателен (фильтрует связи и подзадачи; флаги `can` — в Task 6);
  - `project_service._visible(scope_or_none, refs)`, `roadmap_service._visible(...)` — по `scope.department_ids` (S1-23).

- [ ] **Step 1: Поле `kind` и миграция (S1-27).** Тест `test_migration_0027.py` по образцу `test_roadmap_on_block_migration.py` (`transaction=True`, `MigrationExecutor` на `public`, фикстура «на `0026`», в `finally` — миграция обратно на лист): ключевое утверждение — вставка строки сырым SQL **без** `kind` после миграции даёт `member` (`db_default`). Модель: `kind = CharField(max_length=10, choices=DepartmentLinkKind.choices, default=MEMBER, db_default=MEMBER, db_index=True)`; `makemigrations tasks` → переименовать в `0027_department_link_kind`. Прогон — зелёный; на стенде `migrate_companies`, `tenancy_status` до/после.
- [ ] **Step 2: Фикстуры** `org_fixtures.py`: `make_org()` → отделы `hq`, `it`, `it.dev`, `ops`, `itops`; сотрудники: `EMP_IT` (user 7 — стандартный `token()`), `EMP_DEV` (701), `HEAD_IT` (702, **числится в `hq`**, глава `it`), `HEAD_OPS` (703), `OD` (704), `GD` (705), `PM` (706), `FIRED` (707, `status=INACTIVE`, отдел `it`). Роли — `apps.access.tests.helpers.assign` (`tasks` `write` всем; `tasks.departments.all`/`project.board`/`project.all` `view` директорам и ПМ). Для каждого — `token(user_id=…, sub=…)` и `auth(tok)`.
- [ ] **Step 3: Тесты видимости (красные)** `test_board_visibility.py` — по одному утверждению на тест: `test_dept_member_sees_subdept_task_in_progress`; `test_subdept_member_does_not_see_parent_task`; `test_prefix_is_not_a_subtree` (`it` / `itops`); `test_member_and_origin_links_give_visibility`; `test_head_sees_managed_subtree_from_other_dept` (`HEAD_IT` из `hq`); `test_od_sees_every_department_and_linked_board_task`; `test_gd_same_as_od`; `test_td_adm_see_all_linked_board_tasks`; `test_pm_sees_only_own_project_boards`; `test_private_task_hidden` (параметризованно ОД, ГД, ТД, ПМ, глава, коллега × detail, list, comments, activity); `test_elevated_sees_private_task`; `test_unlinked_board_task_not_opened_by_project_board`; `test_fired_employee_has_no_department` (S1-22); `test_own_department_unknown_to_hr_still_counts` (мок `get_employee_brief` с отделом без строки — задача этого отдела видна, S1-22); `test_hr_disabled_narrows_to_participation`; `test_subresources_follow_subtree` — параметризованно по `test_permissions.SUBRESOURCES` (`test_permissions.py:63-71`) + ежедневный отчёт GET (`views.py:841`) + связь задач: член `it` — 200, член `it.dev` к задаче `it` — 404; `test_real_bpp_gd_role_reads_department_task` (нетранзакционный: `RoleAssignment` на настоящую `Role(code="bpp-gd")` из миграций + `assign(…, "tasks", "read")`; видит задачу отдела, `PATCH` → 403); `test_list_queries_do_not_grow_with_subtree` (разогревающий запрос, затем `CaptureQueriesContext` для поддерева из 1 и из 5 отделов с одинаковым числом строк; `len(five) <= len(one)`); `test_scope_built_once_per_request` (`monkeypatch` счётчиком на `apps.hr.interface.managed_department_ids`; `PATCH` задачи — 1 вызов). Доски: `test_parent_member_sees_subdept_project_board` и `test_holder_opens_roadmap_tasks` (S1-23); в `test_board_scope.py` — `test_holder_sees_tasks_inside_the_board`.
- [ ] **Step 4: Тесты прав главы (красные)** `test_head_rights.py`: `test_head_edits_subdept_task_without_participation` (`PATCH` поля, `supervisor`, `assignees`, `progress`, статус, `DELETE` → 2xx); `test_head_adds_and_removes_delegate` (S1-24); `test_head_cannot_touch_other_dept_task` (задача `ops` у `HEAD_IT` — 404); `test_origin_link_gives_no_rights` (задача `ops` со связью `origin` на `it`: `HEAD_IT` видит, `PATCH` → 403); `test_od_gd_read_only` (`PATCH` → 403, `POST comments` → 201).
- [ ] **Step 5: Тесты утечек (красные)** `test_leaks_closed.py` (S1-17): лента календаря (`GET calendar/timeline/?start=&end=`) и Ганта отчётов (`?ids=<чужая личная>`) не возвращают чужую личную задачу коллеге, ОД и главе; карточка видимой задачи не показывает `summary` связанной невидимой задачи (связь остаётся, заголовок — нет: связь выпадает из `outgoing_links`/`incoming_links`) и не перечисляет невидимые подзадачи; `elevated` видит всё.
- [ ] **Step 6:** `../.venv/Scripts/python.exe -m pytest -q apps/tasks/tests/test_board_visibility.py apps/tasks/tests/test_head_rights.py apps/tasks/tests/test_leaks_closed.py apps/tasks/tests/test_board_scope.py` — красные.
- [ ] **Step 7: `task_scope.py`** (спека §K1.3): `elevated` — без `hr`/`access`; иначе `hr.get_employee_brief` (своё место; `status != "active"` — без отдела, S1-22), `hr.managed_department_ids`, одно `hr.department_subtree_ids(own ∪ managed)`; `department_ids ⊇ {own} ∪ managed` даже без строки в `hr` (S1-22); `managed_subtree` — поддеревья только управляемых; `flags_for` с `resolution` из `request.access_resolution`, если совпадают компания (`current_company_or_none()`) и `user_id`; `ServiceDisabled` — `fallback("tasks.task_scope.hr_unavailable", …, expected=True)` и пустые отделы. `for_request` — кэш `request.task_scope = (company, user_id, scope)`.
- [ ] **Step 8: `task_service`**: `visibility_q(scope)` (формула спеки; отделы — `Exists` по `TaskDepartmentLink`); удалить `_employee_visibility_q`; `task_stats` строит прежнее правило через `_report_visibility_q(user_id, own_department_id)` и передаёт его `filtered_tasks(legacy_q=…)` — поведение статистики не меняется (S1-11); `load_for_action(task_id, request)` → `get_task(task_id, scope=for_request(request))`; `is_head_of(task, scope)` — `task.department_id ∈ scope.managed_subtree` или `member`-связь в нём (`department_links` из prefetch); `can_edit(task, scope)` — прежнее правило **или** `is_head_of`; `can_progress` — через `can_edit`; `require_*` — по `for_request(request)`. `soft_edit_q` не трогать (S1-09).
- [ ] **Step 9: Вызывающие** — четыре списка на `scope=task_scope.for_request(request)`; `roadmap_tasks` (`:1829`) и `_read_resource_target` (`:1903`) — `refs=board_scope.refs_for_request(request)`; `project_service._visible`/`roadmap_service._visible` — `scope.department_ids` вместо одного отдела (S1-23); `board_scope.board_refs_for(..., resolution=None)`; делегаты (`:574`, `:594`) — «руководитель, глава (`is_head_of`) или `elevated`» (S1-24); календарь и Ганта — выборка через `visibility_q(for_request(request))`; `build_detail(task, *, scope)` во всех 10 вызовах, связи и подзадачи — только видимые (`visibility_q(scope)` по id связанных задач одним запросом).
- [ ] **Step 10:** прогон шага 6 — зелёные; затем полный `apps/tasks` (как Task 3, шаг 1) + `apps/access/tests/test_gate.py apps/core/tests/test_app_isolation.py` — новых упавших против базы нет; если старый тест ожидал прежнюю узкую видимость — правка только при противоречии K-04, с перечнем в сообщении коммита.
- [ ] **Step 11: Коммит(ы)** — `feat(tasks): вид связи задачи с отделом (канбан K1.4)` (шаг 1) и `feat(tasks): видимость по поддереву отдела, права главы, видимость в календаре и Ганте (канбан K1.4)`.

---

### Task 5: Отдел задачи, автор, начальный статус, родитель (Plans K1.5)

**Files:**
- Create: `backend/apps/tasks/services/department_rules.py`
- Modify: `backend/apps/tasks/services/task_service.py` (`create_task`, `update_task`, `TRACKED_FIELDS`), `views.py` (`_create_task`, `_update_task`), `task_response.py` (`_common_fields` `:100, :122-126` — `department_ids` только из `member`, S1-20)
- Modify: `backend/apps/tasks/tests/test_tasks_api.py` (`test_create_task_stores_multi_department_set` `:213-218` — на фикстуре `org_fixtures` или `admin_token()`)
- Test: `backend/apps/tasks/tests/test_department_rules.py` (новый)

**Interfaces:**
- Consumes: Task 4.
- Produces: `department_rules.assert_department_allowed(scope, department_ids)`, `assert_department_change(scope, task, effective_ids)`; `create_task(data, user_id, *, scope)`, `update_task(task_id, data, user_id, *, scope)`.

- [ ] **Step 1: Тесты (красные)** — спека §K1.4 «Тесты», по одному утверждению на тест, плюс: `test_hr_disabled_with_department_is_503_before_403` (рядовой с чужим отделом при выключенном `hr` — 503); `test_head_patch_into_own_seat_department_needs_transfer` (`HEAD_IT` из `hq` переводит задачу `it.dev` в `hq` → 422 `task_department_use_transfer`); `test_department_ids_only_realign_is_checked` (`PATCH {department_ids: [ops]}` главой `it` → 422, задача не изменилась); `test_reporter_patch_only_elevated` (глава → 422 `task_reporter_forbidden`, `elevated` → 200, S1-21); `test_parent_must_be_visible` (создание и `PATCH` с `parent_id` невидимой задачи → 404, S1-18); `test_response_department_ids_exclude_origin` (S1-20); `test_head_creating_in_foreign_dept_stays_reporter` (S1-16: автор = глава, связь `origin`, исполнители → 422).
- [ ] **Step 2:** `../.venv/Scripts/python.exe -m pytest -q apps/tasks/tests/test_department_rules.py` — красные.
- [ ] **Step 3: `department_rules.py`** — порядок проверок спеки §K1.4 (существование и активность — первыми; `elevated` — без ограничений; глава на создании — любой, на `PATCH` — `managed_subtree`; рядовой — `department_ids`).
- [ ] **Step 4: `create_task`/`update_task`** — `effective_ids` считаются после перекладки `department_ids[0]` (`task_service.py:478-479`) и до проверки; `reporter_id` в создании — только `elevated` (K-25), в `PATCH` — 422 (S1-21); начальный статус у не-`elevated` — `backlog`/`todo` (`task_status_initial`); `parent_id` — `get_task(parent_id, scope=scope)` (404, S1-18); глава в чужой отдел — `task_transfer_assignees` при исполнителях, строка `origin`; `update_task` заменяет только `member`, `origin` в новом наборе → `member`; `"department_id"` в `TRACKED_FIELDS`.
- [ ] **Step 5:** прогон шага 2 + правка `test_create_task_stores_multi_department_set` + полный `apps/tasks` — новых упавших нет; `makemigrations --check --dry-run` чист.
- [ ] **Step 6: Коммит** — `feat(tasks): правила отдела задачи, автор и родитель (канбан K1.5)`.

---

### Task 6: Перенос, «Взять в работу», `scope` списка, флаги `can` (Plans K1.6)

**Files:**
- Create: `backend/apps/tasks/services/transfer.py`
- Modify: `backend/apps/tasks/services/task_service.py` (`claim`, `can_claim`), `task_response.py` (`can`, `department_links` в карточке; `can.claim` в списке), `schemas.py` (`TransferIn`, `TaskCan`, `TaskDepartmentLinkOut`, поля `TaskDetailResponse`, `TaskListResponse`), `views.py` (`task_transfer`, `task_claim`, `_list_tasks` — `scope`), `urls.py`
- Modify: `backend/apps/tasks/tests/fixtures/contracts.json` (`TaskDetailResponse`: `can`, `department_links`; `TaskListResponse`: `can`)
- Test: `backend/apps/tasks/tests/test_transfer.py`, `test_claim.py`, `test_list_scope.py`, `test_detail_can.py` (новые)

**Interfaces:**
- Consumes: Task 1 (`department_manager_user_ids`), Task 4, Task 5.
- Produces:
  - `POST /api/tasks/v1/tasks/<id>/transfer[/]` — `TransferIn{department_id: int, sender_department_id: int | None}` (`extra="forbid"`) → `build_detail`;
  - `POST /api/tasks/v1/tasks/<id>/claim[/]` → `build_detail`;
  - `GET /api/tasks/v1/tasks/?scope=mine|department`;
  - карточка: `can = {full_edit, soft_edit, comment, transfer, claim, delete}`, `department_links = [{department_id, name, kind}]`; строка списка: `can = {claim}`.

- [ ] **Step 1: Тесты (красные)** — спека §K1.5 «Тесты», плюс находки проверок:
  - `test_transfer.py`: всё из спеки; `test_invisible_task_is_404_not_403`; `test_transfer_notifies_target_head` (утверждение по строке центра уведомлений для `HEAD_OPS` с заголовком `task_transferred:…`, как `test_tasks_api.py:206-211`; получатель может открыть задачу — `GET` 200); `test_hr_off_elevated_transfer_succeeds` (поиск главы при выключенном `hr` — `fallback`, перенос 200); `test_sender_cannot_claim_after_transfer` (сотрудник `it` после переноса задачи в `ops` — `claim` 403);
  - `test_claim.py`: всё из спеки; `test_claim_forbidden_via_origin_link`; `test_two_claims_one_primary` (`transaction=True`, два потока — один 200, другой 409);
  - `test_list_scope.py`: 60 задач отдела с явным `created_at` новее своей задачи (`.update(created_at=…)`); контроль — без `scope` своя задача **не** на первой странице из 50; с `scope=mine` — на ней; `scope=department` — без задач только доски проекта; `scope=x` → 422;
  - `test_detail_can.py`: для каждого флага × ролей (участник, глава, коллега, ОД, `elevated`) значение совпадает с исходом ручки; `can` есть в ответах создания, `PATCH` и переходов; `can.claim` в строке списка совпадает с исходом `claim`.
- [ ] **Step 2:** `../.venv/Scripts/python.exe -m pytest -q apps/tasks/tests/test_transfer.py apps/tasks/tests/test_claim.py apps/tasks/tests/test_list_scope.py apps/tasks/tests/test_detail_can.py apps/tasks/tests/test_contract_parity.py` — красные.
- [ ] **Step 3: `transfer.py`** — спека §K1.5: `load_for_action` → `transaction.atomic` → `Task.objects.select_for_update().get(pk=…, is_deleted=False)` (не через `filtered_tasks` — `DISTINCT` с `FOR UPDATE` нельзя); `DomainError` с кодами §1; журнал — `task_service._log`; уведомление — `_notify` синхронно, поиск главы в `try/except ServiceDisabled` → `fallback(…, expected=True)`.
- [ ] **Step 4: `claim`/`can_claim`** — один предикат (S1-07: основной отдел или `member`-связь ∈ `scope.department_ids`; без `origin`, «всех отделов», досок), блокировка отдельным `select_for_update`, затем проверка «нет исполнителя, статус `backlog`/`todo`».
- [ ] **Step 5: Ручки и `scope`** — `api_view(methods=("POST",), module="tasks", level="write", body=…)`, маршруты с косой чертой и без; `_list_tasks`: `scope=mine` → `Q_part(u)`, `scope=department` → отделы `scope.department_ids` (поле и связи), иное → 422.
- [ ] **Step 6: Флаги** — `build_detail(task, *, scope)`: `can` и `department_links` (имена батчем через `hydration`); `build_list(tasks, *, scope=None)`: `can.claim` из загруженных строк (без новых запросов — проверить `CaptureQueriesContext`); схемы и `contracts.json`.
- [ ] **Step 7:** прогон шага 2 + полный `apps/tasks` + `apps/access/tests/test_gate.py` — зелёные.
- [ ] **Step 8: Коммит** — `feat(tasks): перенос в отдел и «Взять в работу» (канбан K1.6)`.

---

### Task 7: Фронт — серверные вкладки, «Взять в работу», диалог переноса (Plans K1.7)

**Files:**
- Modify: `frontend/src/api/tasks.ts` (`fetchTasks` — `scope`; `claimTask`, `transferTask`), `frontend/src/types/tasks.ts` (`TaskCan`, `TaskDepartmentLink`; `can?`, `department_links?`)
- Modify: `frontend/src/pages/hr/EmployeeTasks.tsx`, `HRTaskDetail.tsx`, `EmployeeTaskDetail.tsx`
- Create: `frontend/src/features/tasks/board/TransferDialog.tsx` (каталог `features/tasks` — новый)
- Modify: `frontend/public/locales/ru/translation.json`, `frontend/public/locales/en/translation.json`
- Test: `frontend/src/pages/hr/__tests__/EmployeeTasks.test.tsx`, `frontend/src/features/tasks/board/__tests__/TransferDialog.test.tsx` (новые)

- [ ] **Step 1: База** — `cd frontend`; `npx tsc --noEmit -p tsconfig.app.json 2>&1 | grep -c "error TS"` и `npm run typecheck:tests 2>&1 | grep -c "error TS"` — записать оба числа.
- [ ] **Step 2: Тесты (красные; файлы создать до запуска — иначе vitest ответит «No test files found»)** — моки по образцу `HRProjectsLink.test.tsx:21-50` (`vi.mock('@/api/tasks')`, `TasksLayout`, `KanbanBoard`), `renderWithProviders` (шпион на `queryClient.invalidateQueries`). `EmployeeTasks`: вкладка «Мои» шлёт `scope=mine`, «Отдела» — `scope=department`; кнопка «Взять в работу» только у строк с `can.claim`; нажатие — `claimTask`, затем инвалидация `['employee-tasks']` и `['hr-tasks']`. `TransferDialog`: нет текущего и неактивных отделов; при 403/409/422 — текст `tasks.errors.<code>` или `detail`.
- [ ] **Step 3:** `npx vitest run src/pages/hr/__tests__/EmployeeTasks.test.tsx src/features/tasks/board/__tests__/TransferDialog.test.tsx` — красные.
- [ ] **Step 4: Реализация** — спека §K1.5 «Фронт»: клиентские фильтры `EmployeeTasks.tsx:87-106` удалить (поиск оставить), `acceptMutation` → `claimTask`; «Kanban»/«Table» — существующие ключи `hr.tasks.kanban`/`hr.tasks.table` (`ru/translation.json:1128-1129`), «Loading...» — `common.loading` (если нет — новый); подпись вкладки — `hr.tasks.department`; `TransferDialog` (shadcn `Dialog` + `Command`, отделы — `GET hr/v1/departments`); «Отправить в отдел» на обеих страницах `/tasks/:id` при `task.can?.transfer`; ответ `task_department_use_transfer` в `HRTaskDetail` — тост с кнопкой открытия диалога. Ключи `tasks.transfer.*`, `tasks.claim.*`, `tasks.errors.*` — в `ru` и `en`.
- [ ] **Step 5:** прогон шага 3 — зелёные; `npx vitest run src/lib/i18n src/pages/hr src/features/tasks`; `npm run lint`; `tsc` и `typecheck:tests` — не больше чисел шага 1.
- [ ] **Step 6: Коммит** — `feat(tasks): серверные вкладки задач, «Взять в работу» и перенос в отдел на фронте (канбан K1.7)`.

---

### Task 8: Документация, стенд, регрессия, ревью (Plans K1.8)

**Files:**
- Modify: `API.md` (раздел «apps.tasks»), `STRUCTURE.md` (§4.2), `CLAUDE.md` (абзац «Канбан-доски, этап 1»), `Plans.md` (статусы фазы K)

- [ ] **Step 1: `API.md`** — `tasks/<id>/transfer`, `tasks/<id>/claim`, `?scope=`, `can` (карточка и список), `department_links`, коды ошибок спеки §1; `projects/` — «задачи доски видны держателю `project.board` целиком»; `tasks/` — видимость по поддереву отдела; `calendar/timeline/` и Ганта — по видимости задач; `department_ids` ответа — только отделы-участники.
- [ ] **Step 2: `STRUCTURE.md` §4.2** — абзац «Видимость и права» (`TaskScope`, поддерево, глава, узлы, `origin`, где ещё действует видимость); `CLAUDE.md` — короткий абзац (узлы, `TaskScope` на `request.task_scope`, `load_for_action(task_id, request)`, `build_detail(task, *, scope)`, ссылки на мастер-план и спеку) и пометка выкатки: «`project.board` теперь только явной строкой — `platform-admin` и кастомные роли с модулем `project` доски проектов теряют».
- [ ] **Step 3: Регрессия** (один прогон, `nohup`, ~25–30 минут): `apps/tasks apps/hr apps/access apps/project apps/tender/tests/test_roles.py apps/core/tests/test_app_isolation.py apps/core/tests/test_invariants.py apps/core/tests/test_platform_today.py apps/core/tests/test_metrics*` — зелёные или только записи `backend/ci-known-failures.txt`; фронт — `npx vitest run`, `npm run lint`, `tsc` и `typecheck:tests` по базе.
- [ ] **Step 4: Стенд** — `migrate_shared`, `migrate_companies`, сиды (Global Constraints); руками: сотрудник подотдела видит взятую в работу задачу отдела; «Взять в работу»; глава переносит задачу со страницы `/tasks/:id`; ОД открывает `/manage/projects` → «Задачи» и видит задачи доски, правка недоступна; вход ОД на `/manage/projects` есть (меню `TasksLayout` показывает пункт только `elevated` — проверить путь через `ProfileSidebar` и карточку «Проекта»).
- [ ] **Step 5: `harness-review`** — Critical/Major исправить; повторное ревью по исправлениям.
- [ ] **Step 6: Коммит** — `docs(tasks): видимость и права задач, этап 1 канбан-досок (K1.8)`; статусы K1.1–K1.8 в `Plans.md` — `cc:完了` со ссылками на коммиты. Пуш и PR — по команде пользователя.
