import api from './client';
import { apiPath } from './endpoints';

export const usersApi = {
  getToken: (email: string, password: string) =>
    api.post(apiPath('users', 'token/'), { email, password }),
  getProfile: () => api.get(apiPath('users', 'profile/me')),
  register: (data: any) => api.post(apiPath('users', 'register/'), data),
};
