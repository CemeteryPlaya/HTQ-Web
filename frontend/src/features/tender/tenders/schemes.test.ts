/**
 * Желаемая схема оплаты тендера (план §4.1): шаблоны 1–3 — предоплата,
 * аванс X % + остаток по приёмке, постоплата через N дней; тело `PUT
 * payment-scheme`, проверки ввода и подпись схемы из этапов сервера.
 */
import { describe, expect, it } from 'vitest';

import { describeScheme, schemeDraftOf, schemeErrors, schemeInput } from './schemes';

describe('schemeInput / schemeErrors', () => {
  it('предоплата — только вид', () => {
    expect(schemeInput({ kind: 'prepay', advance_pct: '', postpay_days: '' }))
      .toEqual({ kind: 'prepay' });
    expect(schemeErrors({ kind: 'prepay', advance_pct: '', postpay_days: '' })).toEqual({});
  });

  it('аванс — процент от 1 до 99, запятая допустима', () => {
    expect(schemeInput({ kind: 'advance', advance_pct: '30,5', postpay_days: '' }))
      .toEqual({ kind: 'advance', advance_pct: '30.5' });
    expect(schemeErrors({ kind: 'advance', advance_pct: '0', postpay_days: '' }))
      .toHaveProperty('advance_pct');
    expect(schemeErrors({ kind: 'advance', advance_pct: '100', postpay_days: '' }))
      .toHaveProperty('advance_pct');
    expect(schemeErrors({ kind: 'advance', advance_pct: 'abc', postpay_days: '' }))
      .toHaveProperty('advance_pct');
  });

  it('постоплата — целое число дней от 1 до 365', () => {
    expect(schemeInput({ kind: 'postpay', advance_pct: '', postpay_days: '30' }))
      .toEqual({ kind: 'postpay', postpay_days: 30 });
    expect(schemeErrors({ kind: 'postpay', advance_pct: '', postpay_days: '' })).toHaveProperty('postpay_days');
    expect(schemeErrors({ kind: 'postpay', advance_pct: '', postpay_days: '1.5' })).toHaveProperty('postpay_days');
    expect(schemeErrors({ kind: 'postpay', advance_pct: '', postpay_days: '400' })).toHaveProperty('postpay_days');
  });

  it('вид не выбран — ошибка', () => {
    expect(schemeErrors({ kind: '', advance_pct: '', postpay_days: '' })).toHaveProperty('kind');
  });
});

describe('schemeDraftOf / describeScheme', () => {
  const advance = {
    kind: 'advance' as const,
    stages: [
      { order: 1, trigger: 'before_shipment', pct: '30.00', days: null },
      { order: 2, trigger: 'on_receipt', pct: '70.00', days: null },
    ],
    postpay_days: null,
  };

  it('черновик схемы из карточки: процент аванса — из первого этапа', () => {
    expect(schemeDraftOf(advance)).toEqual({ kind: 'advance', advance_pct: '30', postpay_days: '' });
    expect(schemeDraftOf(null)).toEqual({ kind: '', advance_pct: '', postpay_days: '' });
    expect(schemeDraftOf({ kind: 'postpay', stages: [], postpay_days: 45 }))
      .toEqual({ kind: 'postpay', advance_pct: '', postpay_days: '45' });
  });

  it('подпись схемы', () => {
    expect(describeScheme(advance)).toBe('Аванс 30 % до отгрузки, 70 % по приёмке');
    expect(describeScheme({ kind: 'prepay', stages: [], postpay_days: null })).toBe('Предоплата 100 %');
    expect(describeScheme({ kind: 'postpay', stages: [], postpay_days: 30 }))
      .toBe('Постоплата через 30 дн. после приёмки');
    expect(describeScheme(null)).toBe('Не задана');
  });
});
