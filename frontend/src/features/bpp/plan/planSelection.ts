/**
 * Правила выбора позиций плана (ТЗ §8.3) и количества мастера F-03 (§8.4
 * шаг 2) — отдельно от экрана.
 */
import { parseQtyInput } from '../requests/requestForm';

import type { PlanItem } from './api';

/** Подсказка, почему «Оформить договор / счёт» недоступны; `null` — можно. */
export function selectionProblem(selected: PlanItem[]): string | null {
  if (selected.length === 0) return 'Отметьте позиции для документа';
  const pairs = new Set(selected.map((item) => `${item.project_id}|${item.article_id ?? ''}`));
  if (pairs.size > 1) return 'Для одного документа выберите позиции одного проекта и одной статьи';
  return null;
}

/** Тысячные количества (`"2.500"` → 2500n); не число — `null`. */
const milli = (text: string): bigint | null => {
  const parsed = parseQtyInput(text);
  return parsed === null ? null : BigInt(parsed.replace('.', ''));
};

/** Количество в мастере: больше нуля и не больше «Остатка кол-во» (§8.4 шаг 2). */
export function qtyProblem(entered: string, left: string): string | null {
  const value = milli(entered);
  const limit = milli(left.replace('.', ','));
  if (value === null || value <= 0n) return 'Количество — больше нуля';
  if (limit !== null && value > limit) return `Не больше остатка ${shownQty(left)}`;
  return null;
}

/**
 * Сумма под выбранное количество: остаток суммы позиции × кол-во / остаток
 * кол-ва, до копейки по правилу «половина — вверх» (как CALC-004), без
 * `float`. Всё количество — весь остаток суммы как есть.
 */
export function proportionalAmount(amountLeft: string, qty: string, qtyLeft: string): string {
  const q = milli(qty) ?? 0n;
  const left = milli(qtyLeft.replace('.', ',')) ?? 0n;
  const cents = BigInt(amountLeft.replace('.', ''));
  if (left <= 0n || q >= left) return amountLeft;
  const value = (cents * q * 2n + left) / (left * 2n);
  const text = value.toString().padStart(3, '0');
  return `${text.slice(0, -2)}.${text.slice(-2)}`;
}

/** `"10.000"` → `"10"`, `"2.500"` → `"2,5"`; целое без точки — как есть. */
export const shownQty = (value: string) =>
  (value.includes('.') ? value.replace(/\.?0+$/, '') : value).replace('.', ',');
