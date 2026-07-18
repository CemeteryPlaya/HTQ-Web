import api from '@/api/client';

export interface PlatformAccount {
  id: number;
  username: string;
  email: string;
  first_name?: string;
  last_name?: string;
  display_name?: string;
  status: 'pending' | 'active' | 'suspended' | 'rejected';
  is_staff: boolean;
  is_superuser: boolean;
  date_joined?: string | null;
  last_login?: string | null;
}

export const fetchPlatformAccounts = async (): Promise<PlatformAccount[]> => {
  const res = await api.get('users/v1/admin/users/');
  const data = res.data as unknown;
  if (Array.isArray(data)) return data as PlatformAccount[];
  if (data && Array.isArray((data as any).items)) return (data as any).items;
  return [];
};

export const updatePlatformAccount = async (
  id: number,
  patch: Partial<Pick<PlatformAccount, 'status' | 'is_staff' | 'is_superuser'>>,
): Promise<PlatformAccount> => {
  const res = await api.patch(`users/v1/admin/users/${id}/`, patch);
  return res.data;
};

/** Generate a temporary password the user must change on next login. */
export const resetPlatformAccountPassword = async (
  id: number,
): Promise<string> => {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
  const newPassword = Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('');
  await api.post(`users/v1/admin/users/${id}/set-password/`, {
    new_password: newPassword,
    must_change_password: true,
  });
  return newPassword;
};
