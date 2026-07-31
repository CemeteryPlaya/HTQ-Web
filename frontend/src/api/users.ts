import api from './client';
import { apiPath } from './endpoints';

export const usersApi = {
  getToken: (email: string, password: string) =>
    api.post(apiPath('users', 'token/'), { email, password }),
  getProfile: () => api.get(apiPath('users', 'profile/me')),
  register: (data: any) => api.post(apiPath('users', 'register/'), data),
};

export interface UserOption {
  id: number;
  full_name: string;
  /** Empty string for non-elevated callers — the endpoint withholds contact
   *  data from them on purpose. Render `full_name` alone in that case. */
  email: string;
}

/**
 * Active-user picker.
 *
 * A search, not a directory dump: the endpoint requires at least two
 * characters and caps the page at 20. Callers must debounce and must not
 * try to preload the whole list — there is no request shape that returns
 * it.
 */
export const searchUserOptions = async (
  query: string,
  limit = 20,
): Promise<UserOption[]> => {
  if (query.trim().length < 2) return [];
  const res = await api.get(apiPath('users', 'options/'), {
    params: { query: query.trim(), limit },
  });
  return Array.isArray(res.data) ? res.data : [];
};
