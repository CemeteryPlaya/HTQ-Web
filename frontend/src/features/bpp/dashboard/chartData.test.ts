/**
 * Строки графиков дашборда: подписи сумм — `formatMoney` над строкой
 * сервера (без `float`), число — только высота столбца; «Оплачено факт»
 * без данных банка — `null`, а не ноль.
 */
import { describe, expect, it } from 'vitest';

import { articleBars, axisTick, tooltipText, weekPoints } from './chartData';

describe('chartData', () => {
  it('статьи: подписи из строк, большая сумма не теряет разряд', () => {
    const [bar] = articleBars([{
      article_id: 'a1', code: null, name: 'Металлопрокат',
      limit: '99999999999999.99', committed: '0', paid_fact: null,
    }]);
    expect(bar.name).toBe('Металлопрокат');
    expect(bar.limitText).toBe('99 999 999 999 999,99');
    expect(bar.committedText).toBe('0,00');
    expect(bar.paid_fact).toBeNull();
    expect(bar.paid_factText).toBeNull();
    expect(typeof bar.limit).toBe('number');
  });

  it('недели: подпись оси — дата понедельника', () => {
    expect(weekPoints([{ week_start: '2026-09-14', amount: '1250000.5' }])).toEqual([{
      week_start: '2026-09-14', week: '14.09.2026', amount: 1250000.5, amountText: '1 250 000,50',
    }]);
  });

  it('подсказка берёт подпись ряда, а не число recharts', () => {
    expect(tooltipText('amount', { amount: 0.1, amountText: '99 999 999 999 999,99' }, 'KZT'))
      .toBe('99 999 999 999 999,99 KZT');
    expect(tooltipText('paid_fact', { paid_fact: null, paid_factText: null })).toBe('—');
  });

  it('подсказка статей — без «KZT»: лимит и оплаты по статье в валюте счетов', () => {
    expect(tooltipText('limit', { limit: 0.1, limitText: '1 250 000,00' })).toBe('1 250 000,00');
  });

  it('деление оси — разряды без копеек', () => {
    expect(axisTick(2500000)).toBe('2 500 000');
  });
});
