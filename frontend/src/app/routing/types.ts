import type { ComponentType, LazyExoticComponent } from 'react';

import type { AccessLevel, DepthFlag } from '@/lib/auth/permissions';

export type LazyPage = LazyExoticComponent<ComponentType>;

/**
 * Гейт маршрута: модуль и минимальный уровень (§3, §6 B4 спеки стадии 2).
 *
 * Пришло на смену `RouteRole`. Прежние три ведра ролей опирались на словарь,
 * который бэкенд не выдавал никогда, — то есть гейт по факту сводился к
 * `admin`/`staff`/`user`.
 */
export interface RouteRequirement {
  module: string;
  level: AccessLevel;
  /** Или признак на узле — пускает и без уровня модуля. Доски задач
   * (`/manage/projects`) открыты держателям «Доски задач проекта»
   * (`project.board`), у которых нет кадровых прав (решение 01.10). */
  orNode?: { node: string; flag: DepthFlag };
}

/** Пускает ли гейт маршрута: уровень модуля или признак на узле. */
export function meetsRequirement(
  permissions: { atLeast: (module: string, level: AccessLevel) => boolean;
    can: (node: string, flag: DepthFlag) => boolean },
  requires: RouteRequirement,
): boolean {
  if (permissions.atLeast(requires.module, requires.level)) return true;
  return Boolean(requires.orNode && permissions.can(requires.orNode.node, requires.orNode.flag));
}

export interface RouteConfig {
  path: string;
  component: LazyPage;
  requiresAuth?: boolean;
  /** Гейт по модулю и уровню. ``requiresAuth`` ОБЯЗАН быть true, иначе он не
   * сработает — RouteElement монтирует охрану только для защищённых путей. */
  requires?: RouteRequirement;
}
