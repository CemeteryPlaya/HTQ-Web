/**
 * Готовые колонки реестров модуля (задача 8): «Статус» — бейдж по словарю
 * вида документа; «Сейчас у» — исполнитель этапа или «нет исполнителя».
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import i18n from '@/i18n';

import {
  currentHoldersColumn, moneyColumn, moneyTotal, statusColumn,
} from './registryColumns';
import type { CurrentHolders } from './registryTypes';

const t = i18n.t.bind(i18n);

describe('statusColumn', () => {
  it('рисует StatusBadge по коду строки', () => {
    const column = statusColumn<{ status: string }>(t, 'request');
    render(<>{column.render!({ status: 'in_approval' })}</>);
    expect(screen.getByText('На согласовании')).toBeInTheDocument();
  });
});

describe('currentHoldersColumn', () => {
  const column = currentHoldersColumn<{ current_holders?: CurrentHolders | null }>(t);

  it('никого не ждёт — прочерк', () => {
    render(<>{column.render!({ current_holders: null })}</>);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('нет исполнителя — предупреждение с этапом', () => {
    render(<>{column.render!({
      current_holders: {
        stage: 'Технический директор', users: [], position: null, since: '', no_executor: true,
      },
    })}</>);
    expect(screen.getByText(/Нет исполнителя: Технический директор/)).toBeInTheDocument();
  });

  it('есть держатели — имена, этап и «с» дата', () => {
    render(<>{column.render!({
      current_holders: {
        stage: 'Финансовый директор',
        users: [{ id: 1, name: 'Иванов А.' }, { id: 2, name: 'Петров Б.' }],
        position: null,
        since: '2026-09-27T20:30:00Z',
        no_executor: false,
      },
    })}</>);
    expect(screen.getByText('Иванов А., Петров Б.')).toBeInTheDocument();
    expect(screen.getByText(/Финансовый директор/)).toBeInTheDocument();
    expect(screen.getByText(/28.09.2026 01:30/)).toBeInTheDocument();
  });
});

describe('moneyColumn', () => {
  interface MoneyRow { amount: string | null; currency_code: string }

  it('сумма строки — формат модуля с валютой из поля строки, по правому краю', () => {
    const column = moneyColumn<MoneyRow>('amount', 'Сумма', { currency: 'currency_code' });
    expect(column.align).toBe('right');
    render(<>{column.render!({ amount: '99999999999999.99', currency_code: 'KZT' })}</>);
    // Без float: последний разряд не теряется.
    expect(screen.getByText('99 999 999 999 999,99 KZT')).toBeInTheDocument();
  });

  it('валюта функцией; пустая сумма — прочерк, а не ноль', () => {
    const column = moneyColumn<MoneyRow>('amount', 'Сумма', { currency: () => 'USD' });
    const { unmount } = render(<>{column.render!({ amount: '1250000.5', currency_code: '' })}</>);
    expect(screen.getByText('1 250 000,50 USD')).toBeInTheDocument();
    unmount();
    render(<>{column.render!({ amount: null, currency_code: 'KZT' })}</>);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('итог — только если назван ключ итога', () => {
    expect(moneyColumn<MoneyRow>('amount', 'Сумма').total).toBeUndefined();
    const column = moneyColumn<MoneyRow>('amount', 'Сумма', {
      totalKey: 'amount_sum', totalCurrency: 'KZT',
    });
    render(<>{column.total!({ amount_sum: '1000' })}</>);
    expect(screen.getByText('1 000,00 KZT')).toBeInTheDocument();
  });
});

describe('moneyTotal', () => {
  it('итог по валютам — каждая своей строкой', () => {
    render(<>{moneyTotal('amount')({ amount: { KZT: '1500000', USD: '2000.5' } })}</>);
    expect(screen.getByText('1 500 000,00 KZT')).toBeInTheDocument();
    expect(screen.getByText('2 000,50 USD')).toBeInTheDocument();
  });

  it('сервер итог не прислал — прочерк; ноль — ноль', () => {
    const { unmount } = render(<>{moneyTotal('amount')({})}</>);
    expect(screen.getByText('—')).toBeInTheDocument();
    unmount();
    render(<>{moneyTotal('amount')({ amount: '0' })}</>);
    expect(screen.getByText('0,00')).toBeInTheDocument();
  });
});
