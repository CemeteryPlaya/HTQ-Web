import { describe, expect, it } from 'vitest';

import { hasAnyRole, isPlatformAdmin, PLATFORM_ROLES } from './roles';

/**
 * От прежнего файла остался только платформенный признак: прикладные права
 * спрашивают у `usePermissions` (см. `hooks/usePermissions.test.tsx`), а не у
 * строк ролей. Проверки на `hasEmployeeTaskAccess` и соседей уехали туда же
 * вместе с поведением — здесь их дублировать нечем и незачем.
 */
describe('PLATFORM_ROLES', () => {
  it('перечисляет ровно то, что выдаёт бэкенд', () => {
    // roles_for() возвращает admin (superuser), staff или user — и ничего
    // больше. Сторож на случай, если список снова начнёт разрастаться.
    expect([...PLATFORM_ROLES]).toEqual(['admin', 'staff', 'user']);
  });
});

describe('hasAnyRole', () => {
  it('находит роль из ожидаемых', () => {
    expect(hasAnyRole(['staff'], ['admin', 'staff'])).toBe(true);
  });

  it('не находит отсутствующую', () => {
    expect(hasAnyRole(['user'], ['admin', 'staff'])).toBe(false);
  });

  it('на пустом и неопределённом списке ролей отвечает false', () => {
    expect(hasAnyRole([], ['admin'])).toBe(false);
    expect(hasAnyRole(undefined, ['admin'])).toBe(false);
  });
});

describe('isPlatformAdmin', () => {
  it('признаёт только admin', () => {
    expect(isPlatformAdmin(['admin'])).toBe(true);
    expect(isPlatformAdmin(['staff'])).toBe(false);
    expect(isPlatformAdmin(['user'])).toBe(false);
  });
});
