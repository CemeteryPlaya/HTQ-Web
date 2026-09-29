/**
 * Клиент заявки на закупку модуля БЗО (`/api/bpp/v1/requests`, ТЗ §07, B2.2).
 *
 * Карточку читают и форма F-02, и карточка согласования
 * (`app/signoffSubjectViews`). Деньги и количества — строками (Decimal на
 * сервере). Изменяющие запросы несут `version` карточки (E-CON-01) и
 * `Idempotency-Key` кнопки.
 */

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import type { CurrentHolders } from '../core/registryTypes';

/** Деньги и количества приходят строкой (Decimal на сервере). */
export type Money = string;

export type InitiatorRole = 'sn' | 'pm';
export type PurchaseType = 'goods' | 'works' | '';

export const REQUESTS_BASE = '/bpp/requests';
export const REQUESTS_ENDPOINT = apiPath('bpp', 'requests');
/** Предмет согласования и владелец файлов в `apps.files`. */
export const REQUEST_SUBJECT = 'bpp.purchase_request';
/** Тип объекта журнала изменений (`_meta.label_lower`). */
export const REQUEST_HISTORY_TYPE = 'bpp.purchaserequest';

export const requestKey = (id: string) => ['bpp', 'request', id] as const;

export interface PurchaseRequestItem {
  id: string;
  line_no: number;
  sys_number: string;
  name: string;
  specs: string;
  uom_id: string;
  uom: string | null;
  qty: string;
  price: Money;
  amount: Money;
  need_date: string;
  status: 'open' | 'partially_closed' | 'closed' | 'annulled';
}

export interface RequestBudget {
  limit: Money;
  committed: Money;
  available: Money;
  after_request: Money;
  reserved: boolean;
}

export interface PurchaseRequestCard {
  id: string;
  number: string;
  status: string;
  version: number;
  author_id: number;
  author_name: string | null;
  created_at: string;
  initiator_role: InitiatorRole;
  project: { id: string; code: string | null; name: string | null };
  article: { id: string; code: string | null; name: string | null; archived: boolean } | null;
  purchase_type: PurchaseType;
  need_date: string | null;
  justification: string;
  currency_code: string;
  total_amount: Money;
  status_comment: string;
  rework_comment: string;
  budget: RequestBudget | null;
  items: PurchaseRequestItem[];
  current_holders: CurrentHolders | null;
  files: { id: string; filename: string; version: number }[];
  allowed_actions: string[];
}

export interface RequestRow {
  id: string;
  number: string;
  status: string;
  created_at: string;
  author_id: number;
  author_name: string | null;
  initiator_role: InitiatorRole;
  project_id: string;
  project_code: string | null;
  article_id: string | null;
  article_name: string | null;
  purchase_type: PurchaseType;
  need_date: string | null;
  total_amount: Money;
  currency_code: string;
  current_holders: CurrentHolders | null;
}

export interface RequestItemInput {
  name: string;
  specs: string;
  uom_id: string | null;
  qty: string;
  price: string;
  need_date: string | null;
}

export interface RequestInput {
  initiator_role: InitiatorRole | null;
  project_id: string | null;
  article_id: string | null;
  purchase_type: PurchaseType;
  need_date: string | null;
  justification: string;
  items: RequestItemInput[];
}

/** Строка бюджета проекта в группе роли — выбор статьи формы (GetBudgetLines). */
export interface BudgetLineOption {
  article_id: string;
  article_code: string;
  article_name: string;
  limit: Money;
  committed: Money;
  available: Money;
}

export interface ExecutionRow {
  id: string;
  sys_number: string;
  name: string;
  status: string;
  qty: string;
  qty_in_agreements: string;
  qty_in_invoices: string;
  amount: Money;
  amount_in_invoices: Money;
  amount_paid: Money;
  amount_left: Money;
}

export interface BppMe {
  article_groups: string[];
  initiator_roles: InitiatorRole[];
}

const path = (suffix = '') => apiPath('bpp', suffix ? `requests/${suffix}` : 'requests');
const withKey = (key: string) => ({ headers: { 'Idempotency-Key': key } });

export const bppRequestsApi = {
  get: (id: string) => api.get<PurchaseRequestCard>(path(id)).then((r) => r.data),
  create: (key: string, body: RequestInput) =>
    api.post<PurchaseRequestCard>(path(), body, withKey(key)).then((r) => r.data),
  save: (id: string, key: string, body: RequestInput & { version: number }) =>
    api.patch<PurchaseRequestCard>(path(id), body, withKey(key)).then((r) => r.data),
  remove: (id: string, key: string, version: number) =>
    api.delete(path(id), { ...withKey(key), params: { version } }).then(() => undefined),
  submit: (id: string, key: string, version: number) =>
    api.post<PurchaseRequestCard>(path(`${id}/submit`), { version }, withKey(key))
      .then((r) => r.data),
  withdraw: (id: string, key: string, version: number) =>
    api.post<PurchaseRequestCard>(path(`${id}/withdraw`), { version }, withKey(key))
      .then((r) => r.data),
  cancel: (id: string, key: string, version: number, comment: string) =>
    api.post<PurchaseRequestCard>(path(`${id}/cancel`), { version, comment }, withKey(key))
      .then((r) => r.data),
  closeRemainder: (id: string, key: string, version: number, comment: string) =>
    api.post<PurchaseRequestCard>(path(`${id}/close-remainder`), { version, comment },
      withKey(key)).then((r) => r.data),
  copy: (id: string, key: string) =>
    api.post<PurchaseRequestCard>(path(`${id}/copy`), {}, withKey(key)).then((r) => r.data),
  execution: (id: string) => api.get<ExecutionRow[]>(path(`${id}/execution`)).then((r) => r.data),
  /** PDF печатной формы — через клиент API (JWT), а не прямой ссылкой. */
  print: (id: string) =>
    api.get<Blob>(path(`${id}/print`), { responseType: 'blob' }).then((r) => r.data),
  budgetLines: (projectId: string, role: InitiatorRole) =>
    api.get<BudgetLineOption[]>(apiPath('bpp', 'budgets/lines'), {
      params: { project_id: projectId, role },
    }).then((r) => r.data),
  me: () => api.get<BppMe>(apiPath('bpp', 'me')).then((r) => r.data),
};
