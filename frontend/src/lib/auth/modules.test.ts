/**
 * Сторож на реестр модулей.
 *
 * Список модулей во фронте — копия `KNOWN_SERVICES` бэкенда, и копии
 * расходятся. Опаснее всего расхождение в гейтах маршрутов: `requires:
 * { module: 'hrr' }` не сломает сборку, не выдаст ошибки в консоли и просто
 * закроет страницу навсегда — уровень по несуществующему модулю всегда `none`.
 * Именно так выглядела бы опечатка, и именно её здесь и ловим.
 */
import { describe, expect, it } from 'vitest';

import { protectedRoutes } from '@/app/routing/routeDefinitions';
import { LEVEL_ORDER } from '@/lib/auth/permissions';

import { ACCESS_MODULES, MODULE_NAMES, isKnownModule } from './modules';

describe('реестр модулей', () => {
  it('не содержит дублей', () => {
    expect(MODULE_NAMES.length).toBe(new Set(MODULE_NAMES).size);
  });

  it('каждый гейт маршрута ссылается на существующий модуль', () => {
    const unknown = protectedRoutes
      .filter((route) => route.requires && !isKnownModule(route.requires.module))
      .map((route) => `${route.path} → ${route.requires?.module}`);

    expect(unknown).toEqual([]);
  });

  it('каждый гейт маршрута ссылается на существующий уровень', () => {
    const levels = new Set<string>(LEVEL_ORDER);
    const unknown = protectedRoutes
      .filter((route) => route.requires && !levels.has(route.requires.level))
      .map((route) => `${route.path} → ${route.requires?.level}`);

    expect(unknown).toEqual([]);
  });

  it('гейт не ставится на маршрут без requiresAuth', () => {
    // Гейт молча не работает без аутентификации: RequireAuth монтируется
    // только для защищённых путей, поэтому такая пара — незакрытая страница,
    // выглядящая закрытой.
    const dangling = protectedRoutes
      .filter((route) => route.requires && !route.requiresAuth)
      .map((route) => route.path);

    expect(dangling).toEqual([]);
  });

  it('у каждого модуля есть подпись для матрицы прав', () => {
    const nameless = ACCESS_MODULES.filter((module) => !module.fallback.trim());
    expect(nameless).toEqual([]);
  });
});
