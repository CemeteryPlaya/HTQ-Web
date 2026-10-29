/**
 * Клиент заявки на тендер (`/api/tender/v1/requests`, план этапов 0–2 §3.4).
 *
 * Деньги и количества — строками (Decimal на сервере). Правка, удаление и
 * переходы несут `version` карточки (отказ 409 `E-CON-01` — карточку уже
 * изменили) и `Idempotency-Key` кнопки. Ошибки — в конверте модуля
 * `{detail, code, fields}`, код читает `lib/apiError::errorCode`.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

/** Деньги и количества приходят строкой (Decimal на сервере). */
export type Money = string;

export type InitiatorRole = 'sn' | 'pm';
export type PurchaseType = 'goods' | 'works';
export type PartKind = 'goods' | 'delivery' | 'works';

export type TenderRequestStatus =
  | 'draft' | 'in_approval' | 'approved' | 'rework' | 'rejected'
  | 'in_tender' | 'handed_over' | 'closed' | 'cancelled';

/** Действия карточки, которые сервер разрешил пользователю сейчас. */
export type TenderRequestAction = 'save' | 'submit' | 'withdraw' | 'cancel' | 'delete' | 'exclude';

export const TENDER_REQUESTS_BASE = '/tender/requests';
export const tenderRequestHref = (id: string) => `${TENDER_REQUESTS_BASE}/${id}`;
/** Заявка на закупку БЗО, в которую ушла часть (`features/bpp`, подмодуль `links`). */
export const bppRequestHref = (id: string) => `/bpp/requests/${id}`;

export const tenderRequestKeys = {
  all: ['tender', 'requests'] as const,
  list: (params: RequestListParams) => ['tender', 'requests', 'list', params] as const,
  card: (id: string) => ['tender', 'requests', 'card', id] as const,
  budget: (projectId: string, articleId: string, role: string) =>
    ['tender', 'requests', 'budget', projectId, articleId, role] as const,
  articles: (projectId: string, role: string) =>
    ['tender', 'requests', 'articles', projectId, role] as const,
  projects: (q: string, role: string) => ['tender', 'requests', 'projects', q, role] as const,
};

export interface TenderRequestItem {
  id: string;
  line_no: number;
  name: string;
  specs: string;
  uom_id: string;
  qty: string;
  plan_price: Money;
  need_date: string;
  /** `null` — позиция идёт по статье заявки. */
  article_id: string | null;
}

/** Часть заявки — заявка на закупку БЗО (ЗЗ) по одной статье (план §3.2). */
export interface TenderRequestPart {
  id: string;
  kind: PartKind;
  article_id: string | null;
  purchase_type: PurchaseType;
  bpp_request_id: string | null;
  bpp_number: string;
  bpp_status: string;
  excluded_at: string | null;
}

export interface TenderRequestCard {
  id: string;
  number: string;
  status: TenderRequestStatus | string;
  /** Подпись статуса сервера; интерфейс берёт свою из словаря. */
  status_display?: string;
  author_id?: number;
  author_name?: string;
  created_at?: string | null;
  updated_at?: string | null;
  initiator_role: InitiatorRole;
  project_id: string;
  /** Проект — в карточке (`project.interface`); `null`, если сервер его не нашёл. */
  project?: { id: string; code: string; name: string } | null;
  article_id: string | null;
  purchase_type: PurchaseType;
  need_date: string | null;
  delivery_address: string;
  justification: string;
  needs_delivery: boolean;
  delivery_article_id: string | null;
  delivery_plan_amount: Money | null;
  needs_works: boolean;
  works_scope: string;
  works_article_id: string | null;
  works_plan_amount: Money | null;
  allow_analogs: boolean;
  allow_partial: boolean;
  rework_comment: string;
  status_comment: string;
  version: number;
  allowed_actions: (TenderRequestAction | string)[];
  items: TenderRequestItem[];
  parts: TenderRequestPart[];
}

/** Строка реестра (`{results, total, page, page_size}`). */
export interface TenderRequestRow {
  id: string;
  number: string;
  status: string;
  status_display?: string;
  project_id: string;
  project_code?: string;
  project_name?: string;
  purchase_type?: PurchaseType;
  need_date?: string | null;
  created_at?: string | null;
  author_id?: number;
  author_name?: string | null;
}

export interface RequestListParams {
  status?: string;
  project_id?: string;
  q?: string;
}

export interface TenderRequestItemInput {
  /** Ключ позиции с сервера — правка на месте (её часть и позиция ЗЗ
   * сохраняются); `null` — новая позиция. Не названные строки сервер удаляет. */
  id: string | null;
  name: string;
  specs: string;
  uom_id: string | null;
  qty: string | null;
  plan_price: Money | null;
  need_date: string | null;
  article_id: string | null;
}

export interface TenderRequestInput {
  initiator_role: InitiatorRole | null;
  project_id: string | null;
  article_id: string | null;
  purchase_type: PurchaseType;
  need_date: string | null;
  delivery_address: string;
  justification: string;
  needs_delivery: boolean;
  delivery_article_id: string | null;
  delivery_plan_amount: Money | null;
  needs_works: boolean;
  works_scope: string;
  works_article_id: string | null;
  works_plan_amount: Money | null;
  allow_analogs: boolean;
  allow_partial: boolean;
  items: TenderRequestItemInput[];
}

/** Остаток статьи бюджета проекта (`bpp.budget_available`). */
export interface ArticleBudget {
  limit: Money;
  committed: Money;
  available: Money;
  currency_code: string;
}

/** Статья, доступная роли в бюджете проекта (`bpp.budget_articles`). */
export interface RequestArticle {
  id: string;
  code: string;
  name: string;
  group_code: string;
  available: Money;
}

export interface RequestProject {
  id: string;
  code: string;
  name: string;
}

/** Реестр отдаёт список или страницу `{results}` — читаем оба вида. */
function rowsOf(data: unknown): TenderRequestRow[] {
  if (Array.isArray(data)) return data as TenderRequestRow[];
  const page = data as { results?: unknown; items?: unknown } | null;
  if (Array.isArray(page?.results)) return page.results as TenderRequestRow[];
  if (Array.isArray(page?.items)) return page.items as TenderRequestRow[];
  return [];
}

const path = (suffix = '') => apiPath('tender', suffix ? `requests/${suffix}` : 'requests');
const withKey = (key: string) => ({ headers: { 'Idempotency-Key': key } });
/** Пустые фильтры не отправляются — сервер понял бы `?status=` как «статус пустой». */
const compact = (params: object) =>
  Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== ''));

export const tenderRequestsApi = {
  list: (params: RequestListParams = {}) =>
    api.get<unknown>(path(), { params: compact(params) }).then((r) => rowsOf(r.data)),
  get: (id: string) => api.get<TenderRequestCard>(path(id)).then((r) => r.data),
  create: (key: string, body: TenderRequestInput) =>
    api.post<TenderRequestCard>(path(), body, withKey(key)).then((r) => r.data),
  save: (id: string, key: string, body: TenderRequestInput & { version: number }) =>
    api.patch<TenderRequestCard>(path(id), body, withKey(key)).then((r) => r.data),
  remove: (id: string, key: string, version: number) =>
    api.delete(path(id), { ...withKey(key), params: { version } }).then(() => undefined),
  submit: (id: string, key: string, version: number) =>
    api.post<TenderRequestCard>(path(`${id}/submit`), { version }, withKey(key)).then((r) => r.data),
  withdraw: (id: string, key: string, version: number) =>
    api.post<TenderRequestCard>(path(`${id}/withdraw`), { version }, withKey(key)).then((r) => r.data),
  cancel: (id: string, key: string, version: number, comment: string) =>
    api.post<TenderRequestCard>(path(`${id}/cancel`), { version, comment }, withKey(key))
      .then((r) => r.data),
  excludePart: (id: string, partId: string, key: string, version: number) =>
    api.post<TenderRequestCard>(path(`${id}/parts/${partId}/exclude`), { version }, withKey(key))
      .then((r) => r.data),
  /** Остаток — в роли заявки: у пользователя с двумя ролями без неё E-REQ-01. */
  budget: (projectId: string, articleId: string, role: InitiatorRole) =>
    api.get<ArticleBudget>(path('budget'), {
      params: { project_id: projectId, article_id: articleId, role },
    }).then((r) => r.data),
  articles: (projectId: string, role: InitiatorRole) =>
    api.get<RequestArticle[]>(path('articles'), { params: { project_id: projectId, role } })
      .then((r) => r.data),
  /** Не больше 20 действующих проектов по `q`; ПМ (роль `pm`) — только участия. */
  projects: (q = '', role: InitiatorRole | '' = '') =>
    api.get<RequestProject[]>(path('projects'), { params: compact({ q, role }) }).then((r) => r.data),
};
