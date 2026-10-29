/**
 * Бейдж статуса документа тендерного модуля: заявки (`request`, по
 * умолчанию), тендера (`tender`) или приглашения (`invitation`).
 * Неизвестный интерфейсу код показывается как есть, моноширинным: выдумать
 * подпись хуже, чем показать код сервера.
 */
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

import { STATUS_DICTIONARIES, TONE_CLASS, type TenderStatusKind } from './statuses';

interface Props {
  status: string;
  kind?: TenderStatusKind;
  className?: string;
}

export function TenderStatusBadge({ status, kind = 'request', className }: Props) {
  const { t } = useTranslation();
  const dictionary = STATUS_DICTIONARIES[kind];
  const def = Object.prototype.hasOwnProperty.call(dictionary, status) ? dictionary[status] : undefined;
  if (!def) {
    return (
      <Badge variant="outline" className={cn('font-mono font-normal', className)} data-tone="unknown">
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
