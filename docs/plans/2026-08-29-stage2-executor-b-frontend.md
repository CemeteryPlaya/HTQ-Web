# Стадия 2 «Доступ и роли» · Исполнитель B (фронтенд) — план реализации

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ СУБ-СКИЛЛ: используйте
> `superpowers:subagent-driven-development` (рекомендуется) или
> `superpowers:executing-plans` для выполнения задача-за-задачей. Шаги
> размечены чекбоксами (`- [ ]`).

**Цель:** перевести фронт с мёртвого словаря ролей на пару «модуль + уровень»,
и дать редактор каталога ролей, панель ролей должности и переключатель
иерархии.

**Архитектура:** права приезжают одним ответом `GET /api/access/v1/me` (та же
карта дублируется в профиле, чтобы не делать второй запрос на каждой загрузке).
Хук `usePermissions` — единственный потребитель; маршруты и навигация спрашивают
у него уровень по модулю. Скрытие в интерфейсе — удобство, рубеж остаётся на
бэкенде.

**Стек:** React 18, TypeScript, Vite, react-router-dom, @tanstack/react-query,
vitest, @xyflow/react + @dagrejs/dagre (диаграмма).

**Спека:** [2026-08-29-stage2-access-and-roles-spec.md](2026-08-29-stage2-access-and-roles-spec.md)
— §3 (уровни), §4 (замороженный контракт API), §6 (задачи B1–B8).

**Парный план:** [исполнитель A (бэкенд)](2026-08-29-stage2-executor-a-backend.md).
До его задачи 7 всё разрабатывается против фикстуры из задачи 1.

---

## Глобальные ограничения

- **Ветка `structure-refactoring-1`**, ответвлённая от `structure-refactoring`.
  Новых веток не создавать.
- **Зона — только `frontend/**`.** Файлы `backend/**` и `docs/**` принадлежат
  исполнителю A; правка любого из них ломает бесконфликтное слияние.
  ⚠️ Это относится и к документации: **`docs/**` не трогать**, включая эту
  спеку — расхождение с контрактом фиксирует A правкой документа.
- **Контракт §4 заморожен.** Первое же расхождение живого API с документом —
  повод остановиться и сообщить A, а не подстроиться в коде.
- **Уровни:** `none < read < write < admin`. Доступ разрешён, если
  эффективный уровень **не ниже** требуемого. Порядок объявляется один раз
  (`LEVEL_ORDER` в `src/api/access.ts`) и больше нигде не повторяется.
- **`useHRLevel` не удаляется и не переписывается** — он в зоне переработки
  заказчика (спека §1.6).
- **Команды** (из `frontend/`):
  - `npm test` — весь набор vitest
  - `npx vitest run <файл> -t "<имя>"` — один тест
  - `npx tsc --noEmit -p tsconfig.json` — типы
  - `npm run lint`
- **Коммит после каждой задачи**, сообщение на русском, префикс
  `feat(access):` / `refactor(auth):` / `test(auth):`.

---

## Структура файлов

**Создаются:**

| Файл | Ответственность |
|---|---|
| `frontend/src/api/access.ts` | клиент `/api/access/v1`, `LEVEL_ORDER`, `atLeastLevel` |
| `frontend/src/types/access.ts` | типы контракта §4 |
| `frontend/src/hooks/usePermissions.ts` | единственный потребитель `/me` |
| `frontend/src/hooks/__tests__/usePermissions.test.tsx` | фикстура §4.5 |
| `frontend/src/test/fixtures/access.ts` | фикстура ответа `/me` до готовности A |
| `frontend/src/pages/access/RoleCatalog.tsx` | каталог ролей (плоский список) |
| `frontend/src/components/access/RolePermissionMatrix.tsx` | матрица «модуль × уровень» |
| `frontend/src/components/access/PositionRolesPanel.tsx` | роли должности + личные назначения |
| `frontend/src/components/hr/OrgChart/HierarchySwitch.tsx` | переключатель иерархии |
| `frontend/src/app/routing/routeAccess.test.ts` | тест-сторож маршрутов |

**Правятся:**

| Файл | Правка |
|---|---|
| `frontend/src/api/endpoints.ts` | `access: 'access/v1'` |
| `frontend/vite.config.ts` | проксирование `^/api/access/` |
| `frontend/src/app/routing/types.ts` | `RouteRole` → `RouteRequirement` |
| `frontend/src/components/RequireAuth.tsx` | гейт по модулю и уровню |
| `frontend/src/app/routing/routeDefinitions.ts` | 47 гейтов на пару «модуль + уровень» |
| `frontend/src/lib/auth/roles.ts` | удаление словаря |
| `frontend/src/components/hr/OrgChart/index.tsx` | переключатель иерархии |
| навигация (пункты меню) | скрытие по уровню `none` |

⚠️ **Точное число гейтов — 47**, не 45: `requiresRole: 'hr'` — 27,
`'admin'` — 16, `'editor'` — 3 (`grep -c "requiresRole" routeDefinitions.ts`).
Всего защищённых маршрутов (`requiresAuth: true`) — 99; остальные 52 остаются
без гейта модуля, как и были.

---

## Задача 1: Клиент доступа, типы и фикстура (спека B1)

**Files:**
- Create: `frontend/src/types/access.ts`, `frontend/src/api/access.ts`,
  `frontend/src/test/fixtures/access.ts`
- Modify: `frontend/src/api/endpoints.ts`, `frontend/vite.config.ts`

**Interfaces:**
- Produces: `AccessLevel`, `PermissionMap`, `MeResponse`, `Role`, `RolePermission`,
  `LEVEL_ORDER`, `atLeastLevel(have, need)`, `accessApi.*`, `meFixture`.

- [ ] **Шаг 1: Написать падающий тест на сравнение уровней**

`frontend/src/api/__tests__/access.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { atLeastLevel, LEVEL_ORDER } from '../access';

describe('уровни доступа', () => {
  it('упорядочены строго по возрастанию', () => {
    expect([LEVEL_ORDER.none, LEVEL_ORDER.read, LEVEL_ORDER.write, LEVEL_ORDER.admin])
      .toEqual([0, 1, 2, 3]);
  });

  it('пропускает равный и более высокий уровень', () => {
    expect(atLeastLevel('write', 'write')).toBe(true);
    expect(atLeastLevel('admin', 'write')).toBe(true);
    expect(atLeastLevel('read', 'write')).toBe(false);
    expect(atLeastLevel('none', 'read')).toBe(false);
  });
});
```

- [ ] **Шаг 2: Прогнать — обязан упасть**

Run: `npx vitest run src/api/__tests__/access.test.ts`
Expected: FAIL, `Failed to resolve import "../access"`

- [ ] **Шаг 3: Типы контракта**

`frontend/src/types/access.ts`:

```ts
/** Типы контракта `/api/access/v1` — спека стадии 2, §4.
 *  Менять только вслед за правкой документа: контракт заморожен. */

export type AccessLevel = 'none' | 'read' | 'write' | 'admin';
export type ScopeKind = 'company' | 'department' | 'site';

export interface AccessScope {
  kind: ScopeKind;
  id: number | null;
}

/** Модули со значением `none` в ответе ОТСУТСТВУЮТ: нет ключа — нет доступа. */
export type PermissionMap = Record<string, { level: AccessLevel; scope: AccessScope }>;

export interface MeResponse {
  company: string | null;
  permissions: PermissionMap;
  /** Компании ниже по дереву владения; пусто у всех, кроме руководителей. */
  subordinate_companies: string[];
}

export interface Role {
  id: number;
  code: string;
  title: string;
  is_system: boolean;
}

export interface RolePermission {
  module: string;
  level: AccessLevel;
}

export interface PositionRole {
  role_id: number;
  code: string;
  title: string;
}

export interface UserAssignment {
  role_id: number;
  scope_kind: ScopeKind;
  scope_id: number | null;
}
```

- [ ] **Шаг 4: Клиент**

`frontend/src/api/access.ts`:

```ts
/**
 * api/access.ts — клиент доступа (`/api/access/v1`).
 *
 * Пути без завершающего слэша: бэкенд регистрирует оба написания
 * (APPEND_SLASH=False), придерживаемся одного стиля, как в api/signoff.ts.
 */

import api from './client';
import { apiPath } from './endpoints';
import type {
  AccessLevel, MeResponse, PositionRole, Role, RolePermission, UserAssignment,
} from '@/types/access';

const path = (suffix: string) => apiPath('access', suffix);

/** Единственный источник порядка уровней на фронте (бэкенд — LEVEL_ORDER
 *  в apps/access/models.py). Две копии — цена того, что сравнение нужно и
 *  до сетевого запроса; расхождение ловит тест выше. */
export const LEVEL_ORDER: Record<AccessLevel, number> = {
  none: 0, read: 1, write: 2, admin: 3,
};

export const atLeastLevel = (have: AccessLevel, need: AccessLevel): boolean =>
  LEVEL_ORDER[have] >= LEVEL_ORDER[need];

export const accessApi = {
  me: async (): Promise<MeResponse> => (await api.get<MeResponse>(path('me'))).data,
  listRoles: async (): Promise<Role[]> => (await api.get<Role[]>(path('roles'))).data,
  createRole: async (body: { code: string; title: string }): Promise<Role> =>
    (await api.post<Role>(path('roles'), body)).data,
  renameRole: async (id: number, body: { title: string }): Promise<Role> =>
    (await api.patch<Role>(path(`roles/${id}`), body)).data,
  deleteRole: async (id: number): Promise<void> => { await api.delete(path(`roles/${id}`)); },
  rolePermissions: async (id: number): Promise<RolePermission[]> =>
    (await api.get<RolePermission[]>(path(`roles/${id}/permissions`))).data,
  setRolePermissions: async (id: number, items: RolePermission[]): Promise<void> => {
    await api.put(path(`roles/${id}/permissions`), items);
  },
  positionRoles: async (positionId: number): Promise<PositionRole[]> =>
    (await api.get<PositionRole[]>(path(`positions/${positionId}/roles`))).data,
  setPositionRoles: async (positionId: number, roleIds: number[]): Promise<void> => {
    await api.put(path(`positions/${positionId}/roles`), { role_ids: roleIds });
  },
  assignments: async (userId: number): Promise<UserAssignment[]> =>
    (await api.get<UserAssignment[]>(path(`assignments/${userId}`))).data,
  setAssignments: async (userId: number, items: UserAssignment[]): Promise<void> => {
    await api.put(path(`assignments/${userId}`), items);
  },
};
```

- [ ] **Шаг 5: Зарегистрировать префикс и прокси**

`src/api/endpoints.ts`, в `API_ENDPOINTS`:

```ts
  // Роли и права (Django app apps.access). Каталог ролей общий для всех
  // компаний, привязки — на компанию запроса.
  access: 'access/v1',
```

`vite.config.ts`, рядом с правилом `"^/api/signoff/"`:

```ts
    // Доступ и роли (apps.access). Легаси-путей без /v1/ нет, одной строки достаточно.
    "^/api/access/": {
      target: backendTarget,
      changeOrigin: true,
    },
```

- [ ] **Шаг 6: Фикстура ответа `/me`**

`frontend/src/test/fixtures/access.ts` — ровно тело из §4.5 спеки плюс пустой
вариант:

```ts
import type { MeResponse } from '@/types/access';

export const meFixture: MeResponse = {
  company: 'hi-tech-qazaqstan',
  permissions: {
    hr: { level: 'admin', scope: { kind: 'company', id: null } },
    tasks: { level: 'write', scope: { kind: 'department', id: 3 } },
    contracts: { level: 'read', scope: { kind: 'company', id: null } },
  },
  subordinate_companies: ['kurly-kg', 'htq-uz'],
};

/** Переходный режим подпроекта 1: контекста компании нет. Это не ошибка. */
export const meWithoutCompanyFixture: MeResponse = {
  company: null,
  permissions: {},
  subordinate_companies: [],
};
```

- [ ] **Шаг 7: Прогнать тесты и типы**

Run: `npx vitest run src/api/__tests__/access.test.ts && npx tsc --noEmit -p tsconfig.json`
Expected: PASS

- [ ] **Шаг 8: Коммит**

```bash
git add frontend/src/api frontend/src/types/access.ts frontend/src/test/fixtures frontend/vite.config.ts
git commit -m "feat(access): клиент доступа, типы контракта и фикстура /me"
```

---

## Задача 2: Хук `usePermissions` (спека B2)

**Files:**
- Create: `frontend/src/hooks/usePermissions.ts`,
  `frontend/src/hooks/__tests__/usePermissions.test.tsx`

**Interfaces:**
- Produces: `usePermissions()` → `{ level(module), atLeast(module, level),
  scope(module), subordinateCompanies, company, isLoading }`.

- [ ] **Шаг 1: Тесты на фикстуре §4.5**

```tsx
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { meFixture, meWithoutCompanyFixture } from '@/test/fixtures/access';
import { usePermissions } from '../usePermissions';

vi.mock('@/api/access', async (orig) => ({
  ...(await orig<typeof import('@/api/access')>()),
  accessApi: { me: vi.fn() },
}));

describe('usePermissions', () => {
  it('отдаёт уровень по модулю', async () => {
    // ... accessApi.me -> meFixture
    const { result } = renderHook(() => usePermissions(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.level('hr')).toBe('admin');
  });

  it('отсутствие ключа означает отсутствие доступа', async () => {
    expect(result.current.level('mail')).toBe('none');
    expect(result.current.atLeast('mail', 'read')).toBe(false);
  });

  it('пропускает равный и более высокий уровень', async () => {
    expect(result.current.atLeast('tasks', 'write')).toBe(true);
    expect(result.current.atLeast('tasks', 'admin')).toBe(false);
  });

  it('отдаёт область модуля', async () => {
    expect(result.current.scope('tasks')).toEqual({ kind: 'department', id: 3 });
  });

  it('пустой ответ без компании — не ошибка', async () => {
    // accessApi.me -> meWithoutCompanyFixture
    expect(result.current.company).toBeNull();
    expect(result.current.level('hr')).toBe('none');
  });

  it('во время загрузки не выдаёт доступ авансом', async () => {
    // до резолва запроса
    expect(result.current.atLeast('hr', 'read')).toBe(false);
  });
});
```

Последний тест — не формальность: `level()` по умолчанию должен возвращать
`none`, иначе на первом рендере страница мигнёт содержимым, которого у
пользователя нет.

- [ ] **Шаг 2: Прогнать — обязаны упасть**

Run: `npx vitest run src/hooks/__tests__/usePermissions.test.tsx`

- [ ] **Шаг 3: Реализовать хук**

`staleTime` 5 минут и `retry: false` — как у `useHRLevel`; `queryKey:
['access-me']`.

- [ ] **Шаг 4: Прогнать тесты**

Run: `npx vitest run src/hooks/__tests__/usePermissions.test.tsx`
Expected: PASS

- [ ] **Шаг 5: Коммит**

```bash
git add frontend/src/hooks
git commit -m "feat(access): хук usePermissions поверх /me"
```

---

## Задача 3: `RequireAuth` на модуль и уровень (спека B4)

**Files:**
- Modify: `frontend/src/app/routing/types.ts`,
  `frontend/src/components/RequireAuth.tsx`
- Test: `frontend/src/components/__tests__/RequireAuth.test.tsx`

**Interfaces:**
- Produces: `RouteRequirement = { module: string; level: AccessLevel }`;
  `RouteConfig.requires?: RouteRequirement` вместо `requiresRole?: RouteRole`.

- [ ] **Шаг 1: Тесты гейта**

```tsx
it('пускает при уровне не ниже требуемого', ...);
it('отвергает при уровне ниже требуемого — редирект на /myprofile', ...);
it('не пускает, пока права не загружены', ...);
it('маршрут без requires доступен любому вошедшему', ...);
it('сетевая ошибка прав не разлогинивает', ...);
```

Последний — регресс существующего поведения: `RequireAuth` сегодня отличает
«сессия недействительна» (401/403 → выход) от «бэкенд недоступен» (показать
экран с повтором). Гейт прав не должен это сломать.

- [ ] **Шаг 2: Прогнать — обязаны упасть**

Run: `npx vitest run src/components/__tests__/RequireAuth.test.tsx`

- [ ] **Шаг 3: Заменить тип требования**

`src/app/routing/types.ts`:

```ts
import type { AccessLevel } from '@/types/access';

/** Требование маршрута: модуль реестра и минимальный уровень.
 *  Пришло на смену RouteRole ('admin' | 'hr' | 'editor'), который опирался на
 *  словарь ролей, никогда не выдававшихся бэкендом (спека §6, B3). */
export interface RouteRequirement {
  module: string;
  level: AccessLevel;
}

export interface RouteConfig {
  path: string;
  component: LazyPage;
  requiresAuth?: boolean;
  /** Гейт по модулю и уровню. ``requiresAuth`` обязан быть true. */
  requires?: RouteRequirement;
}
```

- [ ] **Шаг 4: Переписать гейт в `RequireAuth`**

Блок `ROLE_BUCKETS` и импорт `hasAnyRole/HR_ROLES/EDITOR_ROLES` удаляются;
проверка становится `permissions.atLeast(requires.module, requires.level)`.
Комментарий о том, что это UX-guard, а рубеж на бэкенде, **сохранить** — он
по-прежнему верен и объясняет, почему окно устаревшего кеша не течёт.

Совместимость со старой формой не поддерживается: все потребители
перекладываются задачей 4 в этой же ветке.

- [ ] **Шаг 5: Прогнать тесты**

Run: `npx vitest run src/components/__tests__/RequireAuth.test.tsx`
Expected: PASS. `npx tsc --noEmit` ожидаемо падает на `routeDefinitions.ts` —
это чинит следующая задача.

- [ ] **Шаг 6: Коммит**

```bash
git add frontend/src/components/RequireAuth.tsx frontend/src/app/routing/types.ts frontend/src/components/__tests__
git commit -m "refactor(auth): RequireAuth гейтит по модулю и уровню"
```

---

## Задача 4: Перекладка 47 маршрутов и тест-сторож (спека B5, B3)

**Files:**
- Modify: `frontend/src/app/routing/routeDefinitions.ts`
- Create: `frontend/src/app/routing/routeAccess.test.ts`

**Правило перекладки:**

| Было | Стало |
|---|---|
| `requiresRole: 'hr'` | `requires: { module: 'hr', level: 'read' }` |
| `requiresRole: 'editor'` | `requires: { module: 'cms', level: 'write' }` |
| `requiresRole: 'admin'` | `requires: { module: <по принадлежности пути>, level: 'admin' }` |

`'admin'` разворачивается по смыслу пути, а не одним значением:
`/tasks/*` → `tasks:admin`, `/signoff/*` → `signoff:admin`,
`/requests/*` → `approvals:admin`, `/admin/users` → `users:admin`.

⚠️ Исключения, которые нельзя переложить механически, — их в таблице два, и оба
уже описаны комментариями в самом файле:
`/manage/projects` помечен `'hr'`, хотя управляет проектами домена задач →
`{ module: 'tasks', level: 'write' }`;
`/manage/home`, `/manage/news`, `/manage/contacts` — единственные настоящие
`editor` → `cms:write`.

- [ ] **Шаг 1: Написать тест-сторож (до правки таблицы)**

`frontend/src/app/routing/routeAccess.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { protectedRoutes } from './routeDefinitions';
import { LEVEL_ORDER } from '@/api/access';

/**
 * Сторож из спеки §6 (B3). Именно ОТСУТСТВИЕ такой проверки позволило
 * словарю ролей годами выглядеть работающим: маршруты сравнивались со
 * строками, которых бэкенд не выдаёт никогда.
 */
const KNOWN_MODULES = new Set([
  'users', 'hr', 'tasks', 'approvals', 'cms', 'media', 'mail', 'messenger',
  'conference', 'contracts', 'signoff', 'companies', 'access',
]);

describe('гейты маршрутов', () => {
  it('каждый гейт ссылается на существующий модуль', () => {
    const bad = protectedRoutes
      .filter((r) => r.requires && !KNOWN_MODULES.has(r.requires.module))
      .map((r) => `${r.path} -> ${r.requires!.module}`);
    expect(bad).toEqual([]);
  });

  it('каждый гейт ссылается на существующий уровень', () => {
    const bad = protectedRoutes
      .filter((r) => r.requires && !(r.requires.level in LEVEL_ORDER))
      .map((r) => r.path);
    expect(bad).toEqual([]);
  });

  it('гейт не ставится на маршрут без requiresAuth', () => {
    const bad = protectedRoutes.filter((r) => r.requires && !r.requiresAuth);
    expect(bad).toEqual([]);
  });

  it('число гейтов не уменьшилось при перекладке', () => {
    // 47 = 27 hr + 16 admin + 3 editor на момент перекладки.
    expect(protectedRoutes.filter((r) => r.requires).length).toBe(47);
  });

  it('нигде не осталось старого requiresRole', () => {
    const legacy = protectedRoutes.filter((r) => 'requiresRole' in r);
    expect(legacy).toEqual([]);
  });
});
```

- [ ] **Шаг 2: Прогнать — обязан упасть**

Run: `npx vitest run src/app/routing/routeAccess.test.ts`
Expected: FAIL — `requiresRole` ещё на месте, `requires` нет.

- [ ] **Шаг 3: Переложить таблицу**

Все 47 записей. Комментарии, объясняющие выбор бакета, переписать под новую
пару — они объясняют решение, а не синтаксис, и потому остаются полезны.

- [ ] **Шаг 4: Прогнать сторож, существующий тест таблицы и типы**

Run: `npx vitest run src/app/routing && npx tsc --noEmit -p tsconfig.json`
Expected: PASS. `routeDefinitions.test.ts` (дубли путей) обязан остаться зелёным.

- [ ] **Шаг 5: Коммит**

```bash
git add frontend/src/app/routing
git commit -m "refactor(auth): 47 маршрутов переложены на модуль и уровень"
```

---

## Задача 5: Удаление мёртвого словаря (спека B3)

**Files:**
- Modify: `frontend/src/lib/auth/roles.ts`
- Create: `frontend/src/lib/auth/__tests__/roles.test.ts`

Удаляются `ELEVATED_ROLES`, `HR_ROLES`, `EDITOR_ROLES`, `EMPLOYEE_ROLES` и
построенные на них `hasElevatedAccess`, `isHrManager`, `isEditor`,
`hasEmployeeRole`, `hasEmployeeTaskAccess`, `hasEmployeeTaskAccessFromParts`,
`usesEmployeeTaskExperience`, `hasAnyRole`.

⚠️ Порядок обязателен: сначала переложить всех потребителей (задачи 3–4 и
компоненты, найденные шагом 1), и только потом удалять. Обратный порядок даёт
сборку, которая не компилируется, и соблазн «временно вернуть».

- [ ] **Шаг 1: Найти всех потребителей**

Run: `grep -rn "hasElevatedAccess\|isHrManager\|isEditor\|hasEmployeeTaskAccess\|usesEmployeeTaskExperience\|hasAnyRole\|ELEVATED_ROLES\|HR_ROLES\|EDITOR_ROLES\|EMPLOYEE_ROLES" src | grep -v "lib/auth/roles.ts"`

Каждое найденное место переводится на `usePermissions`:
`hasElevatedAccess` → `atLeast(<модуль страницы>, 'write')`,
`isHrManager` → `atLeast('hr', 'read')`,
`isEditor` → `atLeast('cms', 'write')`.

`hasEmployeeTaskAccess` (роль ИЛИ наличие отдела и должности) переводится на
`atLeast('tasks', 'read')`: «есть отдел и должность» и была самодельной
проверкой того, что теперь отвечает бэкенд.

- [ ] **Шаг 2: Тест-сторож на отсутствие строковых ролей**

```ts
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/** Бэкенд выдаёт ровно три значения (profile_service.roles_for): admin, staff,
 *  user. Сравнение с любой другой строкой роли недостижимо по определению. */
const PHANTOM_ROLES = [
  'hr_manager', 'senior_hr', 'junior_hr', 'senior_manager', 'junior_manager',
  'editors', 'employee', 'superuser',
];

const walk = (dir: string): string[] => fs.readdirSync(dir, { withFileTypes: true })
  .flatMap((e) => (e.isDirectory() ? walk(path.join(dir, e.name))
    : [path.join(dir, e.name)]))
  .filter((f) => /\.(ts|tsx)$/.test(f) && !f.includes('__tests__'));

describe('словарь ролей', () => {
  it('ни один файл не сравнивается с ролью, которой бэкенд не выдаёт', () => {
    const offenders: string[] = [];
    for (const file of walk('src')) {
      const text = fs.readFileSync(file, 'utf-8');
      for (const role of PHANTOM_ROLES) {
        if (text.includes(`'${role}'`) || text.includes(`"${role}"`)) {
          offenders.push(`${file}: ${role}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
```

- [ ] **Шаг 3: Прогнать — обязан упасть**

Run: `npx vitest run src/lib/auth/__tests__/roles.test.ts`

- [ ] **Шаг 4: Переложить потребителей и удалить словарь**

- [ ] **Шаг 5: Прогнать весь набор и типы**

Run: `npm test && npx tsc --noEmit -p tsconfig.json && npm run lint`
Expected: PASS

- [ ] **Шаг 6: Коммит**

```bash
git add frontend/src
git commit -m "refactor(auth): удалён словарь ролей, недостижимый по построению"
```

---

## Задача 6: Навигация по уровню (спека B6)

**Files:**
- Modify: файлы меню/сайдбара (найти шагом 1)

- [ ] **Шаг 1: Найти пункты меню**

Run: `grep -rln "requiresRole\|isHrManager\|hasElevatedAccess" src/components src/layouts 2>/dev/null`

- [ ] **Шаг 2: Тест**

Пункт скрыт при `none` и виден при `read` — по одному тесту на каждую группу
меню, не на каждый пункт.

- [ ] **Шаг 3: Переложить на `usePermissions`**

Комментарий обязателен: скрытие — удобство, не защита; рубеж на бэкенде.

- [ ] **Шаг 4: Прогнать тесты**

Run: `npm test`

- [ ] **Шаг 5: Коммит**

```bash
git commit -am "feat(access): пункты меню скрываются по уровню доступа"
```

---

## Задача 7: Каталог ролей (спека B7, экран 1)

**Files:**
- Create: `frontend/src/pages/access/RoleCatalog.tsx`,
  `frontend/src/components/access/RolePermissionMatrix.tsx`,
  `frontend/src/pages/access/__tests__/RoleCatalog.test.tsx`
- Modify: `frontend/src/app/routing/lazyPages.ts`, `routeDefinitions.ts`

**Экран плоский, без диаграммы** — роль иерархии не имеет (спека §1.1).

Маршрут: `/access/roles`, гейт `{ module: 'access', level: 'admin' }`.

- [ ] **Шаг 1: Тесты**

```tsx
it('показывает подпись о том, что правка действует во всех компаниях', ...);
it('не показывает кнопок правки не платформенному администратору', ...);
it('409 in_use показывается читаемо, с числом должностей и пользователей', ...);
it('матрица прав отправляется одним PUT со всем набором', ...);
it('снятый модуль исчезает из набора, а не остаётся с none', ...);
```

Первый тест не косметический: каталог общий, и без подписи администратор
компании считает, что правит свою роль.

- [ ] **Шаг 2: Прогнать — обязаны упасть**

- [ ] **Шаг 3: Реализовать страницу и матрицу**

Матрица: строки — модули из `KNOWN_MODULES`, столбцы — четыре уровня,
радиокнопка в строке. Сохранение — один `PUT` с полным набором; модули на
`none` в тело не попадают.

- [ ] **Шаг 4: Прогнать тесты и типы**

Run: `npx vitest run src/pages/access && npx tsc --noEmit -p tsconfig.json`

- [ ] **Шаг 5: Коммит**

```bash
git add frontend/src/pages/access frontend/src/components/access frontend/src/app/routing
git commit -m "feat(access): каталог ролей и матрица прав"
```

---

## Задача 8: Роли должности и личные назначения (спека B7, экран 2)

**Files:**
- Create: `frontend/src/components/access/PositionRolesPanel.tsx`,
  `frontend/src/components/access/__tests__/PositionRolesPanel.test.tsx`
- Modify: карточка должности (найти: `grep -rln "Position" src/pages/hr src/components/hr`)

- [ ] **Шаг 1: Тесты**

```tsx
it('набор ролей отправляется одним PUT, а не серией добавлений', ...);
it('личные назначения показаны отдельным блоком с пометкой «исключение»', ...);
it('область «компания» не даёт выбрать отдел', ...);
it('область «отдел» требует выбора отдела до сохранения', ...);
```

Второй тест — требование спеки §1.2: личное назначение обязано выглядеть
исключением, иначе становится вторым равноправным способом раздать права.

- [ ] **Шаг 2: Прогнать — обязаны упасть**

- [ ] **Шаг 3: Реализовать панель**

Штатный блок — мультиселект ролей должности. Второй блок, визуально
подчинённый, — личные назначения с выбором области.

- [ ] **Шаг 4: Прогнать тесты**

- [ ] **Шаг 5: Коммит**

```bash
git add frontend/src/components/access frontend/src/pages
git commit -m "feat(access): панель ролей должности и личных назначений"
```

---

## Задача 9: Переключатель иерархии (спека B7, экран 3)

**Files:**
- Create: `frontend/src/components/hr/OrgChart/HierarchySwitch.tsx`,
  `frontend/src/components/hr/OrgChart/__tests__/HierarchySwitch.test.tsx`
- Modify: `frontend/src/components/hr/OrgChart/index.tsx`

Диаграмма уже умеет всё нужное: `ConnectDialog` (перетаскивание связей),
`OrgEditPanel`, `TransferSubordinatesDialog`, `useOrgLayout`,
`useOrgEditMutations`. Добавляется только выбор источника данных.

- [ ] **Шаг 1: Тесты**

```tsx
it('по умолчанию показывает внутреннюю иерархию компании', ...);
it('внешняя иерархия не даёт перетаскивать узлы', ...);
it('внешняя иерархия пуста, если руководящих должностей нет, и это подписано', ...);
it('подпись «связь — подчинение, а не передача прав» видна в обоих режимах', ...);
```

Третий тест закрывает конкретную ловушку: до переработки HR внешняя иерархия
всегда пуста, и пустой экран без подписи читается как сбой загрузки.

Четвёртый — требование спеки §6 дизайна: это самое вероятное расхождение
ожиданий, и закрывается оно в интерфейсе, а не в документации.

- [ ] **Шаг 2: Прогнать — обязаны упасть**

- [ ] **Шаг 3: Реализовать**

Переключатель «внутренняя / внешняя». Внешняя — только для чтения:
редактировать нечего, она вычисляется из дерева компаний (спека §1.4).
Источник данных внешней — `subordinate_companies` из `/me`.

- [ ] **Шаг 4: Прогнать весь набор**

Run: `npm test && npx tsc --noEmit -p tsconfig.json && npm run lint`

- [ ] **Шаг 5: Коммит**

```bash
git add frontend/src/components/hr/OrgChart
git commit -m "feat(access): переключатель внутренней и внешней иерархии"
```

---

## Определение готовности

- [ ] `npm test` зелёный
- [ ] `npx tsc --noEmit -p tsconfig.json` без ошибок
- [ ] `npm run lint` без ошибок
- [ ] `npm run build` проходит, бюджет размера бандла не превышен
- [ ] Сторож из задачи 5 зелёный: ни одной фантомной строки роли в `src/`
- [ ] Ни один файл вне `frontend/**` не изменён:
      `git diff --name-only structure-refactoring | grep -v '^frontend/' | wc -l` → `0`
- [ ] Ветка перебазирована на `structure-refactoring` перед слиянием
