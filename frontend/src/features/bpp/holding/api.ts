/**
 * Клиент «Сводки группы по БЗО» (`GET /api/bpp/v1/holding/summary`; сервер —
 * `apps/bpp/views_holding.py`, `services/holding/summary.py`, A8.1).
 *
 * Ручка открыта только на поддомене холдинга и только держателям узла
 * `bpp.holding` (ФД, ГД): 403 — нет узла или не тот поддомен, 503 — сводные
 * представления пересобираются. Суммы — строки-десятичные (KZT), на экран —
 * только через `formatMoney`.
 */
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

export type Money = string;

export interface CountAmount {
  count: number;
  amount_kzt: Money;
}

export interface BppHoldingRow {
  company_slug: string;
  company_name: string;
  budgets: number;
  budgets_other_currency: number;
  limit_kzt: Money;
  invoices_to_pay: CountAmount;
  invoices_paid: CountAmount;
  agreements_active: number;
}

export interface BppHoldingSummary {
  companies: BppHoldingRow[];
  totals: {
    budgets: number;
    limit_kzt: Money;
    invoices_to_pay: CountAmount;
    invoices_paid: CountAmount;
    agreements_active: number;
  };
}

export const bppHoldingApi = {
  summary: () => api.get<BppHoldingSummary>(apiPath('bpp', 'holding/summary')),
};
