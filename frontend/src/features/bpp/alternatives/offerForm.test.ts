/**
 * Расчёт F-07 «на лету» — в тиынах, без `float` (CALC-013): экономия,
 * удорожание, отклонение цены, исключённые позиции и другая валюта.
 */
import type { TFunction } from 'i18next';
import { describe, expect, it } from 'vitest';

import { formatMoney } from '../format';

import type { OfferCard } from './api';
import {
  deviationText, formOf, patchOf, savingText, submitErrors, totalsOf, type FormLine,
  type OfferFormState,
} from './offerForm';
import { divRound, formatPct, lineCents, saving } from './money';

const line = (over: Partial<FormLine> = {}): FormLine => ({
  source_line_id: 'l1', item: 'ЗЗ-1-01', name: 'Швеллер', qty: '10.000', uom: 'т',
  source_price: '280000.00', included: true, price: '245 000,00', ...over,
});

const form = (lines: FormLine[], over: Partial<OfferFormState> = {}): OfferFormState => ({
  counterparty: null, currency_code: 'KZT', with_vat: true, delivery_date: '2099-01-15',
  payment_terms: 'postpay', payment_terms_note: '', justification: '', lines, ...over,
});

const tr = ((_key: string, fallback: string, opts?: { min?: number }) =>
  fallback.replace('{{min}}', String(opts?.min ?? ''))) as unknown as TFunction;

describe('расчёт в тиынах', () => {
  it('2 800 000 − 2 450 000 → 350 000,00 KZT (12,50 %)', () => {
    const totals = totalsOf(form([line()]), 'KZT');
    expect(totals.offer).toBe(245000000n);
    expect(totals.source).toBe(280000000n);
    expect(totals.saving).toEqual({ amount: 35000000n, pct: 1250n, moreExpensive: false });
    expect(savingText(totals.saving!, 'KZT', 'Дороже на')).toBe('350 000,00 KZT (12,50 %)');
  });

  it('удорожание — «Дороже на …», знак отклонения плюс', () => {
    const totals = totalsOf(form([line({ price: '300 000' })]), 'KZT');
    expect(totals.saving?.moreExpensive).toBe(true);
    expect(savingText(totals.saving!, 'KZT', 'Дороже на')).toBe('Дороже на 200 000,00 KZT (7,14 %)');
    expect(totals.deviation.get('l1')).toBe(714n);
  });

  it('снятая галочка исключает позицию из суммы, а нет цены — экономии', () => {
    const lines = [line(), line({ source_line_id: 'l2', qty: '1', source_price: '100000.00', price: '', included: false })];
    expect(totalsOf(form(lines), 'KZT').offer).toBe(245000000n);
    expect(totalsOf(form(lines), 'KZT').source).toBe(280000000n);
    const partial = [line(), line({ source_line_id: 'l2', qty: '1', source_price: '100000.00', price: '' })];
    const totals = totalsOf(form(partial), 'KZT');
    expect(totals.complete).toBe(false);
    expect(totals.saving).toBeNull();
  });

  it('другая валюта — на лету не считаем (нужен курс)', () => {
    const totals = totalsOf(form([line()], { currency_code: 'USD' }), 'KZT');
    expect(totals.sameCurrency).toBe(false);
    expect(totals.saving).toBeNull();
  });

  it('дробное количество и округление half-up до тиына', () => {
    expect(lineCents('2.5', 333n)).toBe(833n); // 832,5 → 833
    expect(divRound(-5n, 2n)).toBe(-3n);
    expect(formatPct(-714n)).toBe('-7,14');
    expect(saving(0n, 100n)).toEqual({ amount: -100n, pct: 0n, moreExpensive: true });
    expect(formatMoney('350000.00', 'KZT')).toBe('350 000,00 KZT');
  });

  it('отклонение строки сервера: плюс — дороже', () => {
    expect(deviationText('12.50')).toBe('+12,50 %');
    expect(deviationText('-3.00')).toBe('-3,00 %');
    expect(deviationText(null)).toBe('—');
  });
});

describe('состояние формы', () => {
  it('в запрос идут только отмеченные позиции, пустая цена — null', () => {
    const body = patchOf(form([
      line(), line({ source_line_id: 'l2', included: false }),
      line({ source_line_id: 'l3', price: '' }),
    ]), 4);
    expect(body.version).toBe(4);
    expect(body.lines).toEqual([
      { source_line_id: 'l1', price: '245000.00' },
      { source_line_id: 'l3', price: null },
    ]);
  });

  it('позиция из сравнения без строки АП — без галочки', () => {
    const card = { lines: [{ source_line_id: 'l1', item: 'a', name: 'A', qty: '1', source_price: '5.00', price: '4.00' }],
      counterparty: null, currency_code: 'KZT', with_vat: false, delivery_date: null,
      payment_terms: '', payment_terms_note: '', justification: '' } as unknown as OfferCard;
    const state = formOf(card, [
      { source_line_id: 'l1', item: 'a', name: 'A', uom: null, qty: '1', source_price: '5.00' },
      { source_line_id: 'l2', item: 'b', name: 'B', uom: null, qty: '2', source_price: '7.00' },
    ]);
    expect(state.lines.map((row) => [row.source_line_id, row.included])).toEqual([['l1', true], ['l2', false]]);
  });

  it('обоснование при удорожании — не короче 30', () => {
    const state = form([line({ price: '300 000' })], { justification: 'Короткое обоснование!' });
    const totals = totalsOf(state, 'KZT');
    const errors = submitErrors(state, { moreExpensive: true, totals, today: '2026-09-30' }, tr);
    expect(errors.justification).toContain('30');
    expect(submitErrors(state, { moreExpensive: false, totals, today: '2026-09-30' }, tr).justification).toBeUndefined();
  });
});
