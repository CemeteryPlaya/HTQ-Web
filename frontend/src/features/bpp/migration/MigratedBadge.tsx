/**
 * Пометка документа, перенесённого из «Договоров» (B6.1, D-B61-8).
 *
 * Перенесённые договоры, счета и подотчёт — обычные документы модуля, с ними
 * работают дальше; пометка лишь объясняет, откуда у документа история до
 * модуля (она осталась в «Договорах») и почему номер по документу мог
 * быть обрезан. В реестре — значок у номера, в карточке — строка над формой.
 */
import { useTranslation } from 'react-i18next';
import { History } from 'lucide-react';

import { Badge } from '@/components/ui/badge';

export function MigratedBadge({ migrated }: { migrated?: boolean }) {
  const { t } = useTranslation();
  if (!migrated) return null;
  return (
    <Badge variant="outline" className="ml-2 font-normal">
      {t('bpp.migration.badge', 'перенесён')}
    </Badge>
  );
}

export function MigratedNote({ migrated }: { migrated?: boolean }) {
  const { t } = useTranslation();
  if (!migrated) return null;
  return (
    <p className="flex items-start gap-2 rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">
      <History className="mt-0.5 h-4 w-4 shrink-0" />
      {t('bpp.migration.note',
        'Документ перенесён из «Договоров». Его история до переноса — там, в режиме только чтения.')}
    </p>
  );
}
