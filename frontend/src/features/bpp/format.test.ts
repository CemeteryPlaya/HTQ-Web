/**
 * Формат модуля БЗО (ТЗ §05, §13.2; Review Focus 5 плана этапа 2 A):
 * сумма из строки без потери разрядов, дата-время по Asia/Almaty,
 * разбор ввода суммы человеком.
 */
import { describe, expect, it } from 'vitest';

import { formatDate, formatDateTime, formatMoney, parseMoneyInput } from './format';

describe('formatMoney', () => {
  it('разряды через пробел, копейки через запятую, валюта рядом', () => {
    expect(formatMoney('1250000.5', 'KZT')).toBe('1 250 000,50 KZT');
    expect(formatMoney('1250000')).toBe('1 250 000,00');
    expect(formatMoney('0.5')).toBe('0,50');
  });

  it('знак и ноль', () => {
    expect(formatMoney('-15')).toBe('-15,00');
    expect(formatMoney('0')).toBe('0,00');
    expect(formatMoney('-0.001')).toBe('0,00');
  });

  it('не теряет разрядов там, где float уже ошибается', () => {
    expect(formatMoney('99999999999999.99', 'KZT')).toBe('99 999 999 999 999,99 KZT');
    expect(formatMoney('12345678901234567.89')).toBe('12 345 678 901 234 567,89');
  });

  it('округляет до копейки half-up, как сервер', () => {
    expect(formatMoney('0.005')).toBe('0,01');
    expect(formatMoney('0.004')).toBe('0,00');
    expect(formatMoney('-2.345')).toBe('-2,35');
    expect(formatMoney('999.995')).toBe('1 000,00');
  });

  it('число переводится через String', () => {
    expect(formatMoney(1250000.5, 'KZT')).toBe('1 250 000,50 KZT');
    expect(formatMoney(-15)).toBe('-15,00');
  });

  it('нераспознанное значение показывается как есть', () => {
    expect(formatMoney('abc')).toBe('abc');
  });
});

describe('formatDate', () => {
  it('ДД.ММ.ГГГГ и прочерк для пустой даты', () => {
    expect(formatDate('2026-10-15')).toBe('15.10.2026');
    expect(formatDate(null)).toBe('—');
  });
});

describe('formatDateTime', () => {
  it('переводит момент в Asia/Almaty (UTC+5) — Review Focus 5', () => {
    expect(formatDateTime('2026-09-27T20:30:00Z')).toBe('28.09.2026 01:30');
  });

  it('полночь — 00, а не 24', () => {
    expect(formatDateTime('2026-09-27T19:00:00Z')).toBe('28.09.2026 00:00');
  });

  it('прочерк для пустого и нераспознанного значения', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime('не дата')).toBe('—');
  });
});

describe('parseMoneyInput', () => {
  it('ввод человека → строка-десятичная для сервера', () => {
    expect(parseMoneyInput('1 250 000,00')).toBe('1250000.00');
    expect(parseMoneyInput('1 250 000,5')).toBe('1250000.50');
    expect(parseMoneyInput('1250000.5')).toBe('1250000.50');
    expect(parseMoneyInput('42')).toBe('42.00');
    expect(parseMoneyInput(',5')).toBe('0.50');
    expect(parseMoneyInput('007')).toBe('7.00');
  });

  it('больше двух знаков после запятой — не принимается', () => {
    expect(parseMoneyInput('1,005')).toBeNull();
  });

  it('не число — не принимается', () => {
    expect(parseMoneyInput('')).toBeNull();
    expect(parseMoneyInput('   ')).toBeNull();
    expect(parseMoneyInput('abc')).toBeNull();
    expect(parseMoneyInput('1,2,3')).toBeNull();
    expect(parseMoneyInput('1.250.000')).toBeNull();
    expect(parseMoneyInput('12e3')).toBeNull();
    expect(parseMoneyInput(',')).toBeNull();
  });
});
