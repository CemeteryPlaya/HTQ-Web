import { describe, expect, it } from 'vitest';

import { formatTenure, tenureParts } from '@/components/hr/tenure';

// Простой стенд вместо i18next: возвращает ключ + count, чтобы проверялся
// именно выбор единиц, а не перевод.
const t = ((key: string, opts?: { count?: number }) =>
  `${key}:${opts?.count}`) as never;

describe('tenureParts', () => {
  it('считает полные годы, месяцы и дни от даты приёма до «сейчас»', () => {
    const parts = tenureParts('2020-03-10', null, new Date(2023, 4, 12));
    expect(parts).toEqual({ years: 3, months: 2, days: 2 });
  });

  it('занимает дни из предыдущего месяца, когда день приёма ещё не наступил', () => {
    const parts = tenureParts('2024-01-31', null, new Date(2024, 2, 1));
    // 31 января → 1 марта: 1 полный месяц (до 29 февраля) и 1 день сверху.
    expect(parts).toEqual({ years: 0, months: 1, days: 1 });
  });

  it('для уволенного считает стаж до даты увольнения, а не до сегодня', () => {
    const parts = tenureParts('2020-01-01', '2021-07-01', new Date(2026, 0, 1));
    expect(parts).toEqual({ years: 1, months: 6, days: 0 });
  });

  it('не парсит YYYY-MM-DD как UTC — день не уезжает назад', () => {
    const parts = tenureParts('2024-05-15', null, new Date(2024, 4, 15));
    expect(parts).toEqual({ years: 0, months: 0, days: 0 });
  });

  it('пустая дата и дата из будущего дают null', () => {
    expect(tenureParts(null)).toBeNull();
    expect(tenureParts('')).toBeNull();
    expect(tenureParts('не дата')).toBeNull();
    expect(tenureParts('2030-01-01', null, new Date(2026, 0, 1))).toBeNull();
  });
});

describe('formatTenure', () => {
  it('годы и месяцы, дни при этом опускаются', () => {
    expect(formatTenure(t, '2020-03-10', null, new Date(2023, 4, 12)))
      .toBe('hr.card.tenureYears:3 hr.card.tenureMonths:2');
  });

  it('ровные годы — без нулевых месяцев', () => {
    expect(formatTenure(t, '2020-03-10', null, new Date(2023, 2, 10)))
      .toBe('hr.card.tenureYears:3');
  });

  it('меньше года — месяцы, меньше месяца — дни', () => {
    expect(formatTenure(t, '2024-01-10', null, new Date(2024, 4, 10)))
      .toBe('hr.card.tenureMonths:4');
    expect(formatTenure(t, '2024-01-10', null, new Date(2024, 0, 25)))
      .toBe('hr.card.tenureDays:15');
  });

  it('без даты приёма ничего не рисуем', () => {
    expect(formatTenure(t, null)).toBeNull();
  });
});
