/**
 * api/companies.ts
 * Клиент реестра компаний (`/api/companies/v1`). Пути без завершающего
 * слэша — бэкенд регистрирует оба написания. Слой транспортный.
 *
 * Создания компании здесь нет намеренно: заведение — `manage.py company_create`
 * (миграции схемы ~1 мин не помещаются в HTTP-запрос).
 */

import api from './client';
import { apiPath } from './endpoints';
import type {
  Company,
  CompanyMembership,
  CompanyModule,
  CompanyPatch,
  CompanyTreeNode,
  ExternalHolder,
  MyCompany,
} from '@/types/companies';

const path = (suffix: string) => apiPath('companies', suffix);

export const companiesApi = {
  /** Компании, где у меня есть членство и которые действуют. */
  myCompanies: () => api.get<MyCompany[]>(path('me')),

  list: (status: 'all' | 'active' | 'archived' = 'all') =>
    api.get<Company[]>(path(`companies?status=${status}`)),
  tree: () => api.get<CompanyTreeNode[]>(path('companies/tree')),
  get: (slug: string) => api.get<Company>(path(`companies/${slug}`)),
  patch: (slug: string, body: CompanyPatch) =>
    api.patch<Company>(path(`companies/${slug}`), body),
  /** 409 `last_active` — единственную действующую компанию архивировать нельзя. */
  archive: (slug: string) => api.post<Company>(path(`companies/${slug}/archive`)),
  restore: (slug: string) => api.post<Company>(path(`companies/${slug}/restore`)),

  modules: (slug: string) => api.get<CompanyModule[]>(path(`companies/${slug}/modules`)),
  /** 409 — модуль ядра; 422 — неизвестный модуль. */
  setModule: (slug: string, appLabel: string, body: { enabled: boolean; message?: string }) =>
    api.patch<CompanyModule>(path(`companies/${slug}/modules/${appLabel}`), body),

  memberships: (slug: string) =>
    api.get<CompanyMembership[]>(path(`companies/${slug}/memberships`)),
  grantMembership: (slug: string, body: { user_id: number; is_default?: boolean }) =>
    api.post<CompanyMembership>(path(`companies/${slug}/memberships`), body),
  /** 409 `self_revoke` — своё членство снять нельзя. */
  revokeMembership: (slug: string, userId: number) =>
    api.delete<void>(path(`companies/${slug}/memberships/${userId}`)),

  /**
   * Задача 7 блока C: держатели прав из вышестоящих компаний. 403 с телом,
   * если `show_external_holders` у компании выключен, — вызывающий обязан
   * проверить настройку ДО запроса (см. `CompanyMembersPanel`), чтобы не
   * показать пользователю голую ошибку вместо отсутствующей секции.
   */
  externalHolders: (slug: string) =>
    api.get<ExternalHolder[]>(path(`companies/${slug}/external-holders`)),
};
