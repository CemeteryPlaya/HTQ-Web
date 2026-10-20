/**
 * Клиент справочника потенциальных поставщиков (`/api/tender/v1/prospects`,
 * план этапов 0–2 §4.1, §4.3): поставщик, которого ещё нет среди
 * контрагентов БЗО; карточка контрагента заводится после выбора (этап 5).
 * Правка несёт `version` (409 `E-CON-01`).
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import { compactParams, rowsOf } from '../tenders/api';

export const PROSPECTS_BASE = '/tender/prospects';

export interface Prospect {
  id: string;
  name: string;
  email: string;
  reg_number: string;
  country_code: string;
  counterparty_id: string | null;
  version: number;
}

export interface ProspectInput {
  name: string;
  email: string;
  reg_number: string;
  country_code: string;
}

export const prospectKeys = {
  all: ['tender', 'prospects'] as const,
  list: (q: string) => ['tender', 'prospects', 'list', q] as const,
};

const path = (suffix = '') => apiPath('tender', suffix ? `prospects/${suffix}` : 'prospects');

export const prospectsApi = {
  list: (q = '') =>
    api.get<unknown>(path(), { params: compactParams({ q }) }).then((r) => rowsOf<Prospect>(r.data)),
  create: (body: ProspectInput) => api.post<Prospect>(path(), body).then((r) => r.data),
  save: (id: string, body: ProspectInput & { version: number }) =>
    api.patch<Prospect>(path(id), body).then((r) => r.data),
};
