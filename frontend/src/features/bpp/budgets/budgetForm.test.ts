/**
 * Форма F-01 до отправки (ТЗ §6.4–6.5): дубль статьи (BR-002), лимит — сумма
 * ≥ 0, в корректировке — не ниже задействованного (BR-004); деньги без `float`.
 */
import { describe, expect, it } from 'vitest';

import type { BudgetCard, BudgetLine } from './api';
import { formOf, linesInput, validateLines, type EditLine } from './budgetForm';
import { fromCents, lessThan, subMoney, sumMoney, toCents } from './cents';

const line = (over: Partial<EditLine>): EditLine => ({
  key: over.key ?? 'k', article_id: 'a1', limit: '100,00', comment: '', locked: false,
  committed: null, paid_fact: null, ...over,
});

describe('cents', () => {
  it('складывает деньги без ошибок float', () => {
    expect(sumMoney(['0.10', '0.20'])).toBe('0.30');
    expect(sumMoney(['1250000.00', '0.01', null])).toBe('1250000.01');
    expect(subMoney('100.00', '250.50')).toBe('-150.50');
    expect(fromCents(toCents('-0.05')!)).toBe('-0.05');
    expect(lessThan('3399999.99', '3400000')).toBe(true);
    expect(toCents('abc')).toBeNull();
  });
});

describe('validateLines', () => {
  it('дубль статьи называет первую строку (BR-002)', () => {
    const errors = validateLines([
      line({ key: 'a', article_id: 'x' }),
      line({ key: 'b', article_id: 'y' }),
      line({ key: 'c', article_id: 'x' }),
    ], { correction: false });
    expect(errors).toEqual({ c: 'Статья уже есть в бюджете, строка 1' });
  });

  it('лимит — сумма в формате модуля, не меньше нуля', () => {
    expect(validateLines([line({ limit: '1 250 000,00' })], { correction: false })).toEqual({});
    expect(validateLines([line({ limit: '12,345' })], { correction: false }).k).toMatch(/1 250 000,00/);
    expect(validateLines([line({ limit: '-1' })], { correction: false }).k).toMatch(/не меньше нуля/);
  });

  it('в корректировке лимит ниже задействованного — текст ТЗ §6.5 п.3', () => {
    const errors = validateLines(
      [line({ limit: '3 000 000,00', committed: '3400000.00' })], { correction: true },
    );
    expect(errors.k).toBe('Лимит не может быть меньше задействованной суммы 3 400 000,00');
    expect(validateLines(
      [line({ limit: '3 400 000,00', committed: '3400000.00' })], { correction: true },
    )).toEqual({});
  });

  it('без статьи — «Выберите статью»', () => {
    expect(validateLines([line({ article_id: '' })], { correction: false }).k).toBe('Выберите статью');
  });
});

describe('formOf', () => {
  const budgetLine = (article: string, limit: string): BudgetLine => ({
    id: article, article_id: article, article_code: article, article_name: article,
    article_archived: false, group_code: 'supply', group_name: 'Снабжение',
    limit_amount: limit, comment: '', committed: '100.00', paid_fact: '0.00', available: '0.00',
  });

  it('в корректировке запирает статьи действующей версии, новые — нет', () => {
    const card = {
      project: { id: 'p' }, currency_code: 'KZT',
      lines: [budgetLine('old', '100.00')],
      correction: {
        version_no: 2, comment: 'Рост цен', totals: {} as BudgetCard['totals'],
        lines: [budgetLine('old', '200.00'), budgetLine('new', '50.00')],
      },
    } as unknown as BudgetCard;
    const form = formOf(card);
    expect(form.comment).toBe('Рост цен');
    expect(form.lines.map((l) => [l.article_id, l.locked, l.limit])).toEqual([
      ['old', true, '200,00'], ['new', false, '50,00'],
    ]);
    expect(linesInput(form.lines)).toEqual([
      { article_id: 'old', limit_amount: '200.00', comment: '' },
      { article_id: 'new', limit_amount: '50.00', comment: '' },
    ]);
  });
});
