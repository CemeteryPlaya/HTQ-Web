/**
 * Правила ввода проверяются здесь, а не в каждой форме: текст отказа и
 * граничные случаи должны быть одни на платформу.
 *
 * Отдельно закреплены два решения, которые легко «починить» в неверную
 * сторону: незаполненная дата — НЕ ошибка (обе даты почти везде
 * необязательны), а неизвестный остаток НЕ запрещает отправку (пока лимит
 * не загружен, форма не должна мешать работать).
 */
import { describe, expect, it } from 'vitest';

import {
  DATES_OUT_OF_ORDER, datesOutOfOrder, findSimilarName, invalidAmount,
  overLimit, parseAmount,
} from '@/lib/validation';

describe('порядок дат', () => {
  it('ловит перепутанные местами', () => {
    expect(datesOutOfOrder('2026-05-01', '2026-04-01')).toBe(true);
  });

  it('пропускает верный порядок и один и тот же день', () => {
    expect(datesOutOfOrder('2026-04-01', '2026-05-01')).toBe(false);
    expect(datesOutOfOrder('2026-04-01', '2026-04-01')).toBe(false);
  });

  it('пустую дату ошибкой не считает', () => {
    expect(datesOutOfOrder('', '2026-04-01')).toBe(false);
    expect(datesOutOfOrder('2026-05-01', undefined)).toBe(false);
    expect(datesOutOfOrder(null, null)).toBe(false);
  });

  it('говорит теми же словами, что и бэкенд', () => {
    expect(DATES_OUT_OF_ORDER).toBe('Дата начала позже даты окончания');
  });
});

describe('суммы', () => {
  it('принимает запятую наравне с точкой', () => {
    expect(parseAmount('1234,56')).toBe(1234.56);
    expect(parseAmount('1234.56')).toBe(1234.56);
  });

  it('отвергает ноль, минус, буквы и три знака после запятой', () => {
    for (const bad of ['0', '-5', 'сто', '10.005', '']) {
      expect(invalidAmount(bad), bad).toBe(true);
    }
    expect(invalidAmount('100.50')).toBe(false);
  });

  it('сравнивает с остатком, пришедшим строкой', () => {
    expect(overLimit('500', '400.00')).toBe(true);
    expect(overLimit('400', '400.00')).toBe(false);
    expect(overLimit('500', 400)).toBe(true);
  });

  it('не запрещает, пока остаток неизвестен', () => {
    expect(overLimit('500', null)).toBe(false);
    expect(overLimit('500', undefined)).toBe(false);
  });
});

describe('похожее имя', () => {
  it('находит дубль, отличающийся регистром и пробелами', () => {
    expect(findSimilarName(' алга ', ['Тобол', 'Алга'])).toBe('Алга');
  });

  it('молчит, когда совпадения нет или имя пустое', () => {
    expect(findSimilarName('Сазаган', ['Тобол', 'Алга'])).toBeNull();
    expect(findSimilarName('  ', ['Алга'])).toBeNull();
  });
});
