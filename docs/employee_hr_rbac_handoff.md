# Employee Tasks + HR RBAC Handoff

Дата контекста: 2026-05-05. Репозиторий: `D:\HTQWeb-main`.

## Что уже реализовано

### Employee task access

- `employee` и legacy `user` получили доступ к существующим task-разделам:
  - `/tasks`
  - `/tasks/roadmap`
  - `/tasks/reports`
- Общая frontend-логика доступа вынесена в `frontend/src/lib/auth/roles.ts`.
- Sidebar/header/bottom nav/task routers используют общий helper.
- `EmployeeTasks` и `EmployeeTaskDetail` больше не вызывают `hr/v1/employees/users/`, поэтому обычный employee не ловит `403` на HR-only endpoint.

### Task-service backend scope

- Добавлена миграция:
  - `services/task/alembic/versions/003_employee_department_scope.py`
- Добавлены связи:
  - `task_users.email`
  - `task_users.department_id -> task_departments.id`
  - `project_versions.department_id -> task_departments.id`
- `task-service` теперь вычисляет роль из claims user-service:
  - `is_staff`
  - `is_superuser`
  - `is_admin`
  - plain users становятся `employee`
- Employee visibility rules:
  - обычный список задач: свои assigned/reported + новые свободные задачи своего отдела;
  - reports: только свои завершенные `done/closed` + новые свободные `open` задачи своего отдела;
  - roadmaps: только `project_versions.department_id == employee.department_id`;
  - employee без `department_id` получает пустые department-scoped данные.
- `/api/tasks/v1/tasks/stats/` перенесен до `/{task_id}/`, чтобы не получать `422` из-за route shadowing.

### HR employee access levels

Добавлен backend helper:

- `services/hr/app/auth/hr_access.py`

Уровень HR определяется из HR employee profile, department/position:

- `junior`
- `middle` / typo-compatible `middel`
- `senior`
- `co_hr`

Матрица, реализованная сейчас:

| HR level | Видимость employees | Права |
|---|---|---|
| `junior` | только свой отдел | read-only |
| `middle` | только свой отдел | basic edit в своем отделе, без transfer/position/terminate/suspend |
| `senior` | все отделы | create/update/transfer, без delete и без создания platform user |
| `co_hr` | все отделы | полный доступ, включая delete и create platform user |

Staff/admin/superuser из JWT считаются `co_hr`.

Backend endpoints, где применен scope:

- `GET /api/hr/v1/employees/hr-level/`
- `GET /api/hr/v1/employees/`
- `GET /api/hr/v1/employees/{id}/`
- `PUT /api/hr/v1/employees/{id}/`
- `DELETE /api/hr/v1/employees/{id}/`
- `POST /api/hr/v1/employees/{id}/transfer`
- `GET /api/hr/v1/employees/{id}/pmos`
- `GET /api/hr/v1/employees/{id}/history`
- `GET /api/hr/v1/employees/{id}/documents`
- `GET /api/hr/v1/employees/users/`
- `POST /api/hr/v1/employees/users/`

### HR frontend

- `frontend/src/hooks/useHRLevel.ts` теперь возвращает:
  - `level`
  - `hasHrAccess`
  - `isCoHr`
  - `isSenior`
  - `isMiddle`
  - `isJunior`
  - `canReadAll`
  - `canWriteBasic`
  - `canCreateEmployee`
  - `canTransferEmployee`
  - `canDeleteEmployee`
  - `canListUserOptions`
  - `canManageUserOptions`
- `frontend/src/components/hr/HRLayout.tsx` фильтрует HR navigation по HR level.
- `Header.tsx` и `ProfileSidebar.tsx` показывают HR entrypoint не только по profile roles, но и по backend `hr-level`.
- `frontend/src/pages/hr/HREmployees.tsx` переведен на `frontend/src/api/hr.ts`, учитывает capabilities и больше не предполагает старый API shape.
- `frontend/src/api/hr.ts` теперь нормализует paginated `{items}` ответы и employee aliases:
  - `user -> user_id`
  - `position -> position_id`
  - `department -> department_id`
  - `date_hired -> hire_date`
  - `date_dismissed -> termination_date`
  - `notes -> bio`

## Основные затронутые файлы

Frontend:

- `frontend/src/lib/auth/roles.ts`
- `frontend/src/hooks/useHRLevel.ts`
- `frontend/src/api/hr.ts`
- `frontend/src/api/tasks.ts`
- `frontend/src/components/Header.tsx`
- `frontend/src/components/BottomNav.tsx`
- `frontend/src/components/profile/ProfileSidebar.tsx`
- `frontend/src/components/hr/HRLayout.tsx`
- `frontend/src/components/tasks/TaskRouter.tsx`
- `frontend/src/components/tasks/TaskDetailRouter.tsx`
- `frontend/src/pages/hr/HREmployees.tsx`
- `frontend/src/pages/hr/EmployeeTasks.tsx`
- `frontend/src/pages/hr/EmployeeTaskDetail.tsx`
- `frontend/src/pages/hr/HRRoadmap.tsx`
- `frontend/src/types/hr.ts`
- `frontend/src/types/tasks.ts`
- `frontend/src/lib/auth/roles.test.ts`

Task-service:

- `services/task/app/auth/dependencies.py`
- `services/task/app/api/v1/tasks.py`
- `services/task/app/api/v1/versions.py`
- `services/task/app/models/task.py`
- `services/task/app/models/user_replica.py`
- `services/task/app/models/version.py`
- `services/task/app/repositories/task_repo.py`
- `services/task/app/repositories/__init__.py`
- `services/task/app/schemas/version.py`
- `services/task/app/workers/replica_sync.py`
- `services/task/alembic/versions/003_employee_department_scope.py`
- `services/task/tests/integration/test_employee_scoping.py`

HR-service:

- `services/hr/app/auth/hr_access.py`
- `services/hr/app/api/v1/employees.py`
- `services/hr/app/services/department_service.py`
- `services/hr/app/services/employee_service.py`
- `services/hr/app/workers/actors.py`
- `services/hr/tests/integration/test_hr_employee_access.py`

## Проверки, которые уже проходили

Task-service:

```powershell
python -m compileall app
```

```powershell
cmd /c docker compose run --rm --no-deps -e PYTHONPATH=/app -e JWT_SECRET=change-me -e TEST_DATABASE_URL=postgresql+asyncpg://htqweb:change-me@db:5432/htqweb_test -v "%CD%\services\task:/app" task-service pytest tests/integration/test_employee_scoping.py -q
```

Результат: `5 passed`.

HR-service:

```powershell
python -m compileall app
```

```powershell
cmd /c docker compose run --rm --no-deps -e PYTHONPATH=/app -e JWT_SECRET=change-me -e TEST_DATABASE_URL=postgresql+asyncpg://htqweb:change-me@db:5432/htqweb_test -v "%CD%\services\hr:/app" hr-service pytest tests/integration/test_hr_employee_access.py -q
```

Результат: `6 passed`.

Frontend:

```powershell
cmd /c npx vitest run src/lib/auth/roles.test.ts
```

Результат: `3 passed`.

Targeted TypeScript check for touched files:

```powershell
cmd /c "npx tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | findstr /i ""src/api/hr src/api/tasks src/hooks/useHRLevel src/lib/auth/roles src/components/hr/HRLayout src/components/Header src/components/BottomNav src/components/profile/ProfileSidebar src/components/tasks/TaskRouter src/components/tasks/TaskDetailRouter src/pages/hr/HREmployees src/pages/hr/HRRoadmap src/pages/hr/HRReports src/pages/hr/EmployeeTasks src/pages/hr/EmployeeTaskDetail src/types/hr src/types/tasks"""
```

Результат: no output, exit `1` only because `findstr` found no matching errors.

Full frontend `tsc` still fails on unrelated pre-existing areas:

- calendar
- messenger
- WebRTC
- AdminChats
- old HR pages outside touched scope
- Settings OAuth panel

## Важные допущения

- `done` и `closed` считаются завершенными task statuses.
- Новая task для взятия employee = `status == open`, `assignee_id is NULL`, task department equals employee department.
- HR levels пока выводятся из HR position/department strings, потому что отдельной таблицы HR roles нет.
- `CO HR` считается максимальным HR role.
- `middle` и typo `middel` оба распознаются.
- `HR-менеджер` / `HR Manager` классифицируется как `middle`.
- `Senior HR` классифицируется как `senior`.
- Staff/admin/superuser считаются `co_hr`.

## Что важно сделать после pull/checkout

1. Применить task-service миграцию:

```powershell
alembic upgrade head
```

из контекста `services/task`.

2. Перезапустить backend-сервисы:

- `task-service`
- `hr-service`
- worker/replica sync, если запущены отдельно

3. Если браузер все еще показывает:

```text
GET /api/tasks/v1/tasks/stats/ 422
```

значит работает старый `task-service` процесс. После перезапуска route должен отвечать корректно.

4. Если employee видит:

```text
GET /api/hr/v1/employees/users/ 403
```

проверь, что frontend пересобран и используется обновленный `EmployeeTasks` / `EmployeeTaskDetail`; employee task pages больше не должны вызывать этот endpoint.

## Осторожно с git

В worktree уже были unrelated changes до этой работы:

- `.env`
- `docker-compose.yml`
- часть `services/hr/app/core/settings.py`
- `services/hr/app/main.py`
- `services/hr/app/schemas/employee.py`
- `services/hr/requirements.txt`
- untracked `services/adminjs/`, mongo docs и служебные docs/scripts

Не откатывать их вслепую.
