/**
 * Состояние формы F-07 и расчёт «на лету» (ТЗ §12.3; CALC-013): чистые
 * функции, без React. Деньги — в тиынах (`bigint`), см. `money.ts`.
 *
 * - Позиция без галочки не входит ни в сумму АП, ни в запрос (набор `lines`
 *   PATCH — ровно отмеченные позиции).
 * - Исходная часть — Σ кол-во × исходная цена отмеченных позиций. Экономию
 *   «на лету» считаем, только когда валюта АП совпадает с валютой исходного
 *   документа и у каждой отмеченной позиции есть цена (как на сервере):
 *   иначе нужен курс, и числа показывает сервер после сохранения.
 */
import type { TFunction } from 'i18next';

import type { CounterpartyBrief } from '../agreements/api';
import { centsFromInput, fromCents, toCents } from '../bank/amounts';
import { formatMoney, parseMoneyInput } from '../format';

import type { OfferCard, OfferPatch } from './api';
import {
  deviationHundredths, formatPct, lineCents, saving, savingFromString, type Saving,
} from './money';

/** Короткое обоснование при удорожании (ТЗ §12.3, BR-…): 30 знаков. */
export const JUSTIFICATION_MIN = 10;
export const JUSTIFICATION_MORE_EXPENSIVE_MIN = 30;

export interface FormLine {
  source_line_id: string;
  item: string;
  name: string;
  qty: string;
  uom: string | null;
  source_price: string;
  included: boolean;
  /** Ввод человека («2 450,00»); пусто — цена ещё не введена. */
  price: string;
}

export interface OfferFormState {
  counterparty: CounterpartyBrief | null;
  currency_code: string;
  with_vat: boolean;
  delivery_date: string;
  payment_terms: string;
  payment_terms_note: string;
  justification: string;
  lines: FormLine[];
}

/** Позиция исходного документа из сравнения — полный набор для галочек. */
export interface SourcePosition {
  source_line_id: string;
  item: string;
  name: string;
  uom: string | null;
  qty: string;
  source_price: string;
}

const priceText = (price: string | null): string => (price === null ? '' : formatMoney(price));

export function formOf(card: OfferCard | undefined, positions: SourcePosition[] = []): OfferFormState {
  if (!card) {
    return {
      counterparty: null, currency_code: 'KZT', with_vat: false, delivery_date: '',
      payment_terms: '', payment_terms_note: '', justification: '', lines: [],
    };
  }
  const saved = new Map(card.lines.map((line) => [line.source_line_id, line]));
  const known = new Set<string>();
  const lines: FormLine[] = [];
  // Порядок — как у исходного документа; позиции, которых в сравнении нет
  // (оно не загрузилось), остаются по карточке.
  for (const position of positions) {
    known.add(position.source_line_id);
    const line = saved.get(position.source_line_id);
    lines.push({
      ...position, included: line !== undefined, price: line ? priceText(line.price) : '',
    });
  }
  for (const line of card.lines) {
    if (known.has(line.source_line_id)) continue;
    lines.push({
      source_line_id: line.source_line_id, item: line.item, name: line.name, qty: line.qty,
      uom: null, source_price: line.source_price, included: true, price: priceText(line.price),
    });
  }
  return {
    counterparty: card.counterparty,
    currency_code: card.currency_code,
    with_vat: card.with_vat,
    delivery_date: card.delivery_date ?? '',
    payment_terms: card.payment_terms,
    payment_terms_note: card.payment_terms_note,
    justification: card.justification,
    lines,
  };
}

/** Тело PATCH: отмеченные позиции; непонятная цена уходит как есть — 422 сервера на `lines`. */
export function patchOf(form: OfferFormState, version: number): OfferPatch {
  return {
    version,
    counterparty_id: form.counterparty?.id ?? null,
    currency_code: form.currency_code,
    with_vat: form.with_vat,
    delivery_date: form.delivery_date || null,
    payment_terms: form.payment_terms,
    payment_terms_note: form.payment_terms_note,
    justification: form.justification,
    lines: form.lines.filter((line) => line.included).map((line) => ({
      source_line_id: line.source_line_id,
      price: line.price.trim() === '' ? null : (parseMoneyInput(line.price) ?? line.price.trim()),
    })),
  };
}

export interface OfferTotals {
  /** Сумма АП по отмеченным позициям с ценой, тиыны. */
  offer: bigint;
  /** Исходная часть отмеченных позиций, тиыны. */
  source: bigint;
  /** Каждая отмеченная позиция с корректной ценой и позиция есть. */
  complete: boolean;
  /** Валюта АП совпадает с валютой исходного документа. */
  sameCurrency: boolean;
  /** Экономия «на лету»; `null` — считать нечем (нужен курс или не все цены). */
  saving: Saving | null;
  /** Сумма строки по `source_line_id` (для таблицы); нет цены — нет записи. */
  lineAmount: Map<string, bigint>;
  /** Отклонение цены по позиции, сотые доли %. */
  deviation: Map<string, bigint>;
}

export function totalsOf(form: OfferFormState, sourceCurrency: string | null): OfferTotals {
  const lineAmount = new Map<string, bigint>();
  const deviation = new Map<string, bigint>();
  let offer = 0n;
  let source = 0n;
  let complete = true;
  let included = 0;
  for (const line of form.lines) {
    if (!line.included) continue;
    included += 1;
    const sourcePrice = toCents(line.source_price);
    const sourceAmount = sourcePrice === null ? null : lineCents(line.qty, sourcePrice);
    if (sourceAmount !== null) source += sourceAmount;
    const price = line.price.trim() === '' ? null : centsFromInput(line.price);
    if (price === null || price <= 0n) {
      complete = false;
      continue;
    }
    const amount = lineCents(line.qty, price);
    if (amount === null) {
      complete = false;
      continue;
    }
    lineAmount.set(line.source_line_id, amount);
    offer += amount;
    const pct = sourcePrice === null ? null : deviationHundredths(price, sourcePrice);
    if (pct !== null) deviation.set(line.source_line_id, pct);
  }
  const sameCurrency = sourceCurrency !== null && form.currency_code === sourceCurrency;
  return {
    offer, source, complete: complete && included > 0, sameCurrency,
    saving: sameCurrency && complete && included > 0 ? saving(source, offer) : null,
    lineAmount, deviation,
  };
}

/** «350 000,00 KZT (12,50 %)» или «Дороже на 50 000,00 KZT (2,04 %)». */
export function savingText(value: Saving, currency: string, moreLabel: string): string {
  const abs = value.amount < 0n ? -value.amount : value.amount;
  const pct = value.pct < 0n ? -value.pct : value.pct;
  const body = `${formatMoney(fromCents(abs), currency)} (${formatPct(pct)} %)`;
  return value.moreExpensive ? `${moreLabel} ${body}` : body;
}

/** Экономия карточки (`saving_amount`/`saving_pct`, KZT) → `Saving`. */
export function savingFromServer(card: OfferCard): Saving | null {
  if (card.saving_amount === null || card.saving_pct === null) return null;
  return savingFromString(card.saving_amount, card.saving_pct);
}

/** Отклонение строки сервера («12.50») → «+12,50 %»; плюс — дороже исходного. */
export function deviationText(value: string | null): string {
  if (value === null) return '—';
  const cents = toCents(value);
  if (cents === null) return value;
  return `${cents > 0n ? '+' : ''}${formatPct(cents)} %`;
}

/** Отклонение строки сервера — плюс (дороже исходного). */
export const isDearer = (value: string | null): boolean => {
  const cents = value === null ? null : toCents(value);
  return cents !== null && cents > 0n;
};

export const deviationLabel = (hundredths: bigint): string =>
  `${hundredths > 0n ? '+' : ''}${formatPct(hundredths)} %`;

export interface OfferErrorContext {
  moreExpensive: boolean;
  totals: OfferTotals;
  today: string;
}

/** Клиентские отказы подачи — тем же набором полей, что у сервера (`fields`). */
export function submitErrors(
  form: OfferFormState, ctx: OfferErrorContext, t: TFunction,
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.counterparty) errors.counterparty_id = t('bpp.alternatives.err.counterparty', 'Выберите контрагента');
  const included = form.lines.filter((line) => line.included);
  if (included.length === 0) errors.lines = t('bpp.alternatives.err.noLines', 'Отметьте хотя бы одну позицию');
  else if (!ctx.totals.complete) {
    errors.lines = t('bpp.alternatives.err.prices', 'Введите цену за единицу у каждой отмеченной позиции');
  }
  if (!form.delivery_date) errors.delivery_date = t('bpp.alternatives.err.delivery', 'Укажите срок поставки');
  else if (form.delivery_date < ctx.today) {
    errors.delivery_date = t('bpp.alternatives.err.deliveryPast', 'Срок поставки — не раньше сегодняшней даты');
  }
  if (!form.payment_terms) errors.payment_terms = t('bpp.alternatives.err.terms', 'Выберите условия оплаты');
  const length = form.justification.trim().length;
  const min = ctx.moreExpensive ? JUSTIFICATION_MORE_EXPENSIVE_MIN : JUSTIFICATION_MIN;
  if (length < min) {
    errors.justification = ctx.moreExpensive
      ? t('bpp.alternatives.err.justificationDearer', 'При удорожании обоснование — не короче {{min}} знаков', { min })
      : t('bpp.alternatives.err.justification', 'Обоснование — не короче {{min}} знаков', { min });
  }
  return errors;
}
