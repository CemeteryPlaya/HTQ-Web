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
export const EMPLOYEE_ROLES = ['employee', 'user'] as const;

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
