/**
 * Клиент «Обзора» модуля (`GET /api/bpp/v1/overview`; сервер —
 * `apps/bpp/views_overview.py`, `services/overview.py`).
 *
 * - Блок приходит, только если у пользователя есть право просмотра его узла
 *   и у компании включён его подмодуль: нет права или рубильник выключен —
 *   нет ключа (не нули). Несколько ролей — объединение блоков.
 * - Числа сервер считает на выборках реестров: «свои» документы СН и ПМ,
 *   проекты-участия ПМ, группы статей — та же видимость, что в реестре, и
 *   очередь счетов совпадает с `total` реестра на своей вкладке (`?tab=`).
 * - Деньги (`budgets.projects`, `kpi.saving_confirmed`) — только при
 *   `shows_money` (право видеть счета): у АДМ — количества без сумм (ТЗ §17).
 *   Бюджеты — каждый проект отдельно: общей суммы по проектам нет.
 *   Суммы — строки-десятичные, на экран — только через `formatMoney`.
 * - Кеша нет: обзор открывают, чтобы увидеть текущие очереди.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

export const OVERVIEW_BASE = '/bpp/overview';
export const OVERVIEW_ENDPOINT = apiPath('bpp', 'overview');

export type Money = string;

/** Утверждённый бюджет одного проекта: итоги по строкам, видимым
 * пользователю (СН и ПМ — свои группы статей), в валюте бюджета. */
export interface BudgetProjectMoney {
  budget_id: string;
  project: { id: string; code: string | null; name: string | null };
  currency_code: string;
  limit_amount: Money;
  committed: Money;
  available: Money;
}

export interface OverviewBudgets {
  total: number;
  approved: number;
  draft: number;
  can_create: boolean;
  /** Каждый проект отдельно, по коду (суммы разных проектов не
   * складываются); только при `shows_money`. */
  projects?: BudgetProjectMoney[];
}

export interface OverviewApprovals {
  /** Задачи согласования документов модуля, ждущие решения пользователя. */
  pending: number;
}

export interface OverviewRequests {
  total: number;
  draft: number;
  in_approval: number;
  rework: number;
  approved: number;
  can_create: boolean;
}

export interface OverviewPlan {
  /** Позиции плана закупок, видимые пользователю. */
  open: number;
}

export interface OverviewAgreements {
  total: number;
  draft: number;
  on_review: number;
  rework: number;
  active: number;
}

/** Вкладки реестра счетов L-06, которые «Обзор» считает по правам. */
export type InvoiceTab = 'fd' | 'to_pay' | 'docs_provided' | 'awaiting_docs' | 'bank_unconfirmed';

export interface OverviewInvoices {
  total: number;
  draft: number;
  returned: number;
  /** Только вкладки, открытые правами: `fd` — ФД, `to_pay`/`docs_provided` —
   * БУХ, `awaiting_docs` — авторы счетов, `bank_unconfirmed` — с правом банка. */
  tabs: Partial<Record<InvoiceTab, number>>;
}

export interface OverviewAccountable {
  total: number;
  awaiting_report: number;
  can_create: boolean;
  /** Ждут бухгалтерию — только у БУХ (`bpp.accountable.payment`). */
  awaiting_accounting?: number;
}

export interface OverviewAlternatives {
  /** Документы, открытые для альтернатив (лента L-09). */
  feed: number;
  /** Поданные альтернативы, ждущие решения, — у ФД, ТД, ОД, ГД. */
  submitted?: number;
  /** Свои поданные альтернативы — у тех, кто может их подавать. */
  mine_submitted?: number;
}

export interface OverviewKpi {
  preliminary: number;
  confirmed: number;
  /** Подтверждённая экономия; только при `shows_money`. */
  saving_confirmed?: Money;
}

export interface OverviewAdmin {
  /** Документы модуля, чей этап согласования ждёт исполнителя. */
  no_executor: number;
  routes: boolean;
  settings: boolean;
  refdata: boolean;
  projects: boolean;
}

export interface Overview {
  shows_money: boolean;
  budgets?: OverviewBudgets;
  approvals?: OverviewApprovals;
  requests?: OverviewRequests;
  plan?: OverviewPlan;
  agreements?: OverviewAgreements;
  invoices?: OverviewInvoices;
  accountable?: OverviewAccountable;
  /** Есть ключ — открыт раздел «Оплаты факт»; чисел у него нет. */
  bank?: Record<string, never>;
  /** Есть ключ — открыт «Дашборд оплат»; чисел у него нет. */
  dashboard?: Record<string, never>;
  alternatives?: OverviewAlternatives;
  kpi?: OverviewKpi;
  admin?: OverviewAdmin;
}

/** Куда ведут карточки — пути пунктов меню подмодулей (тест страницы
 * сверяет их с маршрутами `bppModules`, чтобы переименование не оставило
 * ссылку в никуда). */
export const OVERVIEW_LINKS = {
  approvals: '/bpp/approvals',
  budgets: '/bpp/budgets',
  budgetNew: '/bpp/budgets/new',
  budget: '/bpp/budgets/:id',
  requests: '/bpp/requests',
  requestNew: '/bpp/requests/new',
  plan: '/bpp/plan',
  agreements: '/bpp/agreements',
  invoices: '/bpp/invoices',
  accountable: '/bpp/accountable',
  bank: '/bpp/bank',
  dashboard: '/bpp/dashboard',
  alternatives: '/bpp/alternatives',
  kpi: '/bpp/kpi',
  routes: '/bpp/routes',
  settings: '/bpp/settings',
  refdata: '/bpp/refdata',
  projects: '/bpp/projects',
} as const;

/** Карточка бюджета проекта (F-01). */
export const budgetHref = (id: string): string => OVERVIEW_LINKS.budget.replace(':id', id);

/** Вкладка реестра счетов: её `total` совпадает с числом «Обзора». */
export const invoiceTabHref = (tab: InvoiceTab): string => `${OVERVIEW_LINKS.invoices}?tab=${tab}`;

export const overviewKeys = {
  all: ['bpp', 'overview'] as const,
};

export const overviewApi = {
  get: () => api.get<Overview>(OVERVIEW_ENDPOINT).then((r) => r.data),
};
