/**
 * Клиент подотчётных средств модуля БЗО (`/api/bpp/v1/accountable`, B4.1).
 *
 * Деньги — строками (Decimal на сервере). Изменяющие запросы несут
 * `Idempotency-Key` кнопки; правки черновика — ещё и `version` (E-CON-01).
 */

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import type { CurrentHolders } from '../core/registryTypes';
import type { HistoryFieldOptions } from '../core/HistoryTab';

export type Money = string;

export const ACCOUNTABLE_BASE = '/bpp/accountable';
export const ACCOUNTABLE_ENDPOINT = apiPath('bpp', 'accountable');
export const ACCOUNTABLE_SUBJECT = 'bpp.accountable_funds_request';
export const ACCOUNTABLE_HISTORY_TYPE = 'bpp.accountablefundsrequest';

export const accountableKey = (id: string) => ['bpp', 'accountable', id] as const;

export type AccountableStatus =
  'draft' | 'on_review' | 'awaiting_accounting' | 'awaiting_report' | 'closed';

export interface ReportFile {
  id: string;
  filename: string;
}

export interface AdvanceReportRow {
  id: string;
  expense_name: string;
  amount: Money;
  approval_state: string;
  created_at: string;
  files?: ReportFile[];
  /** Отправить отчёт может подотчётное лицо, пока отчёт не на согласовании. */
  can_submit?: boolean;
}

export interface AccountableCard {
  /** Перенесён из «Договоров» (B6.1) — пометка в реестре и карточке. */
  is_migrated?: boolean;
  id: string;
  number: string;
  status: AccountableStatus;
  version?: number;
  project?: { id: string; code: string | null; name: string | null };
  project_id?: string;
  article_id?: string;
  article_name: string;
  amount: Money;
  currency: string;
  goal: string;
  accountable_user_id?: number;
  accountable_user_name?: string | null;
  paid_at: string | null;
  paid_by_name?: string | null;
  reported_amount: Money;
  remaining_amount: Money;
  reports: AdvanceReportRow[];
  current_holders?: CurrentHolders | null;
  allowed_actions?: string[];
  created_at: string;
}

export interface AccountableRow {
  /** Перенесён из «Договоров» (B6.1) — пометка в реестре и карточке. */
  is_migrated?: boolean;
  id: string;
  number: string;
  status: AccountableStatus;
  created_at: string;
  accountable_user_id: number;
  accountable_user_name: string | null;
  project_id: string;
  project_code: string | null;
  article_id: string;
  article_name: string | null;
  goal: string;
  amount: Money;
  currency: string;
  reported_amount: Money;
  remaining_amount: Money;
  current_holders: CurrentHolders | null;
}

export interface AccountableInput {
  project_id: string;
  article_id: string;
  amount: string;
  goal: string;
}

const path = (suffix = '') => apiPath('bpp', suffix ? `accountable/${suffix}` : 'accountable');
const withKey = (key: string) => ({ headers: { 'Idempotency-Key': key } });

export const bppAccountableApi = {
  get: (id: string) => api.get<AccountableCard>(path(id)).then((r) => r.data),
  create: (key: string, body: AccountableInput) =>
    api.post<AccountableCard>(path(), body, withKey(key)).then((r) => r.data),
  save: (id: string, key: string, body: Partial<AccountableInput> & { version: number }) =>
    api.patch<AccountableCard>(path(id), body, withKey(key)).then((r) => r.data),
  remove: (id: string, key: string, version: number) =>
    api.delete(path(id), { ...withKey(key), params: { version } }).then(() => undefined),
  submit: (id: string, key: string, version: number) =>
    api.post<AccountableCard>(path(`${id}/submit`), { version }, withKey(key)).then((r) => r.data),
  markPaid: (id: string, key: string, version: number) =>
    api.post<AccountableCard>(path(`${id}/mark-paid`), { version }, withKey(key))
      .then((r) => r.data),
  /** Авансовый отчёт: multipart — наименование затрат, сумма и подтверждающий файл. */
  addReport: (id: string, key: string, body: { expense_name: string; amount: string; file: File }) => {
    const form = new FormData();
    form.append('expense_name', body.expense_name);
    form.append('amount', body.amount);
    form.append('file', body.file);
    return api.post<AdvanceReportRow>(path(`${id}/reports`), form, withKey(key))
      .then((r) => r.data);
  },
  submitReport: (reportId: string, key: string) =>
    api.post<AdvanceReportRow>(path(`reports/${reportId}/submit`), {}, withKey(key))
      .then((r) => r.data),
  reportFileLink: (reportId: string) =>
    api.get<{ url: string }>(path(`reports/${reportId}/file-link`)).then((r) => r.data.url),
};

/** Подписи и денежные поля «Истории изменений» заявки на подотчёт. */
export const ACCOUNTABLE_HISTORY_FIELDS: HistoryFieldOptions = {
  fieldLabels: {
    amount: 'Сумма', goal: 'Цель', article_id: 'Статья бюджета', number: 'Номер',
    report: 'Авансовый отчёт',
  },
  moneyFields: ['amount'],
};
