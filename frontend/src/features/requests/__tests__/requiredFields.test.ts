/**
 * Зеркало серверных проверок формы: обязательность и совпадение сумм.
 *
 * Смысл тестов — не «функция работает», а «клиент не врёт о правилах»:
 * он обязан запрещать РОВНО то же, что сервер (`value_validation.py`), —
 * запретив больше, он не даст отправить законную заявку, запретив меньше,
 * подведёт человека под 409 после нажатия.
 */

import { describe, expect, it } from 'vitest';

import { blockedByRequired, mismatchIn, missingRequired } from '../requiredFields';
import type { FormSchema } from '../types';

const schema = {
  fields: [
    { key: 'limit', type: 'money', label: 'Лимит', required: true },
    { key: 'note', type: 'text', label: 'Комментарий' },
    {
      key: 'invoice', type: 'group', label: 'Счёт', repeatable: false,
      filled_by: 'approver',
      fields: [
        { key: 'number', type: 'text', label: 'Номер', required: true },
        { key: 'amount', type: 'money', label: 'Сумма', must_equal: 'limit' },
      ],
    },
  ],
} as unknown as FormSchema;

describe('обязательные поля', () => {
  it('поля согласующего с инициатора не спрашиваются', () => {
    // `invoice` — блок закупщика: он заполняется уже на согласовании,
    // и требовать его при подаче значило бы не дать отправить заявку.
    expect(missingRequired(schema, { limit: 100 })).toEqual([]);
  });

  it('незаполненное поле инициатора называется подписью, а не ключом', () => {
    expect(missingRequired(schema, {})).toEqual(['Лимит']);
    expect(blockedByRequired(schema, {})).toBe('Заполните поле «Лимит»');
  });
});

describe('совпадение сумм (must_equal)', () => {
  it('равные значения проходят в любом виде из JSON', () => {
    // Суммы приходят то числом, то строкой: `100 === '100.00'` ложно,
    // поэтому сравнение числовое.
    expect(mismatchIn(schema, 'invoice', { limit: 100, invoice: { amount: 100 } })).toBeNull();
    expect(mismatchIn(schema, 'invoice', { limit: 100, invoice: { amount: '100.00' } })).toBeNull();
  });

  it('расхождение называет оба поля и оба числа', () => {
    const problem = mismatchIn(schema, 'invoice', {
      limit: 2400000, invoice: { amount: 2500000 },
    });
    expect(problem).toContain('«Счёт → Сумма»');
    expect(problem).toContain('«Лимит»');
    expect(problem).toContain('2500000');
    expect(problem).toContain('2400000');
  });

  it('пустое значение — не расхождение', () => {
    // Пусто — забота обязательности: иначе человек, ещё не начавший
    // заполнять, сразу получал бы «не совпадает».
    expect(mismatchIn(schema, 'invoice', { limit: 100, invoice: {} })).toBeNull();
    expect(mismatchIn(schema, 'invoice', { invoice: { amount: 100 } })).toBeNull();
  });

  it('проверяется только спрошенное поле верхнего уровня', () => {
    // На шаге проверяют блок ЭТОГО шага, а не всю форму.
    const values = { limit: 100, invoice: { amount: 999 } };
    expect(mismatchIn(schema, 'invoice', values)).not.toBeNull();
    expect(mismatchIn(schema, 'limit', values)).toBeNull();
  });
});
