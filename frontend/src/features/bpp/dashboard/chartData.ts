/**
 * Строки графиков дашборда «Оплаты» из ответа сервера.
 *
 * recharts рисует по числам, поэтому у каждой суммы две формы:
 * - число (`limit`, `amount`, …) — только для геометрии столбца или точки
 *   линии; погрешность `Number` на высоте столбца не видна;
 * - подпись (`limitText`, `amountText`, …) — `formatMoney` над исходной
 *   строкой-десятичной сервера, без `float`: всплывающая подсказка и
 *   таблица показывают ровно ту сумму, что посчитал сервер.
 */
import { formatDate, formatMoney } from '../format';

import type { ArticleChartRow, WeeklyPaidRow } from './api';

/** Ряды столбцов по статьям; подпись ряда — ключ + `Text`. */
export const ARTICLE_SERIES = ['limit', 'committed', 'paid_fact'] as const;
export type ArticleSeries = (typeof ARTICLE_SERIES)[number];

export interface ArticleBar {
  article_id: string;
  name: string;
  limit: number;
  limitText: string;
  committed: number;
  committedText: string;
  /** `null` — «Оплачено факт» не считали (у компании выключен `bpp_bank`). */
  paid_fact: number | null;
  paid_factText: string | null;
}

export interface WeekPoint {
  week_start: string;
  /** Подпись оси — `ДД.ММ.ГГГГ` понедельника. */
  week: string;
  amount: number;
  amountText: string;
}

/** Высота столбца — только геометрия, подписи из строки. */
const plotValue = (value: string): number => {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
};

export const articleBars = (rows: ArticleChartRow[]): ArticleBar[] => rows.map((row) => ({
  article_id: row.article_id,
  name: row.code ? `${row.code} ${row.name}` : row.name,
  limit: plotValue(row.limit),
  limitText: formatMoney(row.limit),
  committed: plotValue(row.committed),
  committedText: formatMoney(row.committed),
  paid_fact: row.paid_fact === null ? null : plotValue(row.paid_fact),
  paid_factText: row.paid_fact === null ? null : formatMoney(row.paid_fact),
}));

export const weekPoints = (rows: WeeklyPaidRow[]): WeekPoint[] => rows.map((row) => ({
  week_start: row.week_start,
  week: formatDate(row.week_start),
  amount: plotValue(row.amount),
  amountText: formatMoney(row.amount),
}));

/** Подпись значения для всплывающей подсказки recharts: поле `<ряд>Text`
 * строки данных, а не число, которое recharts передаёт первым аргументом.
 * Валюта — только там, где сервер обещает одну: «Оплачено по банку» — в KZT,
 * а «Лимит / Задействовано / Оплачено факт» по статьям — в валюте счетов
 * (как CALC-002), и подпись «KZT» у них была бы неправдой. */
export function tooltipText(dataKey: unknown, payload: unknown, currency?: string): string {
  const row = (payload ?? {}) as Record<string, unknown>;
  const text = row[`${String(dataKey)}Text`];
  if (typeof text !== 'string') return '—';
  return currency ? `${text} ${currency}` : text;
}

/** Подпись деления оси: деления строит recharts, это не суммы сервера. */
export const axisTick = (value: number): string => formatMoney(String(value)).replace(/,00$/, '');
