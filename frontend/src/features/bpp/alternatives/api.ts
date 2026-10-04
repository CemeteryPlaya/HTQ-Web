/**
 * Клиент альтернативных предложений (`/api/bpp/v1/alternatives/…`; ТЗ §12,
 * A5.1; сервер — `apps/bpp/views_alternatives.py`, `services/alternatives/`).
 *
 * - Деньги, количества и проценты — строки-десятичные; на экран — через
 *   `formatMoney`/`money.ts`, без `float`.
 * - Изменяющие запросы несут `Idempotency-Key` кнопки и `version` карточки
 *   (устаревшая — 409 `E-CON-01`).
 * - Знак `deviation_pct` — плюс: АП дороже исходного (противоположен экономии).
 */
import type { TFunction } from 'i18next';

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

import type { CounterpartyBrief } from '../agreements/api';

export type Money = string;
export type SourceType = 'invoice' | 'agreement';

export const ALTERNATIVES_BASE = '/bpp/alternatives';
export const ALTERNATIVES_FEED_ENDPOINT = apiPath('bpp', 'alternatives/feed');
export const OFFER_FILE_OWNER = 'bpp.alternative_offer';
export const OFFER_HISTORY_TYPE = 'bpp.alternativeoffer';

export const offerHref = (id: string) => `${ALTERNATIVES_BASE}/${id}`;
export const offerKey = (id: string) => ['bpp', 'alternatives', 'offer', id] as const;
export const comparisonKey = (type: SourceType, id: string) =>
  ['bpp', 'alternatives', 'comparison', type, id] as const;

export const PAYMENT_TERMS = [
  { value: 'full_prepay', label: 'Полная предоплата' },
  { value: 'partial_prepay', label: 'Частичная предоплата' },
  { value: 'postpay', label: 'Постоплата' },
] as const;
export type PaymentTerms = (typeof PAYMENT_TERMS)[number]['value'];

export const paymentTermsLabel = (value: string, t: TFunction): string => {
  const entry = PAYMENT_TERMS.find((row) => row.value === value);
  return entry ? t(`bpp.alternatives.terms.${entry.value}`, entry.label) : '—';
};

export interface OfferSourceBrief {
  type: SourceType;
  id: string;
  number: string | null;
  status?: string;
  status_label?: string;
  amount?: Money | null;
  currency_code: string | null;
  counterparty?: CounterpartyBrief | null;
  author_id?: number | null;
  author_name?: string | null;
  alt_limit: number | null;
  window_open: boolean;
  url: string;
}

export interface OfferLine {
  id: string;
  source_line_id: string;
  item: string;
  name: string;
  qty: string;
  source_price: Money;
  price: Money | null;
  amount: Money | null;
  deviation_pct: string | null;
}

export interface OfferCard {
  id: string;
  number: string;
  version: number;
  status: string;
  status_label: string;
  source: OfferSourceBrief;
  project: { id: string; code: string | null; name: string | null } | null;
  article: { id: string; code: string | null; name: string | null } | null;
  author_id: number;
  author_name: string | null;
  author_role: string;
  own_document: boolean;
  counterparty_id: string | null;
  counterparty: CounterpartyBrief | null;
  currency_code: string;
  rate: string | null;
  amount: Money | null;
  amount_kzt: Money | null;
  with_vat: boolean;
  vat_rate: string | null;
  vat_source: string;
  vat_amount: Money | null;
  source_amount_kzt: Money | null;
  saving_amount: Money | null;
  saving_pct: string | null;
  more_expensive: boolean;
  delivery_date: string | null;
  payment_terms: string;
  payment_terms_note: string;
  justification: string;
  submitted_at: string | null;
  decided_at: string | null;
  decision_comment: string;
  closed_reason: string;
  lines: OfferLine[];
  allowed_actions: string[];
}

export interface OfferPatch {
  version: number;
  counterparty_id?: string | null;
  currency_code?: string;
  delivery_date?: string | null;
  payment_terms?: string;
  payment_terms_note?: string;
  justification?: string;
  with_vat?: boolean;
  lines?: { source_line_id: string; price: string | null }[];
}

// ── лента L-09 ──────────────────────────────────────────────────────────

export interface FeedRow {
  /** Ключ строки для реестра = `source_id` (у ленты своего `id` нет). */
  id: string;
  source_type: SourceType;
  source_id: string;
  number: string;
  kind_label: string;
  url: string;
  author_id: number | null;
  author_name: string | null;
  project: { id: string; code: string | null; name: string | null };
  article: { id: string; code: string | null; name: string | null };
  counterparty: { id: string; name: string; reg_number: string } | null;
  positions: { names: string[]; more: number; count: number };
  amount: Money | null;
  currency_code: string;
  sent_at: string | null;
  offers_count: number;
  alt_limit: number;
  my_offer: { id: string; number: string; status: string; status_label: string } | null;
}

/** Ответ ленты без ключа строки → строки реестра. */
export const feedRows = (raw: unknown[]): FeedRow[] =>
  (raw as Omit<FeedRow, 'id'>[]).map((row) => ({ ...row, id: row.source_id }));

/** Отбор ссылкой уведомления: `?source=<invoice|agreement>:<id>`. */
export function parseSource(value: string | null): { type: SourceType; id: string } | null {
  if (!value) return null;
  const [type, id] = value.split(':');
  return (type === 'invoice' || type === 'agreement') && id ? { type, id } : null;
}

/** Адрес ленты: отбор ссылкой (`source`) и фильтры страницы (`project_id`/`article_id`
 * повторяемые, `author_id`, `counterparty_id`) — строкой запроса; остальное добавит реестр. */
export function feedEndpoint(source: string | null, extra?: URLSearchParams): string {
  const query = new URLSearchParams();
  if (source) query.set('source', source);
  extra?.forEach((value, key) => query.append(key, value));
  const text = query.toString();
  return text ? `${ALTERNATIVES_FEED_ENDPOINT}?${text}` : ALTERNATIVES_FEED_ENDPOINT;
}

export const FEED_PAGE_FILTERS = ['project_id', 'article_id', 'author_id', 'counterparty_id'] as const;

// ── сравнение ───────────────────────────────────────────────────────────

export interface ComparisonCounterparty extends CounterpartyBrief {
  country_name?: string | null;
}

export interface ComparisonColumnBase {
  id: string;
  number: string;
  status: string;
  status_label: string;
  counterparty: ComparisonCounterparty | null;
  currency_code: string;
  amount: Money | null;
  amount_kzt: Money | null;
  with_vat: boolean;
  vat_rate: string | null;
  vat_amount: Money | null;
  delivery_date: string | null;
  url: string;
}

export interface ComparisonSource extends ComparisonColumnBase {
  kind: 'source';
  source_type: SourceType;
  payment_terms: null;
  author: { id: number; name: string | null };
}

export interface ComparisonOffer extends ComparisonColumnBase {
  kind: 'offer';
  version: number;
  source_amount_kzt: Money | null;
  saving: { amount: Money | null; pct: string | null; more_expensive: boolean };
  payment_terms: string;
  payment_terms_note: string;
  justification: string;
  files: { id?: string; filename?: string }[];
  author: { id: number; name: string | null; role: string };
  own_document: boolean;
  submitted_at: string | null;
}

export interface ComparisonPosition {
  source_line_id: string;
  item: string;
  name: string;
  uom: string | null;
  qty: string;
  source_price: Money;
  source_amount: Money;
  offers: Record<string, { price: Money | null; amount: Money | null; deviation_pct: string | null }>;
}

export interface Comparison {
  source: ComparisonSource;
  offers: ComparisonOffer[];
  positions: ComparisonPosition[];
  limit: number;
  submitted_count: number;
  window_open: boolean;
  can_propose: boolean;
  propose_blocked_reason: string | null;
  my_offer_id: string | null;
}

// ── запросы ─────────────────────────────────────────────────────────────

const path = (suffix = '') => apiPath('bpp', suffix ? `alternatives/${suffix}` : 'alternatives');
const withKey = (key: string) => ({ headers: { 'Idempotency-Key': key } });

export const alternativesApi = {
  get: (id: string) => api.get<OfferCard>(path(`offers/${id}`)).then((r) => r.data),
  create: (key: string, sourceType: SourceType, sourceId: string) =>
    api.post<OfferCard>(path('offers'), { source_type: sourceType, source_id: sourceId },
      withKey(key)).then((r) => r.data),
  save: (id: string, key: string, body: OfferPatch) =>
    api.patch<OfferCard>(path(`offers/${id}`), body, withKey(key)).then((r) => r.data),
  remove: (id: string, key: string, version: number) =>
    api.delete(path(`offers/${id}`), { ...withKey(key), params: { version } })
      .then(() => undefined),
  submit: (id: string, key: string, version: number) =>
    api.post<OfferCard>(path(`offers/${id}/submit`), { version }, withKey(key))
      .then((r) => r.data),
  withdraw: (id: string, key: string, version: number) =>
    api.post<OfferCard>(path(`offers/${id}/withdraw`), { version }, withKey(key))
      .then((r) => r.data),
  comparison: (type: SourceType, id: string) =>
    api.get<Comparison>(path(`sources/${type}/${id}/comparison`)).then((r) => r.data),
  setLimit: (type: SourceType, id: string, key: string, limit: number) =>
    api.post<{ source_type: SourceType; source_id: string; alt_limit: number }>(
      path(`sources/${type}/${id}/limit`), { limit }, withKey(key)).then((r) => r.data),
};
