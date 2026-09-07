import type { UserProfile } from '@/types/userProfile';

export const ELEVATED_ROLES = [
  'staff',
  'admin',
  'superuser',
  'hr_manager',
  'senior_hr',
  'junior_hr',
  'senior_manager',
  'junior_manager',
] as const;

export const HR_ROLES = [
  'hr_manager',
  'senior_hr',
  'junior_hr',
  'senior_manager',
  'junior_manager',
  'staff',
] as const;

export const EDITOR_ROLES = ['editors', 'staff'] as const;

/**
 * «Администратор» в том смысле, в каком его понимает бэкенд.
 *
 * `htqweb.http.api_view(admin=True)` пускает `is_staff ИЛИ is_superuser`, и
 * этот набор — его зеркало (тот же, что в `components/RequireAuth.tsx`).
 * Раньше он был скопирован в десяти файлах: разъедься копии — часть экранов
 * начнёт предлагать действия, которые сервер не выполнит.
 */
export const ADMIN_ROLES = ['admin', 'superuser', 'staff'] as const;

/** Может ли пользователь делать то, что закрыто `admin=True`. */
export const isPlatformAdmin = (
  profile: UserProfile | null | undefined,
): boolean => hasAnyRole(profile?.roles, ADMIN_ROLES);
export const EMPLOYEE_ROLES = ['employee', 'user'] as const;

/**
 * Кто проходит ролевой гейт маршрута — ОДИН источник на охрану маршрута и на
 * решение «рисовать ли ссылку туда».
 *
 * Жил в `components/RequireAuth.tsx`, куда и смотрит роутер. Пока копия была
 * одна, это было незаметно; вторая (бейдж проекта в договорной карточке)
 * скопировала только `HR_ROLES` — и администратор, которого маршрут пускает,
 * ссылки не видел. Ровно та беда, о которой предупреждает `ADMIN_ROLES`
 * выше, только зеркальная: копия оказалась СТРОЖЕ оригинала.
 *
 * `admin`/`superuser`/`staff` проходят везде: платформенный администратор не
 * должен упираться в предметную роль.
 */
export const ALWAYS_ALLOWED_ROLES = ['admin', 'superuser', 'staff'] as const;

export const ROLE_BUCKETS: Record<'admin' | 'hr' | 'editor', readonly string[]> = {
  admin: ALWAYS_ALLOWED_ROLES,
  hr: [...ALWAYS_ALLOWED_ROLES,
       ...HR_ROLES.filter((r) => !ALWAYS_ALLOWED_ROLES.includes(r as never))],
  editor: [...ALWAYS_ALLOWED_ROLES,
           ...EDITOR_ROLES.filter((r) => !ALWAYS_ALLOWED_ROLES.includes(r as never))],
};

/** Пустит ли ролевой гейт маршрута этого пользователя. */
export const canAccessRouteRole = (
  roles: string[] | undefined,
  routeRole: keyof typeof ROLE_BUCKETS,
): boolean => hasAnyRole(roles, ROLE_BUCKETS[routeRole]);

export const hasAnyRole = (
  roles: string[] | undefined,
  expectedRoles: readonly string[],
): boolean => {
  if (!roles?.length) {
    return false;
  }

  return roles.some((role) => expectedRoles.includes(role));
};

export const hasElevatedAccess = (profile: UserProfile | null | undefined): boolean =>
  hasAnyRole(profile?.roles, ELEVATED_ROLES);

export const isHrManager = (profile: UserProfile | null | undefined): boolean =>
  hasAnyRole(profile?.roles, HR_ROLES);

export const isEditor = (profile: UserProfile | null | undefined): boolean =>
  hasAnyRole(profile?.roles, EDITOR_ROLES);

export const hasEmployeeRole = (roles: string[] | undefined): boolean =>
  hasAnyRole(roles, EMPLOYEE_ROLES);

export const hasEmployeeTaskAccess = (profile: UserProfile | null | undefined): boolean =>
  Boolean(
    profile
    && (
      hasElevatedAccess(profile)
      || hasEmployeeRole(profile.roles)
      || (profile.department && profile.position)
    ),
  );

export const hasEmployeeTaskAccessFromParts = (
  roles?: string[],
  department?: string,
  position?: string,
): boolean =>
  hasAnyRole(roles, ELEVATED_ROLES)
  || hasEmployeeRole(roles)
  || Boolean(department && position);

export const usesEmployeeTaskExperience = (
  profile: UserProfile | null | undefined,
): profile is UserProfile =>
  Boolean(profile && hasEmployeeTaskAccess(profile) && !hasElevatedAccess(profile));
