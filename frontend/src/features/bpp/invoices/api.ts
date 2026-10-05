/**
 * Клиент счёта на оплату модуля БЗО (`/api/bpp/v1/invoices`, ТЗ §10, B3.2).
 *
 * Деньги и количества — строками (Decimal на сервере). Изменяющие запросы
 * несут `version` карточки (E-CON-01) и `Idempotency-Key` кнопки.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import type { CounterpartyBrief } from '../agreements/api';
import type { CurrentHolders } from '../core/registryTypes';
import type { AlternativeLinks, SelectionResult } from '../selection/links';

export type Money = string;

export const INVOICES_BASE = '/bpp/invoices';
export const INVOICES_ENDPOINT = apiPath('bpp', 'invoices');
export const INVOICE_SUBJECT = 'bpp.invoice';
export const INVOICE_HISTORY_TYPE = 'bpp.invoice';

export const invoiceKey = (id: string) => ['bpp', 'invoice', id] as const;

export interface InvoiceLine {
  id: string;
  request_item_id: string;
  sys_number: string;
  name: string;
  request_id: string;
  request_number: string;
  qty: string;
  amount: Money;
  plan_amount: Money;
  qty_available: string;
  amount_available: Money;
}

export interface PaymentMark {
  id: string;
  pay_date: string;
  amount: Money;
  pp_number: string;
  rate: string | null;
  marked_by_name: string | null;
  cancelled_at: string | null;
  cancel_comment: string;
}

export interface InvoiceCard {
  /** Перенесён из «Договоров» (B6.1) — пометка в реестре и карточке. */
  is_migrated?: boolean;
  id: string;
  number: string;
  status: string;
  version: number;
  author_id: number;
  author_name: string | null;
  created_at: string;
  basis: 'no_contract' | 'contract';
  initiator_role: 'sn' | 'pm' | '';
  agreement: {
    id: string; number: string; ext_number: string; ext_date: string | null;
    is_open: boolean; status: string; effective_amount: Money | null; remaining: Money | null;
  } | null;
  project: { id: string; code: string | null; name: string | null };
  article: { id: string; code: string | null; name: string | null };
  counterparty: CounterpartyBrief | null;
  counterparty_confirmed: boolean;
  ext_number: string;
  ext_date: string | null;
  amount: Money;
  currency_code: string;
  rate: string | null;
  rate_source: '' | 'kzt' | 'nbrk' | 'manual';
  amount_kzt: Money | null;
  threshold: Money | null;
  over_threshold: boolean;
  with_vat: boolean;
  vat_rate: string | null;
  vat_source: string;
  vat_amount: Money | null;
  vat_warning: string | null;
  purchase_type: 'goods' | 'works' | '';
  is_advance: boolean;
  due_date: string | null;
  planned_pay_date: string | null;
  fd_decided_at: string | null;
  status_comment: string;
  rework_comment: string;
  author_comment: string;
  docs_required: { avr?: boolean; waybill?: boolean; vat_invoice?: boolean };
  docs_requested_at: string | null;
  docs_comment: string;
  days_waiting_docs: number | null;
  recon_status: string;
  paid_bank_amount: Money;
  paid_amount: Money;
  unpaid_amount: Money;
  payments: PaymentMark[];
  possible_split: boolean;
  lines: InvoiceLine[];
  current_holders: CurrentHolders | null;
  /** Связь с альтернативой (B5.1): основание нового счёта и чем заменён исходный. */
  alternative?: AlternativeLinks;
  allowed_actions: string[];
}

/** Тело правки черновика — только присланные поля (сервер меняет их одни). */
export interface InvoicePatch {
  basis?: 'no_contract';
  counterparty_id?: string | null;
  ext_number?: string;
  ext_date?: string | null;
  amount?: string;
  currency_code?: string;
  rate?: string | null;
  with_vat?: boolean;
  vat_rate?: string | null;
  purchase_type?: 'goods' | 'works';
  is_advance?: boolean;
  due_date?: string | null;
  author_comment?: string;
  lines?: { id: string; qty: string; amount: string }[];
}

const path = (suffix = '') => apiPath('bpp', suffix ? `invoices/${suffix}` : 'invoices');
const withKey = (key: string) => ({ headers: { 'Idempotency-Key': key } });

export const invoiceApi = {
  get: (id: string) => api.get<InvoiceCard>(path(id)).then((r) => r.data),
  createFromPlan: (key: string, itemIds: string[], role: 'sn' | 'pm' | null) =>
    api.post<InvoiceCard>(path(), { item_ids: itemIds, ...(role ? { role } : {}) },
      withKey(key)).then((r) => r.data),
  createFromAgreement: (key: string, agreementId: string) =>
    api.post<InvoiceCard>(path(), { agreement_id: agreementId }, withKey(key))
      .then((r) => r.data),
  save: (id: string, key: string, body: InvoicePatch & { version: number }) =>
    api.patch<InvoiceCard>(path(id), body, withKey(key)).then((r) => r.data),
  remove: (id: string, key: string, version: number) =>
    api.delete(path(id), { ...withKey(key), params: { version } }).then(() => undefined),
  submit: (id: string, key: string, version: number, counterpartyConfirmed: boolean) =>
    api.post<InvoiceCard>(path(`${id}/submit`),
      { version, counterparty_confirmed: counterpartyConfirmed }, withKey(key))
      .then((r) => r.data),
  cancel: (id: string, key: string, version: number, comment: string) =>
    api.post<InvoiceCard>(path(`${id}/cancel`), { version, comment }, withKey(key))
      .then((r) => r.data),
  /** «Выбрать» альтернативу (B5.1, ТЗ §12.4 п.3): счёт «Заменён альтернативой». */
  selectAlternative: (id: string, key: string, body: {
    offer_id: string; comment: string; version: number;
  }) => api.post<SelectionResult<InvoiceCard>>(path(`${id}/select-alternative`), body,
    withKey(key)).then((r) => r.data),
  decide: (id: string, key: string, body: {
    decision: 'pay' | 'not_payable' | 'return'; planned_pay_date?: string | null; comment?: string;
  }) => api.post<InvoiceCard>(path(`${id}/decision`), body, withKey(key)).then((r) => r.data),
  batchDecision: (key: string, body: {
    invoice_ids: string[]; decision: 'pay' | 'not_payable'; comment?: string;
    planned_pay_date?: string;
  }) => api.post<{ ok: string[]; failed: { id: string; reason: string }[] }>(
    path('batch-decision'), body, withKey(key)).then((r) => r.data),
  pay: (id: string, key: string, body: {
    pay_date: string; amount: string; pp_number?: string; rate?: string | null;
  }) => api.post<InvoiceCard>(path(`${id}/payments`), body, withKey(key)).then((r) => r.data),
  unpay: (id: string, markId: string, key: string, comment: string) =>
    api.post<InvoiceCard>(path(`${id}/payments/${markId}/cancel`), { comment }, withKey(key))
      .then((r) => r.data),
  requestDocs: (id: string, key: string, body: {
    avr: boolean; waybill: boolean; vat_invoice: boolean; comment?: string;
  }) => api.post<InvoiceCard>(path(`${id}/request-docs`), body, withKey(key)).then((r) => r.data),
  submitDocs: (id: string, key: string) =>
    api.post<InvoiceCard>(path(`${id}/submit-docs`), {}, withKey(key)).then((r) => r.data),
  acceptDocs: (id: string, key: string) =>
    api.post<InvoiceCard>(path(`${id}/accept-docs`), {}, withKey(key)).then((r) => r.data),
  returnDocs: (id: string, key: string, comment: string) =>
    api.post<InvoiceCard>(path(`${id}/return-docs`), { comment }, withKey(key))
      .then((r) => r.data),
  /** Порог 1000 МРП на дату счёта (GetMrpThreshold, ТЗ §23); 422 — МРП на дату нет. */
  threshold: (onDate: string) =>
    api.get<{ date: string; threshold: Money }>(path('threshold'), { params: { date: onDate } })
      .then((r) => r.data.threshold),
};

export const EXPORT_QUEUE_ENDPOINT = apiPath('bpp', 'invoices/export-queue');

export interface InvoiceRow {
  /** Перенесён из «Договоров» (B6.1) — пометка в реестре и карточке. */
  is_migrated?: boolean;
  id: string;
  number: string;
  status: string;
  created_at: string;
  author_name: string | null;
  basis: 'no_contract' | 'contract';
  agreement_number: string | null;
  project_code: string | null;
  article_name: string | null;
  counterparty_name: string | null;
  counterparty_reg_number: string | null;
  counterparty_blocked: boolean;
  ext_number: string;
  ext_date: string | null;
  amount: Money;
  currency_code: string;
  amount_kzt: Money | null;
  due_date: string | null;
  planned_pay_date: string | null;
  overdue: boolean;
  docs_required: { avr?: boolean; waybill?: boolean; vat_invoice?: boolean };
  days_waiting_docs: number | null;
  recon_status: string;
  paid_bank_amount: Money;
  possible_split: boolean;
  current_holders: CurrentHolders | null;
}

/**
 * Отбор реестра, пришедший ссылкой (показатель дашборда «Оплаты», D-S4-8):
 * параметры адреса страницы `/bpp/invoices?…`, которые уходят в запрос
 * реестра как есть — имена совпадают с параметрами ручки `GET invoices`.
 * `status` и `recon_status` повторяются. `tab` — вкладка реестра.
 */
export const INVOICE_LINK_PARAMS = [
  'tab', 'status', 'recon_status', 'project_id', 'article_id', 'counterparty_id', 'author_id',
  'bank_date_from', 'bank_date_to', 'bank_wait_days',
] as const;

/** Параметры отбора из адреса страницы (порядок — как в адресе). Пусто — отбора нет. */
export function invoiceLinkParams(search: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  for (const [key, value] of search) {
    if (value && (INVOICE_LINK_PARAMS as readonly string[]).includes(key)) out.append(key, value);
  }
  return out;
}

/** Адрес реестра для `BppRegistry`: вкладка и отбор ссылки — строкой запроса,
 * остальное (страница, поиск, фильтры панели) реестр добавит сам. */
export function invoicesEndpoint(tab: string, link: URLSearchParams): string {
  const query = new URLSearchParams(link);
  query.delete('tab');
  if (tab !== 'all') query.set('tab', tab);
  const text = query.toString();
  return text ? `${INVOICES_ENDPOINT}?${text}` : INVOICES_ENDPOINT;
}
