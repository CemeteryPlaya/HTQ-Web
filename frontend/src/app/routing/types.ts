import type { ComponentType, LazyExoticComponent } from 'react';

import type { AccessLevel } from '@/lib/auth/permissions';

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
}

export interface RouteConfig {
  path: string;
  component: LazyPage;
  requiresAuth?: boolean;
  /** Гейт по модулю и уровню. ``requiresAuth`` ОБЯЗАН быть true, иначе он не
   * сработает — RouteElement монтирует охрану только для защищённых путей. */
  requires?: RouteRequirement;
}
