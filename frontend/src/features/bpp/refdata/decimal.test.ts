/**
 * Десятичные значения справочников без float: курс — до 6 знаков, ставка
 * НДС — процент, порог договора — 1000 × МРП сдвигом запятой.
 */
import { describe, expect, it } from 'vitest';

import {
  formatDecimal, isPositiveDecimal, notAboveWhole, parseDecimalInput, thousandTimes,
} from './decimal';

describe('formatDecimal', () => {
  it('курс: хвостовые нули срезаются до двух знаков', () => {
    expect(formatDecimal('475.120000')).toBe('475,12');
    expect(formatDecimal('5.123456')).toBe('5,123456');
    expect(formatDecimal('1475.100000')).toBe('1 475,10');
  });

  it('ставка НДС и пустое значение', () => {
    expect(formatDecimal('12.00')).toBe('12,00');
    expect(formatDecimal('0')).toBe('0,00');
    expect(formatDecimal(null)).toBe('—');
  });

  it('нераспознанное — как есть', () => {
    expect(formatDecimal('abc')).toBe('abc');
  });
});

describe('parseDecimalInput', () => {
  it('запятая, пробелы тысяч', () => {
    expect(parseDecimalInput('1 475,5', 6)).toBe('1475.5');
    expect(parseDecimalInput('475.123456', 6)).toBe('475.123456');
    expect(parseDecimalInput('12', 2)).toBe('12');
  });

  it('лишние знаки, минус и не число — null, без округления', () => {
    expect(parseDecimalInput('475.1234567', 6)).toBeNull();
    expect(parseDecimalInput('12.345', 2)).toBeNull();
    expect(parseDecimalInput('-1', 6)).toBeNull();
    expect(parseDecimalInput('abc', 6)).toBeNull();
    expect(parseDecimalInput('', 6)).toBeNull();
  });
});

describe('проверки значения', () => {
  it('isPositiveDecimal', () => {
    expect(isPositiveDecimal('0.000001')).toBe(true);
    expect(isPositiveDecimal('0.00')).toBe(false);
  });

  it('notAboveWhole — ставка НДС до 100 включительно', () => {
    expect(notAboveWhole('100', 100)).toBe(true);
    expect(notAboveWhole('100.00', 100)).toBe(true);
    expect(notAboveWhole('100.01', 100)).toBe(false);
    expect(notAboveWhole('99.99', 100)).toBe(true);
  });
});

describe('thousandTimes', () => {
  it('1000 × МРП', () => {
    expect(thousandTimes('4325.00')).toBe('4325000');
    expect(thousandTimes('4325.5')).toBe('4325500');
    expect(thousandTimes('0.25')).toBe('250');
  });
});
