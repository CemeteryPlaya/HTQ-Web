/**
 * Клиент договора модуля БЗО (`/api/bpp/v1/agreements`, ТЗ §09, B3.1).
 *
 * Деньги и количества — строками (Decimal на сервере). Изменяющие запросы
 * несут `version` карточки (E-CON-01) и `Idempotency-Key` кнопки.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import type { CurrentHolders } from '../core/registryTypes';
import type { AlternativeLinks } from '../selection/links';
import type { InitiatorRole } from '../requests/api';

export type Money = string;

export const AGREEMENTS_BASE = '/bpp/agreements';
export const AGREEMENTS_ENDPOINT = apiPath('bpp', 'agreements');
export const AGREEMENT_SUBJECT = 'bpp.agreement';
export const AGREEMENT_HISTORY_TYPE = 'bpp.agreement';

export const agreementKey = (id: string) => ['bpp', 'agreement', id] as const;

export type AgreementType = 'goods' | 'works' | '';

export interface AgreementItem {
  id: string;
  request_item_id: string;
  sys_number: string;
  name: string;
  request_id: string;
  request_number: string;
  uom: string | null;
  plan_qty: string;
  plan_amount: Money;
  qty: string;
  amount: Money | null;
  qty_available: string;
}

export interface CounterpartyBrief {
  id: string;
  name: string;
  short_name: string;
  reg_number: string;
  country_code: string;
  is_vat_payer: boolean;
  status: string;
  is_verified: boolean;
}

export interface AgreementCard {
  /** Перенесён из «Договоров» (B6.1) — пометка в реестре и карточке. */
  is_migrated?: boolean;
  id: string;
  number: string;
  status: string;
  version: number;
  author_id: number;
  author_name: string | null;
  created_at: string;
  project: { id: string; code: string | null; name: string | null };
  article: { id: string; code: string | null; name: string | null; archived: boolean };
  counterparty: CounterpartyBrief | null;
  counterparty_confirmed: boolean;
  name: string;
  ext_number: string;
  ext_date: string | null;
  agreement_type: AgreementType;
  is_open: boolean;
  amount: Money | null;
  currency_code: string;
  with_vat: boolean;
  vat_rate: string | null;
  vat_source: '' | 'refdata' | 'default' | 'manual';
  vat_amount: Money | null;
  amount_without_vat: Money | null;
  vat_warning: string | null;
  valid_to: string | null;
  status_comment: string;
  rework_comment: string;
  parent: { id: string; number: string } | null;
  supplements: { id: string; number: string; status: string; amount: Money | null;
    ext_date: string | null }[];
  effective_amount: Money | null;
  remaining: Money | null;
  budget: { available: Money; over_plan: Money; plan_total: Money } | null;
  items: AgreementItem[];
  current_holders: CurrentHolders | null;
  /** Связь с альтернативой (B5.1): основание нового договора и чем заменён исходный. */
  alternative?: AlternativeLinks;
  allowed_actions: string[];
}

export interface AgreementRow {
  /** Перенесён из «Договоров» (B6.1) — пометка в реестре и карточке. */
  is_migrated?: boolean;
  id: string;
  number: string;
  status: string;
  created_at: string;
  author_name: string | null;
  ext_number: string;
  ext_date: string | null;
  name: string;
  project_code: string | null;
  article_name: string | null;
  counterparty_name: string | null;
  is_open: boolean;
  amount: Money | null;
  currency_code: string;
  remaining: Money | null;
  valid_to: string | null;
  is_supplement: boolean;
  current_holders: CurrentHolders | null;
}

export interface AgreementExecution {
  invoices: { id: string; number: string; ext_number: string; ext_date: string | null;
    amount: Money; currency_code: string; status: string; paid_bank_amount: Money }[];
  effective_amount: Money | null;
  remaining: Money | null;
}

/** Тело правки черновика — только присланные поля (сервер меняет их одни). */
export interface AgreementPatch {
  counterparty_id?: string | null;
  name?: string;
  ext_number?: string;
  ext_date?: string | null;
  agreement_type?: AgreementType;
  is_open?: boolean;
  amount?: string | null;
  with_vat?: boolean;
  vat_rate?: string | null;
  valid_to?: string | null;
  items?: { id: string; qty: string; amount: string | null }[];
}

const path = (suffix = '') => apiPath('bpp', suffix ? `agreements/${suffix}` : 'agreements');
const withKey = (key: string) => ({ headers: { 'Idempotency-Key': key } });

export const agreementApi = {
  get: (id: string) => api.get<AgreementCard>(path(id)).then((r) => r.data),
  createFromPlan: (key: string, itemIds: string[], role: InitiatorRole | null) =>
    api.post<AgreementCard>(path(), { item_ids: itemIds, ...(role ? { role } : {}) },
      withKey(key)).then((r) => r.data),
  save: (id: string, key: string, body: AgreementPatch & { version: number }) =>
    api.patch<AgreementCard>(path(id), body, withKey(key)).then((r) => r.data),
  remove: (id: string, key: string, version: number) =>
    api.delete(path(id), { ...withKey(key), params: { version } }).then(() => undefined),
  submit: (id: string, key: string, version: number, counterpartyConfirmed: boolean) =>
    api.post<AgreementCard>(path(`${id}/submit`),
      { version, counterparty_confirmed: counterpartyConfirmed }, withKey(key))
      .then((r) => r.data),
  withdraw: (id: string, key: string, version: number) =>
    api.post<AgreementCard>(path(`${id}/withdraw`), { version }, withKey(key))
      .then((r) => r.data),
  fulfil: (id: string, key: string, version: number) =>
    api.post<AgreementCard>(path(`${id}/fulfil`), { version }, withKey(key))
      .then((r) => r.data),
  terminate: (id: string, key: string, version: number, comment: string) =>
    api.post<AgreementCard>(path(`${id}/terminate`), { version, comment }, withKey(key))
      .then((r) => r.data),
  supplement: (id: string, key: string) =>
    api.post<AgreementCard>(path(`${id}/supplement`), {}, withKey(key)).then((r) => r.data),
  execution: (id: string) =>
    api.get<AgreementExecution>(path(`${id}/execution`)).then((r) => r.data),
};
