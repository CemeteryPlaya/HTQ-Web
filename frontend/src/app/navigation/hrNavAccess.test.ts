/**
 * Задача 10 блока I: кадровая навигация читает права из `usePermissions`,
 * а не из снятого кадрового уровня. Здесь закреплено, что для четырёх
 * засеянных ролей (`backend/apps/access/migrations/0005_seed_hr_level_roles`
 * + `0008_hr_role_subnode_denies`) новые предикаты дают ТОТ ЖЕ набор
 * пунктов, что старая таблица «маршрут → уровни» в `HRLayout`/
 * `ProfileSidebar`, — с одним намеренным отличием: `/hr/accounts` (см.
 * `LEGACY_LEVELS` ниже и комментарий в `hrNavAccess.ts`).
 *
 * Карты глубины ниже — литералы из миграций, а не пересказ: если сид
 * поменяется, тест обязан покраснеть, а не подстроиться.
 */
import { describe, expect, it } from 'vitest';

import type { Permissions } from '@/hooks/usePermissions';
import {
  depthFor,
  hasDepth,
  levelFor,
  meetsLevel,
  scopeFor,
  type DepthFlag,
  type DepthMap,
  type PermissionMap,
} from '@/lib/auth/permissions';

import { HR_NAV_VISIBLE, hrNavVisible } from './hrNavAccess';

/** Тот же расчёт, что в `usePermissions`, — над теми же чистыми функциями. */
function permissionsOf(permissions: PermissionMap, depth: DepthMap): Permissions {
  return {
    company: 'hi-tech-qazaqstan',
    level: (module) => levelFor(permissions, module),
    atLeast: (module, required) => meetsLevel(levelFor(permissions, module), required),
    scope: (module) => scopeFor(permissions, module),
    depth: (node) => depthFor(depth, node),
    can: (node, flag) => hasDepth(depth, node, flag),
    pageHidden: () => false,
    subordinateCompanies: [],
    inheritedFrom: [],
    isLoading: false,
    isError: false,
    refetch: () => {},
  };
}

const VIEW: DepthFlag[] = ['view'];
const EDIT: DepthFlag[] = ['view', 'edit'];
const FULL: DepthFlag[] = ['view', 'create', 'edit'];
const ADMIN: DepthFlag[] = ['view', 'create', 'edit', 'delete'];
const DENY: DepthFlag[] = [];

// 0005 (строки роли) + 0008 (явные запреты на под-узлах). Уровень модуля —
// `legacy_level` по поддереву (delete → admin, create|edit → write,
// view → read); область — по выдаче: junior/middle — отдел, senior/lead —
// компания (рекомендация задачи 2, `legacy_roles.py`, решение 1).
const ROLES: Record<string, Permissions> = {
  junior: permissionsOf(
    { hr: { level: 'read', scope: { kind: 'department', id: 7 } } },
    {
      'hr.departments': VIEW, 'hr.documents': VIEW, 'hr.employees': VIEW,
      'hr.positions': VIEW, 'hr.production_calendar': VIEW,
      'hr.employees.salary': DENY, 'hr.employees.passport': DENY,
      'hr.employees.family': DENY, 'hr.employees.identity': DENY,
      'hr.employees.transfer': DENY,
    },
  ),
  middle: permissionsOf(
    { hr: { level: 'write', scope: { kind: 'department', id: 7 } } },
    {
      'hr.departments': EDIT, 'hr.documents': FULL, 'hr.employees': EDIT,
      'hr.employees.family': EDIT, 'hr.positions': EDIT,
      'hr.production_calendar': VIEW,
      'hr.employees.salary': DENY, 'hr.employees.passport': DENY,
      'hr.employees.identity': DENY, 'hr.employees.transfer': DENY,
    },
  ),
  senior: permissionsOf(
    { hr: { level: 'admin', scope: { kind: 'company', id: null } } },
    {
      'hr.accounts': VIEW, 'hr.departments': EDIT, 'hr.documents': FULL,
      'hr.employees': FULL, 'hr.employees.family': EDIT,
      'hr.employees.passport': EDIT, 'hr.employees.salary': EDIT,
      'hr.identity_requests': VIEW, 'hr.org': ADMIN, 'hr.positions': EDIT,
      'hr.production_calendar': ADMIN, 'hr.reports': VIEW, 'hr.staffing': ADMIN,
      'hr.employees.identity': DENY, 'hr.employees.transfer': EDIT,
    },
  ),
  lead: permissionsOf(
    { hr: { level: 'admin', scope: { kind: 'company', id: null } } },
    {
      'hr.accounts': FULL, 'hr.departments': EDIT, 'hr.documents': FULL,
      'hr.employees': ADMIN, 'hr.employees.family': EDIT,
      'hr.employees.passport': EDIT, 'hr.employees.salary': EDIT,
      'hr.identity_requests': EDIT, 'hr.org': ADMIN, 'hr.positions': EDIT,
      'hr.production_calendar': ADMIN, 'hr.reports': VIEW, 'hr.staffing': ADMIN,
      'hr.employees.identity': DENY, 'hr.employees.transfer': EDIT,
    },
  ),
};

/** Суперпользователь: `/me` отдаёт admin/company на КАЖДЫЙ модуль и все
 *  признаки (`resolve.permissions_for`/`depth_map`, ветка is_superuser). */
const SUPERUSER = permissionsOf(
  {
    hr: { level: 'admin', scope: { kind: 'company', id: null } },
    users: { level: 'admin', scope: { kind: 'company', id: null } },
  },
  { hr: ADMIN, users: ADMIN },
);

/** Платформенный админ учёток без единой кадровой роли. */
const USERS_ADMIN_ONLY = permissionsOf(
  { users: { level: 'admin', scope: { kind: 'company', id: null } } },
  { users: ADMIN },
);

const NOBODY = permissionsOf({}, {});

/** Старая таблица `HRLayout.navItems[].levels` — кто видел пункт ДО задачи 10. */
const LEGACY_LEVELS: Record<string, string[]> = {
  '/hr/employees': ['junior', 'middle', 'senior', 'lead'],
  // Было `['lead']` (а с задачи 8 — фактически и senior). Старая таблица
  // была НЕВЕРНА: экран `/hr/accounts` зовёт `users/v1/admin/users/` под
  // `users:admin` + `admin=True`, а ни одна из четырёх кадровых ролей не
  // несёт узлов `users.*` — пункт вёл кадровика на 403. Ожидание здесь —
  // никому из четырёх; кому виден — см. отдельный кейс `users:admin` ниже.
  '/hr/accounts': [],
  '/hr/identity-requests': ['senior', 'lead'],
  '/hr/recruitment': ['middle', 'senior', 'lead'],
  '/hr/archive': ['senior', 'lead'],
  '/hr/departments': ['middle', 'senior', 'lead'],
  '/hr/positions': ['middle', 'senior', 'lead'],
  '/hr/org-chart': ['junior', 'middle', 'senior', 'lead'],
  '/hr/pmo': ['senior', 'lead'],
  '/hr/time-tracking': ['middle', 'senior', 'lead'],
  '/hr/production-calendar': ['junior', 'middle', 'senior', 'lead'],
  '/hr/staffing': ['senior', 'lead'],
  '/hr/documents': ['junior', 'middle', 'senior', 'lead'],
  '/hr/share-links': ['senior', 'lead'],
  '/hr/history': ['senior', 'lead'],
};

describe('hrNavAccess — соответствие старой таблице уровней', () => {
  it('покрывает ровно те маршруты, что и старая таблица', () => {
    expect(Object.keys(HR_NAV_VISIBLE).sort()).toEqual(Object.keys(LEGACY_LEVELS).sort());
  });

  for (const [route, levels] of Object.entries(LEGACY_LEVELS)) {
    const who = levels.length > 0 ? levels.join('/') : 'никому из четырёх кадровых ролей';
    it(`${route}: виден ${who} и никому другому`, () => {
      for (const [role, perm] of Object.entries(ROLES)) {
        expect(hrNavVisible(perm, route), `${role} на ${route}`).toBe(levels.includes(role));
      }
    });
  }

  it('суперпользователь видит всё, человек без модуля hr — ничего', () => {
    for (const route of Object.keys(HR_NAV_VISIBLE)) {
      expect(hrNavVisible(SUPERUSER, route), route).toBe(true);
      expect(hrNavVisible(NOBODY, route), route).toBe(false);
    }
  });

  it('/hr/accounts открыт администратору учёток (users:admin), а не кадровым ролям', () => {
    // Фикс-раунд 1 задачи 10: предикат — гейт самого экрана
    // (`users/v1/admin/users/` → `users:admin`), поэтому платформенный
    // админ без кадровых ролей пункт видит, а hr-lead без `users` — нет.
    expect(hrNavVisible(USERS_ADMIN_ONLY, '/hr/accounts')).toBe(true);
    expect(hrNavVisible(ROLES.lead, '/hr/accounts')).toBe(false);
    // …и при этом ни один кадровый пункт ему не открылся заодно.
    for (const route of Object.keys(HR_NAV_VISIBLE).filter((r) => r !== '/hr/accounts')) {
      expect(hrNavVisible(USERS_ADMIN_ONLY, route), route).toBe(false);
    }
  });

  it('маршрут без правила — ошибка, а не тихое «скрыть»', () => {
    expect(() => hrNavVisible(SUPERUSER, '/hr/nonexistent')).toThrow(/не задано правило/);
  });
});
