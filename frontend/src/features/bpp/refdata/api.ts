/**
 * Клиент справочников модуля БЗО (`/api/refdata/v1/*`, задача 9, A2.4).
 *
 * Ответы — голые списки (без обёртки `{items,...}`): справочники группы
 * малы (десятки-сотни строк), и сервер не пагинирует их
 * (`apps/refdata/views.py::_collection`). Поэтому здесь — простые
 * CRUD-клиенты, а не `BppRegistry`/`useRegistryState` (тем реестрам нужен
 * конверт `{items,total,page,page_size}`, которого у справочников нет).
 *
 * Каждая строка несёт `can_edit` — сервер решает, годится ли компания
 * запроса для правки (D-03: правит только управляющая компания); фронт по
 * этому полю показывает или прячет кнопки, а не гадает по роли сам.
 *
 * У курсов валют, ставок НДС и МРП нет ни правки, ни архива — это
 * периодические значения, к которым добавляют новую запись на дату, а не
 * правят старую (`apps/refdata/urls.py`: `rates`/`vat`/`mrp` — только
 * `GET`/`POST`).
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

const path = (suffix: string) => apiPath('refdata', suffix);

export interface RefRow {
  id: string;
  can_edit: boolean;
  is_active?: boolean;
}

export interface Country extends RefRow {
  code: string;
  name: string;
  is_active: boolean;
}

export interface Currency extends RefRow {
  code: string;
  name: string;
  symbol: string;
  is_active: boolean;
}

export interface ExchangeRate extends RefRow {
  currency_code: string;
  on_date: string;
  rate: string;
  source: 'nbrk' | 'manual';
}

export interface VatRate extends RefRow {
  country_code: string;
  rate: string;
  date_from: string;
  date_to: string | null;
}

export interface MrpValue extends RefRow {
  date_from: string;
  value: string;
}

export interface Uom extends RefRow {
  code: string;
  short_name: string;
  name: string;
  is_active: boolean;
}

export interface ArticleGroup extends RefRow {
  code: string;
  name: string;
  node_key: string;
  is_active: boolean;
}

export interface Article extends RefRow {
  code: string;
  name: string;
  group_id: string;
  parent_id: string | null;
  is_active: boolean;
  ext_1c_ref: string;
}

/**
 * Параметры списка. `active: true` — `?active=1`, без архивных записей: так
 * справочник читают ВЫБОРЫ в новых документах (архивная валюта или статья
 * не предлагается), а экран справочника читает всё, помечая архив меткой.
 * У курсов, НДС и МРП архива нет — сервер параметр там молча пропускает.
 */
export interface ListParams {
  active?: boolean;
}

const listQuery = (params?: ListParams) => (params?.active ? { active: '1' } : undefined);

function collection<Row, CreateBody extends object>(suffix: string) {
  return {
    list: (params?: ListParams) =>
      api.get<Row[]>(path(suffix), { params: listQuery(params) }).then((r) => r.data),
    create: (body: CreateBody) => api.post<Row>(path(suffix), body).then((r) => r.data),
  };
}

function item<Row, PatchBody extends object>(suffix: string) {
  return {
    patch: (id: string, body: PatchBody) =>
      api.patch<Row>(path(`${suffix}/${id}`), body).then((r) => r.data),
  };
}

export const refdataApi = {
  countries: {
    ...collection<Country, { code: string; name: string }>('countries'),
    ...item<Country, { name?: string; is_active?: boolean }>('countries'),
  },
  currencies: {
    ...collection<Currency, { code: string; name: string; symbol?: string }>('currencies'),
    ...item<Currency, { name?: string; symbol?: string; is_active?: boolean }>('currencies'),
  },
  rates: collection<ExchangeRate, { currency_code: string; on_date: string; rate: string }>(
    'rates',
  ),
  vat: collection<VatRate, {
    country_code: string; rate: string; date_from: string; date_to?: string | null;
  }>('vat'),
  mrp: collection<MrpValue, { date_from: string; value: string }>('mrp'),
  uoms: {
    ...collection<Uom, { code: string; short_name: string; name: string }>('uoms'),
    ...item<Uom, { short_name?: string; name?: string; is_active?: boolean }>('uoms'),
  },
  articleGroups: {
    ...collection<ArticleGroup, { code: string; name: string; node_key: string }>(
      'article-groups',
    ),
    ...item<ArticleGroup, { name?: string; is_active?: boolean }>('article-groups'),
  },
  articles: {
    ...collection<Article, {
      code: string; name: string; group_id: string; parent_id?: string | null;
      ext_1c_ref?: string;
    }>('articles'),
    ...item<Article, { name?: string; is_active?: boolean; ext_1c_ref?: string }>('articles'),
  },
};

/** Коллекции справочников — ключи `refdataApi`. */
export type RefdataCollection = keyof typeof refdataApi;

/**
 * Ключи react-query. Полный список (экран справочника) и список без архива
 * (выборы в документах) — разные ключи: это разные ответы сервера. Сброс
 * после правки — по префиксу `refdataKeys.collection(...)`, он задевает оба.
 */
export const refdataKeys = {
  all: ['bpp', 'refdata'] as const,
  collection: (name: RefdataCollection) => ['bpp', 'refdata', name] as const,
  list: (name: RefdataCollection, params?: ListParams) =>
    ['bpp', 'refdata', name, params?.active ? 'active' : 'all'] as const,
};
