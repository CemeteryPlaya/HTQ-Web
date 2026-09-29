/**
 * Денежная колонка реестров бюджета, заявок и плана (ТЗ §4: «1 250 000,00»,
 * выравнивание вправо). В плане этапа 2 A общая `moneyColumn` появится в
 * `core/registryColumns.tsx` — тогда экраны B перейдут на неё, а этот файл
 * уйдёт (сверка B §10).
 */
import type { ReactNode } from 'react';

import type { RegistryColumn } from '../core/registryTypes';
import { formatMoney } from '../format';

export function moneyColumn<Row>(
  key: string,
  title: string,
  value: (row: Row) => string | null | undefined,
  options: { currency?: (row: Row) => string; total?: string; sortable?: boolean } = {},
): RegistryColumn<Row> {
  return {
    key,
    title,
    align: 'right',
    sortable: options.sortable,
    render: (row) => {
      const amount = value(row);
      if (amount === null || amount === undefined || amount === '') {
        return <span className="text-muted-foreground">—</span>;
      }
      return (
        <span className={Number(amount) < 0 ? 'text-destructive' : undefined}>
          {formatMoney(amount, options.currency?.(row))}
        </span>
      );
    },
    total: options.total
      ? (totals): ReactNode => {
        const amount = totals[options.total as string];
        return typeof amount === 'string' || typeof amount === 'number'
          ? formatMoney(amount)
          : null;
      }
      : undefined,
  };
}
