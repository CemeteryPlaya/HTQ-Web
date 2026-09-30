/**
 * Клиент дашборда D-01 «Оплаты» (`GET /api/bpp/v1/dashboard/payments`; ТЗ
 * §11.5, REQ-018; сервер — `apps/bpp/views_dashboard.py`,
 * `services/dashboard/payments.py`).
 *
 * - Фильтры — период по дате платежа в выписке (`period_from`/`period_to`),
 *   проект, статья, контрагент (UUID) и автор счёта (`author_id`, целое).
 *   Экран держит их в адресе страницы: «Назад» из реестра по ссылке
 *   показателя возвращает тот же отбор.
 * - Деньги — строки-десятичные (`Decimal(18,2)`), в KZT; на экран — только
 *   через `formatMoney`.
 * - `link` показателя — адрес реестра счетов фронта с теми же фильтрами
 *   (`/bpp/invoices?…`), сервер собирает его сам: число на карточке и
 *   `total` реестра по ссылке совпадают. У «Несопоставленных списаний» —
 *   реестр загрузок выписок с тем же периодом (`/bpp/bank?period_from=…`),
 *   без права `bpp.bank` view — `null`.
 * - `sections` — включены ли у компании подмодули счетов, банка и бюджетов:
 *   экран пишет «подмодуль выключен», а не «данных нет».
 * - `authors` — список фильтра «Автор счёта»: авторы счетов, видимых
 *   пользователю по правилам реестра. Кадровый список сотрудников не годится
 *   — у ролей дашборда нет прав `hr`.
 * - Кеша нет: ТЗ требует свежих цифр при каждом открытии и после каждой
 *   загрузки выписки. Экраны сверки после загрузки и своих действий
 *   сбрасывают `DASHBOARD_KEY`.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

export type Money = string;

export const DASHBOARD_BASE = '/bpp/dashboard';
export const PAYMENTS_DASHBOARD_ENDPOINT = apiPath('bpp', 'dashboard/payments');

/** Фильтры дашборда; пустая строка — фильтр не задан. */
export interface DashboardFilters {
  period_from: string;
  period_to: string;
  project_id: string;
  article_id: string;
  counterparty_id: string;
  author_id: string;
}

export const FILTER_KEYS = [
  'period_from', 'period_to', 'project_id', 'article_id', 'counterparty_id', 'author_id',
] as const satisfies readonly (keyof DashboardFilters)[];

export const EMPTY_FILTERS: DashboardFilters = {
  period_from: '', period_to: '', project_id: '', article_id: '', counterparty_id: '', author_id: '',
};

/** Показатель (карточка): `key` — `fd`, `to_pay`, `awaiting_docs`,
 * `bank_unconfirmed`, `full`, `underpaid`, `overpaid`, `no_mark`,
 * `unmatched`. Показатели выключенного у компании подмодуля не приходят. */
export interface DashboardIndicator {
  key: string;
  label: string;
  count: number;
  /** Сумма в KZT. */
  amount: Money;
  link: string | null;
}

/** Статья действующей версии бюджета проекта. */
export interface ArticleChartRow {
  article_id: string;
  code: string | null;
  name: string;
  limit: Money;
  committed: Money;
  /** «Оплачено факт» (CALC-007); `null` — у компании выключен `bpp_bank`. */
  paid_fact: Money | null;
}

export interface WeeklyPaidRow {
  /** Понедельник недели, `ГГГГ-ММ-ДД`. */
  week_start: string;
  amount: Money;
}

export interface TopCounterpartyRow {
  counterparty_id: string;
  name: string;
  amount: Money;
}

/** Включены ли у компании подмодули (`bpp_invoices`, `bpp_bank`, `bpp_budget`). */
export interface DashboardSections {
  invoices: boolean;
  bank: boolean;
  budget: boolean;
}

/** Автор счёта для фильтра; `name: null` — учётки пользователя нет. */
export interface DashboardAuthor {
  id: number;
  name: string | null;
}

export interface PaymentsDashboard {
  filters: Record<string, string | number | null>;
  sections: DashboardSections;
  authors: DashboardAuthor[];
  indicators: DashboardIndicator[];
  article_chart: ArticleChartRow[];
  weekly_paid: WeeklyPaidRow[];
  top_counterparties: TopCounterpartyRow[];
  as_of: string;
}

/** Фильтры из адреса страницы: неизвестные параметры не берутся. */
export function filtersFromSearch(params: URLSearchParams): DashboardFilters {
  const out = { ...EMPTY_FILTERS };
  for (const key of FILTER_KEYS) out[key] = params.get(key) ?? '';
  return out;
}

/** Только заданные фильтры — параметры запроса. */
export function filterParams(filters: DashboardFilters): Record<string, string> {
  return Object.fromEntries(FILTER_KEYS.filter((key) => filters[key]).map((key) => [key, filters[key]]));
}

/** Ключ всех дашбордов модуля — его сбрасывают экраны сверки. */
export const DASHBOARD_KEY = ['bpp', 'dashboard'] as const;

export const dashboardKeys = {
  all: DASHBOARD_KEY,
  payments: (filters: DashboardFilters) => [...DASHBOARD_KEY, 'payments', filterParams(filters)] as const,
};

export const dashboardApi = {
  payments: (filters: DashboardFilters) =>
    api.get<PaymentsDashboard>(PAYMENTS_DASHBOARD_ENDPOINT, { params: filterParams(filters) })
      .then((r) => r.data),
};
