# Отчет по рефакторингу

Дата: 27 марта 2026
Проект: `D:\HTQWeb1`

## Цель
Сделать кодовую базу более понятной для команды: разделить ответственность по слоям, убрать дублирование логики, сохранить обратную совместимость API и подтвердить стабильность сборкой/тестами.

## Краткий итог
- Backend-модуль `tasks` разделен на `services` (бизнес-логика) и `viewsets` (HTTP-слой).
- Frontend-роутинг вынесен в декларативную конфигурацию, `App.tsx` упрощен.
- Логика профиля пользователя централизована через единый hook `useActiveProfile`.
- Добавлен архитектурный документ для онбординга коллег.
- Проверки `manage.py check`, backend tests, frontend build и frontend tests проходят.

## Что изменено

### Backend
- Разделен монолит `backend/tasks/views.py` на слои:
  - доступ/видимость,
  - фильтры задач,
  - статистика,
  - календарь,
  - уведомления,
  - проверки связей задач.
- Введен слой `backend/tasks/viewsets/` для отдельных API-доменов.
- Сохранена совместимость импортов через `backend/tasks/views.py` (compatibility export).
- Добавлен legacy alias задач под `/api/hr/*`, чтобы не ломать старые клиенты и существующие тесты.

### Frontend
- `frontend/src/App.tsx` переведен на модульную схему маршрутов.
- Добавлены отдельные модули:
  - lazy page registry,
  - route definitions,
  - prefetch strategy,
  - app-level components (`PageLoader`, `AppErrorBoundary`).
- Централизована auth/profile логика:
  - storage helpers,
  - role helpers,
  - единый hook `useActiveProfile`.
- На новый профиль-хук переведены ключевые компоненты (`RequireAuth`, `BottomNav`, `Header`, task routers, календарный виджет).

### Документация
- Добавлен `docs/architecture.md` с правилами структуры и быстрым контекстом для нового разработчика.
- В `README.md` добавлена ссылка на архитектурную документацию.

## Измененные файлы

### Добавлены
- `backend/tasks/services/__init__.py`
- `backend/tasks/services/access.py`
- `backend/tasks/services/calendar.py`
- `backend/tasks/services/links.py`
- `backend/tasks/services/notifications.py`
- `backend/tasks/services/stats.py`
- `backend/tasks/services/task_queries.py`
- `backend/tasks/viewsets/__init__.py`
- `backend/tasks/viewsets/calendar.py`
- `backend/tasks/viewsets/common.py`
- `backend/tasks/viewsets/tasks.py`
- `frontend/src/app/components/AppErrorBoundary.tsx`
- `frontend/src/app/components/PageLoader.tsx`
- `frontend/src/app/routing/lazyPages.ts`
- `frontend/src/app/routing/prefetch.ts`
- `frontend/src/app/routing/routeDefinitions.ts`
- `frontend/src/app/routing/types.ts`
- `frontend/src/hooks/useActiveProfile.ts`
- `frontend/src/lib/auth/profileStorage.ts`
- `frontend/src/lib/auth/roles.ts`
- `docs/architecture.md`

### Изменены
- `backend/HTQWeb/urls.py`
- `backend/tasks/urls.py`
- `backend/tasks/views.py`
- `frontend/src/App.tsx`
- `frontend/src/components/BottomNav.tsx`
- `frontend/src/components/Header.tsx`
- `frontend/src/components/RequireAuth.tsx`
- `frontend/src/components/calendar/CalendarWidget.tsx`
- `frontend/src/components/tasks/TaskDetailRouter.tsx`
- `frontend/src/components/tasks/TaskRouter.tsx`
- `README.md`

## Проверки и результат
- `python manage.py check` (backend): PASS
- `python manage.py test tasks` (backend): PASS, 17/17
- `npm run build` (frontend): PASS
- `npm test` (frontend): PASS, 7/7
- `npm run lint` (frontend): FAIL по существующим историческим проблемам проекта (в основном `no-explicit-any` и несколько legacy правил), не вызвано данным рефакторингом

## Примечания по совместимости
- API задач доступен в двух префиксах:
  - основной: `/api/...`
  - legacy: `/api/hr/...`
- Это сделано для безопасного перехода без поломки старых интеграций.
