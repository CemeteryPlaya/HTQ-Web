/**
 * Готовые колонки реестров модуля: «Статус» и «Сейчас у» одинаковы во всех
 * реестрах документов, поэтому собираются здесь, а не в каждом экране; сумма
 * (`moneyColumn`) и её итог по выборке (`moneyTotal`) — в формате модуля
 * через `formatMoney`, без арифметики над `float`.
 */
import type { ReactNode } from 'react';
import type { TFunction } from 'i18next';

import { formatDateTime, formatMoney } from '../format';

import type { CurrentHolders, RegistryColumn } from './registryTypes';
import { StatusBadge } from './StatusBadge';
import type { StatusKind } from './statusDictionaries';

/** Колонка «Статус» — бейдж по словарю вида документа. */
export function statusColumn<Row extends { status: string }>(
  t: TFunction,
  kind: StatusKind,
): RegistryColumn<Row> {
  return {
    key: 'status',
    title: t('bpp.registry.status', 'Статус'),
    sortable: true,
    render: (row) => <StatusBadge kind={kind} status={row.status} />,
  };
}

/**
 * Колонка «Сейчас у» (ТЗ §16.2): у кого документ на согласовании и с какого
 * момента. Поле строки — `current_holders` (реестры B отдают его сами,
 * `signoff.interface.current_holders`); `null` — документ ни у кого не ждёт.
 */
export function currentHoldersColumn<Row extends { current_holders?: CurrentHolders | null }>(
  t: TFunction,
): RegistryColumn<Row> {
  return {
    key: 'current_holders',
    title: t('bpp.registry.currentHolders', 'Сейчас у'),
    render: (row) => {
      const holders = row.current_holders;
      if (!holders) return <span className="text-muted-foreground">—</span>;
      if (holders.no_executor) {
        return (
          <span className="text-destructive">
            {t('bpp.registry.noExecutor', 'Нет исполнителя: {{stage}}', { stage: holders.stage })}
          </span>
        );
      }
      const names = holders.users.map((user) => user.name).filter(Boolean).join(', ');
      return (
        <div className="leading-tight">
          <div>{names || holders.position || '—'}</div>
          <div className="text-xs text-muted-foreground">
            {holders.stage}
            {holders.since ? ` · ${t('bpp.registry.since', 'с')} ${formatDateTime(holders.since)}` : ''}
          </div>
        </div>
      );
    },
  };
}

const DASH = <span className="text-muted-foreground">—</span>;

const isAmount = (value: unknown): value is string | number =>
  (typeof value === 'string' && value.trim() !== '') || typeof value === 'number';

/**
 * Ячейка итоговой строки с суммой из `totals` сервера (итог по ВСЕЙ выборке).
 *
 * Значение — строка-десятичная или число: `1 250 000,00 KZT` (валюта —
 * `currency`, если выборка в одной валюте). Итог по валютам — объект
 * `{KZT: "…", USD: "…"}`: складывать разные валюты нельзя, поэтому каждая
 * своей строкой. Нет значения — прочерк, а не ноль: «сервер итог не прислал»
 * и «итог ноль» не должны выглядеть одинаково.
 */
export function moneyTotal(
  key: string,
  currency?: string,
): (totals: Record<string, unknown>) => ReactNode {
  return (totals) => {
    const value = totals[key];
    if (isAmount(value)) return <span className="whitespace-nowrap">{formatMoney(value, currency)}</span>;
    if (value && typeof value === 'object') {
      const lines = Object.entries(value as Record<string, unknown>).filter(([, v]) => isAmount(v));
      if (lines.length === 0) return DASH;
      return (
        <div className="leading-tight">
          {lines.map(([code, amount]) => (
            <div key={code} className="whitespace-nowrap">{formatMoney(amount as string | number, code)}</div>
          ))}
        </div>
      );
    }
    return DASH;
  };
}

export interface MoneyColumnOptions<Row> {
  /** Поле сортировки сервера; `true` — совпадает с ключом. */
  sortable?: boolean | string;
  /** Валюта строки: имя поля строки (`currency_code`) или функция. */
  currency?: keyof Row & string | ((row: Row) => string | null | undefined);
  /** Ключ итога в `totals` сервера; без него итоговой ячейки нет. */
  totalKey?: string;
  /** Валюта итога, если выборка в одной валюте. */
  totalCurrency?: string;
}

/** Колонка суммы: по правому краю, `1 250 000,00 KZT`, итог — `moneyTotal`. */
export function moneyColumn<Row>(
  key: keyof Row & string,
  title: string,
  { sortable, currency, totalKey, totalCurrency }: MoneyColumnOptions<Row> = {},
): RegistryColumn<Row> {
  const currencyOf = (row: Row): string | undefined => {
    const code = typeof currency === 'function'
      ? currency(row)
      : currency ? (row as Record<string, unknown>)[currency] : undefined;
    return typeof code === 'string' && code ? code : undefined;
  };
  return {
    key,
    title,
    sortable,
    align: 'right',
    render: (row) => {
      const value = (row as Record<string, unknown>)[key];
      if (!isAmount(value)) return DASH;
      return <span className="whitespace-nowrap">{formatMoney(value, currencyOf(row))}</span>;
    },
    total: totalKey ? moneyTotal(totalKey, totalCurrency) : undefined,
  };
}
