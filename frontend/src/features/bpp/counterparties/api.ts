/**
 * Клиент справочника «Контрагенты» модуля БЗО (`/api/bpp/v1/counterparties…`,
 * ТЗ §18, L-08; сервер — задача A2.3, `apps/bpp/views_counterparties.py`).
 *
 * Все записывающие ручки идемпотентны: ключ `Idempotency-Key` приходит от
 * `useIdempotentAction` (повтор после обрыва сети идёт тем же ключом, и
 * сервер отдаёт первый ответ). Правка карточки, блокировка, архив и метка
 * сверяют `version` — устаревшая даёт 409 `E-CON-01`.
 *
 * Страны для выбора — справочник `refdata` (`?active=1`: архивную страну в
 * новый документ не ставят). Свой короткий запрос, а не клиент экранов
 * справочников: тем нужен полный набор полей и правка, здесь — только выбор.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import type { CounterpartyKind } from './validation';

export type { CounterpartyKind } from './validation';
export type CounterpartyStatus = 'active' | 'blocked' | 'archived';

export interface BankAccount {
  id: string;
  counterparty_id: string;
  iban: string;
  bank_name: string;
  bic: string;
  currency: string;
  is_primary: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** Строка реестра L-08 (без счетов и `allowed_actions`). */
export interface CounterpartyRow {
  id: string;
  name: string;
  short_name: string;
  kind: CounterpartyKind;
  country_code: string;
  reg_number: string;
  is_vat_payer: boolean;
  vat_cert_series: string;
  vat_cert_number: string;
  legal_address: string;
  contact_person: string;
  phone: string;
  email: string;
  status: CounterpartyStatus;
  block_reason: string;
  blocked_at: string | null;
  blocked_by: number | null;
  successful_documents: number;
  /** `null` — метку ставит порог; `true`/`false` — решение ФД. */
  verified_override: boolean | null;
  verified_threshold: number;
  is_verified: boolean;
  ext_1c_ref: string;
  version: number;
  created_at: string;
  created_by: number | null;
  updated_at: string;
  updated_by: number | null;
}

/** Действия карточки — сервер решает по правам и статусу. */
export type CounterpartyAction =
  | 'edit' | 'add_account' | 'block' | 'unblock' | 'archive' | 'verified';

export interface CounterpartyCard extends CounterpartyRow {
  bank_accounts: BankAccount[];
  allowed_actions: CounterpartyAction[];
}

/** Поля формы карточки (статус, блокировка и метка — своими действиями). */
export interface CounterpartyInput {
  name: string;
  short_name: string;
  kind: CounterpartyKind;
  country_code: string;
  reg_number: string;
  is_vat_payer: boolean;
  vat_cert_series: string;
  vat_cert_number: string;
  legal_address: string;
  contact_person: string;
  phone: string;
  email: string;
}

export interface BankAccountInput {
  iban: string;
  bic: string;
  bank_name: string;
  currency: string;
  is_primary: boolean;
}

export interface CountryOption {
  code: string;
  name: string;
}

/** Экраны справочника внутри раздела `/bpp`. */
export const COUNTERPARTIES_BASE = '/bpp/counterparties';
export const counterpartyHref = (id: string) => `${COUNTERPARTIES_BASE}/${id}`;

/** Адрес реестра для `BppRegistry` (относительно `/api/`). */
export const COUNTERPARTIES_ENDPOINT = apiPath('bpp', 'counterparties');

const path = (suffix: string) => apiPath('bpp', `counterparties/${suffix}`);
const keyed = (key: string) => ({ headers: { 'Idempotency-Key': key } });

export const counterpartyApi = {
  get: (id: string) =>
    api.get<CounterpartyCard>(path(id)).then((r) => r.data),

  create: (key: string, body: CounterpartyInput) =>
    api.post<CounterpartyCard>(COUNTERPARTIES_ENDPOINT, body, keyed(key)).then((r) => r.data),

  update: (id: string, key: string, body: Partial<CounterpartyInput> & { version: number }) =>
    api.patch<CounterpartyCard>(path(id), body, keyed(key)).then((r) => r.data),

  block: (id: string, key: string, body: { version: number; reason: string }) =>
    api.post<CounterpartyCard>(path(`${id}/block`), body, keyed(key)).then((r) => r.data),

  unblock: (id: string, key: string, body: { version: number }) =>
    api.post<CounterpartyCard>(path(`${id}/unblock`), body, keyed(key)).then((r) => r.data),

  archive: (id: string, key: string, body: { version: number }) =>
    api.post<CounterpartyCard>(path(`${id}/archive`), body, keyed(key)).then((r) => r.data),

  setVerified: (id: string, key: string, body: { version: number; verified: boolean | null }) =>
    api.post<CounterpartyCard>(path(`${id}/verified`), body, keyed(key)).then((r) => r.data),

  addAccount: (id: string, key: string, body: BankAccountInput) =>
    api.post<BankAccount>(path(`${id}/accounts`), body, keyed(key)).then((r) => r.data),

  updateAccount: (
    accountId: string, key: string, body: Partial<BankAccountInput> & { is_active?: boolean },
  ) => api.patch<BankAccount>(path(`accounts/${accountId}`), body, keyed(key)).then((r) => r.data),

  /** Поиск для выбора контрагента в чужих формах (заказчик проекта):
   * первая страница реестра, только действующие. */
  search: (q: string) =>
    api.get<{ items: CounterpartyRow[]; total: number }>(COUNTERPARTIES_ENDPOINT, {
      params: { q: q || undefined, status: 'active', page_size: 25 },
    }).then((r) => r.data),

  countries: () =>
    api.get<CountryOption[]>(apiPath('refdata', 'countries'), { params: { active: 1 } })
      .then((r) => r.data),
};

/** Ключ кеша карточки — общий для экрана карточки и её вкладок. */
export const counterpartyKey = (id: string) => ['bpp', 'counterparty', id] as const;
export const COUNTRIES_KEY = ['refdata', 'countries', 'active'] as const;
