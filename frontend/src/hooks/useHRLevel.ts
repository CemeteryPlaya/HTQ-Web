import { useQuery } from '@tanstack/react-query';
import api from '@/api/client';

export type HRLevel = 'junior' | 'middle' | 'senior' | 'lead' | null;

interface HRLevelResponse {
  level: HRLevel;
  scope_department_id: number | null;
  can_read_all: boolean;
  can_write_basic: boolean;
  can_create_employee: boolean;
  can_transfer_employee: boolean;
  can_delete_employee: boolean;
  can_list_user_options: boolean;
  can_manage_user_options: boolean;
  permissions?: string[];
}

/**
 * Fetches the HR access level of the current user from the backend.
 *   - `'lead'`  — full HR access, including destructive/account actions
 *   - `'senior'` — full employee directory visibility and normal HR writes
 *   - `'middle'` — own department visibility with basic edits
 *   - `'junior'` — own department read-only access
 *   - `null`     — no HR access
 */
export function useHRLevel(options: { enabled?: boolean } = {}) {
  const { data, isLoading } = useQuery<HRLevelResponse>({
    queryKey: ['hr-level'],
    queryFn: async () => {
      const res = await api.get<HRLevelResponse>('hr/v1/employees/hr-level/');
      return res.data;
    },
    enabled: options.enabled ?? true,
    staleTime: 5 * 60 * 1000, // cache for 5 min
    retry: false,
  });

  return {
    level: data?.level ?? null,
    scopeDepartmentId: data?.scope_department_id ?? null,
    hasHrAccess: Boolean(data?.level),
    isLead: data?.level === 'lead',
    isSenior: data?.level === 'senior' || data?.level === 'lead',
    isSeniorOrAbove: data?.level === 'senior' || data?.level === 'lead',
    isMiddle: data?.level === 'middle',
    isMiddleOrAbove: data?.level === 'middle' || data?.level === 'senior' || data?.level === 'lead',
    isJunior: data?.level === 'junior',
    canReadAll: Boolean(data?.can_read_all),
    canWriteBasic: Boolean(data?.can_write_basic),
    canCreateEmployee: Boolean(data?.can_create_employee),
    canTransferEmployee: Boolean(data?.can_transfer_employee),
    canDeleteEmployee: Boolean(data?.can_delete_employee),
    canListUserOptions: Boolean(data?.can_list_user_options),
    canManageUserOptions: Boolean(data?.can_manage_user_options),
    permissions: data?.permissions ?? [],
    hasPerm: (key: string) =>
      (data?.permissions ?? []).includes('*') || (data?.permissions ?? []).includes(key),
    isLoading,
  };
}
