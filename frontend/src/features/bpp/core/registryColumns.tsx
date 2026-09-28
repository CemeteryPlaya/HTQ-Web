/**
 * Готовые колонки реестров модуля: «Статус» и «Сейчас у» одинаковы во всех
 * реестрах документов, поэтому собираются здесь, а не в каждом экране.
 */
import type { TFunction } from 'i18next';

import { formatDateTime } from '../format';

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
