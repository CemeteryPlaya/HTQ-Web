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
  id: string;
  number: string;
  status: string;
  version: number;
  author_id: number;
  author_name: string | null;
  created_at: string;
  basis: 'no_contract' | 'contract';
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
  allowed_actions: string[];
}

export const invoiceApi = {
  get: (id: string) =>
    api.get<InvoiceCard>(apiPath('bpp', `invoices/${id}`)).then((r) => r.data),
};
