/**
 * Клиент бюджета проекта модуля БЗО (`/api/bpp/v1/budgets`, ТЗ §06, B2.1).
 *
 * Деньги приходят строкой (Decimal на сервере) и уходят строкой: `float` в
 * расчётах денег не участвует (ТЗ §13.2). Изменяющие запросы несут `version`
 * карточки (E-CON-01) и `Idempotency-Key` кнопки (`useIdempotentAction`).
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

export type Money = string;

export const BUDGETS_BASE = '/bpp/budgets';
export const BUDGETS_ENDPOINT = apiPath('bpp', 'budgets');
/** Тип объекта журнала изменений бюджета (`_meta.label_lower`). */
export const BUDGET_HISTORY_TYPE = 'bpp.budget';

export const budgetKey = (id: string) => ['bpp', 'budget', id] as const;

export interface BudgetLine {
  id: string;
  article_id: string;
  article_code: string;
  article_name: string;
  article_archived: boolean;
  group_code: string;
  group_name: string;
  limit_amount: Money;
  comment: string;
  /** `null` — бюджет ещё не утверждён, «Задействовано» не показывается. */
  committed: Money | null;
  /** «Оплачено факт» по выписке (CALC-007); `null` — бюджет не утверждён или
   * подмодуль выписки у компании выключен. */
  paid_fact: Money | null;
  available: Money | null;
}

export interface BudgetTotals {
  limit_amount: Money;
  committed: Money;
  /** `null` — «Оплачено факт» не показывается (см. `BudgetLine.paid_fact`). */
  paid_fact: Money | null;
  available: Money;
  by_group: {
    group_code: string;
    group_name: string;
    limit_amount: Money;
    committed: Money;
    paid_fact: Money | null;
    available: Money;
  }[];
}

export interface BudgetVersion {
  id: string;
  version_no: number;
  state: 'draft' | 'active' | 'archived';
  comment: string;
  approved_at: string | null;
  approved_by: number | null;
  approved_by_name: string | null;
}

export interface BudgetCard {
  id: string;
  number: string;
  status: 'draft' | 'approved' | 'closed';
  version: number;
  currency_code: string;
  project: {
    id: string;
    code: string | null;
    name: string | null;
    customer_name?: string | null;
    manager_user_id?: number | null;
  };
  date_from: string | null;
  date_to: string | null;
  status_comment: string;
  active_version: BudgetVersion | null;
  correction: {
    version_no: number;
    comment: string;
    lines: BudgetLine[];
    totals: BudgetTotals;
  } | null;
  lines: BudgetLine[];
  totals: BudgetTotals;
  created_at: string;
  created_by: number | null;
  created_by_name?: string | null;
  allowed_actions: string[];
}

export interface BudgetRow {
  id: string;
  number: string;
  status: BudgetCard['status'];
  currency_code: string;
  project: { id: string; code: string | null; name: string | null };
  version_no: number;
  limit_amount: Money;
  committed: Money;
  paid_fact: Money | null;
  available: Money;
  approved_at: string | null;
  approved_by_name: string | null;
}

/** Строка формы — то, что уходит в `lines` запроса. */
export interface BudgetLineInput {
  article_id: string;
  limit_amount: Money;
  comment: string;
}

export interface BudgetCreate {
  project_id: string;
  currency: string;
  lines: BudgetLineInput[];
}

const path = (suffix = '') => apiPath('bpp', suffix ? `budgets/${suffix}` : 'budgets');
const withKey = (key: string) => ({ headers: { 'Idempotency-Key': key } });

export const budgetApi = {
  get: (id: string) => api.get<BudgetCard>(path(id)).then((r) => r.data),
  create: (key: string, body: BudgetCreate) =>
    api.post<BudgetCard>(path(), body, withKey(key)).then((r) => r.data),
  save: (id: string, key: string, body: { version: number; lines: BudgetLineInput[] }) =>
    api.patch<BudgetCard>(path(id), body, withKey(key)).then((r) => r.data),
  remove: (id: string, key: string, version: number) =>
    api.delete(path(id), { ...withKey(key), params: { version } }).then(() => undefined),
  approve: (id: string, key: string, version: number) =>
    api.post<BudgetCard>(path(`${id}/approve`), { version }, withKey(key)).then((r) => r.data),
  startCorrection: (id: string, key: string, version: number) =>
    api.post<BudgetCard>(path(`${id}/correction`), { version }, withKey(key)).then((r) => r.data),
  saveCorrection: (
    id: string, key: string, body: { version: number; lines: BudgetLineInput[]; comment: string },
  ) => api.patch<BudgetCard>(path(`${id}/correction`), body, withKey(key)).then((r) => r.data),
  approveCorrection: (id: string, key: string, version: number, comment: string) =>
    api.post<BudgetCard>(path(`${id}/correction/approve`), { version, comment }, withKey(key))
      .then((r) => r.data),
  cancelCorrection: (id: string, key: string, version: number) =>
    api.post<BudgetCard>(path(`${id}/correction/cancel`), { version }, withKey(key))
      .then((r) => r.data),
  close: (id: string, key: string, version: number, comment: string) =>
    api.post<BudgetCard>(path(`${id}/close`), { version, comment }, withKey(key))
      .then((r) => r.data),
  reopen: (id: string, key: string, version: number, comment: string) =>
    api.post<BudgetCard>(path(`${id}/reopen`), { version, comment }, withKey(key))
      .then((r) => r.data),
  versions: (id: string) => api.get<BudgetVersion[]>(path(`${id}/versions`)).then((r) => r.data),
};
