/**
 * Клиент тендера и его участников (`/api/tender/v1/tenders`, `counterparties`,
 * `contacts`; план этапов 0–2 §4.3).
 *
 * Ссылка участника (`link`) приходит ТОЛЬКО в ответах публикации,
 * перевыпуска и приглашения после публикации: сервер хранит лишь хэш
 * токена, и второй раз ту же ссылку не отдаст. Поэтому ссылки не кладутся
 * в кэш react-query — их показывает диалог, пока он открыт.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

export type TenderStatus =
  | 'draft' | 'intake' | 'opened' | 'on_approval' | 'awarded' | 'handed_over' | 'delivery'
  | 'closed' | 'cancelled' | 'failed' | 'rework';

export type TenderAction = 'edit' | 'publish' | 'extend' | 'cancel' | 'invite';
export type SchemeKind = 'prepay' | 'advance' | 'postpay';

export const TENDERS_BASE = '/tender/tenders';
export const tenderHref = (id: string) => `${TENDERS_BASE}/${id}`;

export interface PaymentStage {
  order: number;
  trigger: string;
  pct: string;
  days: number | null;
}

export interface PaymentScheme {
  kind: SchemeKind | string;
  stages: PaymentStage[];
  postpay_days: number | null;
}

export interface Invitation {
  id: string;
  counterparty_id: string | null;
  prospect_id: string | null;
  name: string;
  email: string;
  status: string;
  sent_at: string | null;
  first_opened_at: string | null;
  revoked_at: string | null;
  max_devices: number;
  /** Что автор может сделать с приглашением сейчас — решает сервер (T3.7). */
  allowed_actions: InvitationAction[];
}

export type InvitationAction = 'revoke' | 'reissue' | 'reset_device';

export interface TenderCounters {
  sent: number;
  opened: number;
  submitted: number;
}

export interface TenderCard {
  id: string;
  number: string;
  status: TenderStatus | string;
  status_display?: string;
  request_id: string;
  request_number: string;
  request_status?: string;
  author_id?: number;
  opened_at?: string | null;
  created_at?: string | null;
  deadline_at: string | null;
  currency_code: string;
  delivery_terms: string;
  quality_reviewer_user_id: number | null;
  /** Имя проверяющего, если сервер его отдаёт (иначе — «пользователь №»). */
  quality_reviewer_name?: string | null;
  cancel_reason: string;
  round: number;
  version: number;
  allowed_actions: (TenderAction | string)[];
  payment_scheme: PaymentScheme | null;
  counters: TenderCounters;
  invitations: Invitation[];
}

/** Строка реестра (`{results, total, page, page_size}`). */
export interface TenderRow {
  id: string;
  number: string;
  status: string;
  status_display?: string;
  author_id?: number;
  created_at?: string | null;
  request_id: string;
  request_number: string;
  deadline_at: string | null;
  counters?: TenderCounters;
}

/** Правка шапки: только изменённые поля — сервер проверяет каждое
 * переданное (срок «в будущем», валюта ISO, роль проверяющего). */
export interface TenderPatch {
  deadline_at?: string | null;
  currency_code?: string;
  delivery_terms?: string;
  quality_reviewer_user_id?: number | null;
  version: number;
}

export interface SchemeInput {
  kind: SchemeKind;
  advance_pct?: string;
  postpay_days?: number;
}

export interface IssuedLink {
  invitation_id: string;
  link: string;
}

/** Карточка контрагента БЗО из поиска (`bpp.search_counterparties`). */
export interface Counterparty {
  id: string;
  name: string;
  short_name: string;
  reg_number: string;
  country_code: string;
  status: string;
  email: string;
  contact_person: string;
  phone: string;
}

export interface SupplierContact {
  id: string;
  counterparty_id: string;
  email: string;
  name: string;
  phone: string;
  is_primary: boolean;
  is_active: boolean;
}

export type InvitationInput =
  | { counterparty_id: string; contact_id?: string }
  | { prospect_id: string };

export const tenderKeys = {
  all: ['tender', 'tenders'] as const,
  list: (params: object) => ['tender', 'tenders', 'list', params] as const,
  card: (id: string) => ['tender', 'tenders', 'card', id] as const,
  counterparties: (q: string) => ['tender', 'counterparties', q] as const,
  contacts: (counterpartyId: string) => ['tender', 'contacts', counterpartyId] as const,
};

/** Реестр отдаёт список или страницу `{results}` — читаем оба вида. */
export function rowsOf<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  const page = data as { results?: unknown; items?: unknown } | null;
  if (Array.isArray(page?.results)) return page.results as T[];
  if (Array.isArray(page?.items)) return page.items as T[];
  return [];
}

/** Пустые фильтры не отправляются. */
export const compactParams = (params: object) =>
  Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== ''));

const path = (suffix = '') => apiPath('tender', suffix ? `tenders/${suffix}` : 'tenders');
const withKey = (key: string) => ({ headers: { 'Idempotency-Key': key } });

export const tendersApi = {
  list: (params: { status?: string; q?: string } = {}) =>
    api.get<unknown>(path(), { params: compactParams(params) }).then((r) => rowsOf<TenderRow>(r.data)),
  get: (id: string) => api.get<TenderCard>(path(id)).then((r) => r.data),
  create: (key: string, requestId: string) =>
    api.post<TenderCard>(path(), { request_id: requestId }, withKey(key)).then((r) => r.data),
  save: (id: string, body: TenderPatch) => api.patch<TenderCard>(path(id), body).then((r) => r.data),
  setScheme: (id: string, body: SchemeInput) =>
    api.put<TenderCard>(path(`${id}/payment-scheme`), body).then((r) => r.data),
  publish: (id: string, key: string, version: number) =>
    api.post<{ links?: IssuedLink[] }>(path(`${id}/publish`), { version }, withKey(key))
      .then((r) => r.data?.links ?? []),
  extend: (id: string, key: string, deadlineAt: string, version: number) =>
    api.post<TenderCard>(path(`${id}/extend`), { deadline_at: deadlineAt, version }, withKey(key))
      .then((r) => r.data),
  cancel: (id: string, key: string, reason: string, version: number) =>
    api.post<TenderCard>(path(`${id}/cancel`), { reason, version }, withKey(key)).then((r) => r.data),
  invite: (id: string, key: string, body: InvitationInput) =>
    api.post<Invitation & { link?: string }>(path(`${id}/invitations`), body, withKey(key))
      .then((r) => r.data),
  revoke: (id: string, invitationId: string, key: string) =>
    api.post(path(`${id}/invitations/${invitationId}/revoke`), {}, withKey(key)).then(() => undefined),
  reissue: (id: string, invitationId: string, key: string) =>
    api.post<{ link: string }>(path(`${id}/invitations/${invitationId}/reissue`), {}, withKey(key))
      .then((r) => r.data.link),
  resetDevice: (id: string, invitationId: string, key: string) =>
    api.post(path(`${id}/invitations/${invitationId}/reset-device`), {}, withKey(key))
      .then(() => undefined),
  counterparties: (q: string) =>
    api.get<unknown>(apiPath('tender', 'counterparties'), { params: compactParams({ q }) })
      .then((r) => rowsOf<Counterparty>(r.data)),
  contacts: (counterpartyId: string) =>
    api.get<unknown>(apiPath('tender', 'contacts'), { params: { counterparty_id: counterpartyId } })
      .then((r) => rowsOf<SupplierContact>(r.data)),
};
