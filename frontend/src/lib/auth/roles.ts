/**
 * Роли платформенной учётки.
 *
 * Бэкенд выдаёт ровно три значения — `admin` (superuser), `staff`, `user`
 * (`apps/users/services/profile_service.py::roles_for`). Всё остальное, что
 * здесь когда-то перечислялось (`hr_manager`, `senior_hr`, `junior_hr`,
 * `senior_manager`, `junior_manager`, `editors`, `employee`), не приезжало
 * никогда: ветки на этих строках были недостижимы, а код с ними выглядел
 * работающей ролевой моделью.
 *
 * Прикладные права теперь спрашивают у `usePermissions` — уровень модуля
 * (§3 спеки стадии 2), а не строку роли. Здесь остался только платформенный
 * признак, у которого нет модульного эквивалента: `admin` — оператор
 * платформы. Сторож `deadRoles.test.ts` не даёт словарю вернуться.
 */

/** Роли, которые бэкенд действительно выдаёт. */
export const PLATFORM_ROLES = ['admin', 'staff', 'user'] as const;

export type PlatformRole = (typeof PLATFORM_ROLES)[number];

export const hasAnyRole = (
  roles: string[] | undefined,
  expectedRoles: readonly string[],
): boolean => {
  if (!roles?.length) {
    return false;
  }

  return roles.some((role) => expectedRoles.includes(role));
};

/** Оператор платформы. Модульного эквивалента нет и быть не должно. */
export const isPlatformAdmin = (roles: string[] | undefined): boolean =>
  hasAnyRole(roles, ['admin']);
