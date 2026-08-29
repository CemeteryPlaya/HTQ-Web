/**
 * Типы домена доступа (`/api/access/v1`).
 *
 * Соответствуют замороженному контракту §4 спецификации стадии 2
 * (`docs/plans/2026-08-29-stage2-access-and-roles-spec.md`). Контракт — стык
 * между двумя исполнителями, поэтому расхождение здесь чинится правкой
 * документа и согласованием, а не подгонкой типов под то, что пришло.
 */

import type { AccessLevel, PermissionMap, ScopeKind } from '@/lib/auth/permissions';

/** §4.1. Каталог ролей глобален: одна роль действует во всех компаниях. */
export interface Role {
  id: number;
  code: string;
  title: string;
  /** Служебная роль — удалять нельзя (409). */
  is_system: boolean;
}

export interface RoleInput {
  code: string;
  title: string;
}

/** §4.2. Права роли — плоский набор пар «модуль → уровень». */
export interface RolePermission {
  module: string;
  level: AccessLevel;
}

/** §4.3. Роль в наборе должности — штатный путь выдачи прав. */
export interface PositionRole {
  role_id: number;
  code: string;
  title: string;
}

/** §4.4. Личное назначение — исключительный путь. */
export interface RoleAssignment {
  role_id: number;
  scope_kind: ScopeKind;
  /** `null` обязателен при `scope_kind: 'company'`. */
  scope_id: number | null;
}

/** §4.5. Права текущего пользователя в компании запроса. */
export interface AccessMe {
  /** `null` вне контекста компании — переходный режим подпроекта 1, не ошибка. */
  company: string | null;
  permissions: PermissionMap;
  /**
   * Компании ниже по дереву владения, над сотрудниками которых пользователь
   * начальник по внешней иерархии (§1.4). Стадия его отдаёт, но выборки по
   * нему не режет — только отображение (§7).
   */
  subordinate_companies: string[];
}
