/**
 * Отказ 409 `E-CON-01`: документ изменили с тех пор, как его открыли (другой
 * пользователь, другая вкладка или слушатель статусов БЗО). Повторять тем
 * же `version` бессмысленно — нужно перечитать документ. Распознаёт отказ
 * `conflict.ts::isConflict`; текст — свой у каждого документа.
 */
import { useTranslation } from 'react-i18next';
import { RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';

export function ConflictAlert({ message, onReload }: { message: string; onReload: () => void }) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm"
    >
      <span>{message}</span>
      <Button type="button" size="sm" variant="outline" onClick={onReload}>
        <RefreshCw className="mr-1.5 h-4 w-4" />
        {t('tender.common.reload', 'Обновить')}
      </Button>
    </div>
  );
}
