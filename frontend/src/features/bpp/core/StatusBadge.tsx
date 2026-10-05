/**
 * Бейдж статуса документа модуля БЗО (ТЗ §15, шапка формы §05, колонка
 * «Статус» реестров §19).
 *
 * Словари статусов — в `statusDictionaries.ts` (react-refresh требует, чтобы
 * файл компонента экспортировал только компоненты). Неизвестный код —
 * нейтральный бейдж с самим кодом: новый статус сервера виден сразу, а не
 * прячется под чужой подписью.
 */
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

import { STATUS_DICTIONARIES, type StatusDef, type StatusKind, type StatusTone } from './statusDictionaries';

export type { StatusKind, StatusTone } from './statusDictionaries';

const TONE_CLASS: Record<StatusTone, string> = {
  draft: 'border-transparent bg-secondary text-secondary-foreground',
  progress: 'border-transparent bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200',
  attention: 'border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  success: 'border-transparent bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200',
  danger: 'border-transparent bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200',
  muted: 'border-transparent bg-muted text-muted-foreground',
};

interface Props {
  kind: StatusKind;
  status: string;
  className?: string;
}

export function StatusBadge({ kind, status, className }: Props) {
  const { t } = useTranslation();
  const dictionary: Record<string, StatusDef> = STATUS_DICTIONARIES[kind];
  const def = Object.prototype.hasOwnProperty.call(dictionary, status)
    ? dictionary[status]
    : undefined;
  if (!def) {
    return (
      <Badge
        variant="outline"
        className={cn('font-mono font-normal', className)}
        data-tone="unknown"
        title={t('bpp.status.unknown', 'Статус, неизвестный интерфейсу')}
      >
        {status || '—'}
      </Badge>
    );
  }
  return (
    <Badge className={cn(TONE_CLASS[def.tone], className)} data-tone={def.tone}>
      {t(def.labelKey, def.label)}
    </Badge>
  );
}
