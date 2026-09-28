/**
 * Клиент договора модуля БЗО (`/api/bpp/v1/agreements`, ТЗ §09, B3.1).
 *
 * Деньги и количества — строками (Decimal на сервере). Изменяющие запросы
 * несут `version` карточки (E-CON-01) и `Idempotency-Key` кнопки.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import type { CurrentHolders } from '../core/registryTypes';

export type Money = string;

export const AGREEMENTS_BASE = '/bpp/agreements';
export const AGREEMENTS_ENDPOINT = apiPath('bpp', 'agreements');
export const AGREEMENT_SUBJECT = 'bpp.agreement';
export const AGREEMENT_HISTORY_TYPE = 'bpp.agreement';

export const agreementKey = (id: string) => ['bpp', 'agreement', id] as const;

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
  agreement_type: 'goods' | 'works' | '';
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
  allowed_actions: string[];
}

export const agreementApi = {
  get: (id: string) =>
    api.get<AgreementCard>(apiPath('bpp', `agreements/${id}`)).then((r) => r.data),
};
