/**
 * Продление срока приёма предложений (план §4.2): новый срок позже
 * прежнего и позже текущего момента — иначе кнопка закрыта, сервер всё
 * равно проверит сам. Запрос — через `useIdempotentAction`.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useIdempotentAction } from '@/features/bpp/core/useIdempotentAction';

import { isoToLocalInput, localInputToIso } from '../core/datetime';

interface Props {
  open: boolean;
  currentDeadline: string | null;
  onOpenChange: (open: boolean) => void;
  /** Запрос продления; ошибку показывает вызывающий. */
  onExtend: (key: string, deadlineAt: string) => Promise<unknown>;
  onError: (error: unknown) => void;
}

export function ExtendDialog({ open, currentDeadline, onOpenChange, onExtend, onError }: Props) {
  const { t } = useTranslation();
  const [value, setValue] = useState(() => isoToLocalInput(currentDeadline));
  const iso = localInputToIso(value);
  const action = useIdempotentAction((key) => onExtend(key, iso as string));

  const now = Date.now();
  const current = currentDeadline ? new Date(currentDeadline).getTime() : 0;
  const moment = iso ? new Date(iso).getTime() : NaN;
  const problem = !iso
    ? t('tender.tenders.extendPick', 'Укажите новый срок')
    : moment <= current
      ? t('tender.tenders.extendLater', 'Новый срок — позже текущего')
      : moment <= now
        ? t('tender.tenders.extendFuture', 'Новый срок — в будущем')
        : null;

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!action.pending) onOpenChange(next); }}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t('tender.tenders.extendTitle', 'Продлить срок приёма предложений')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="tender-extend-deadline">{t('tender.tenders.extendNew', 'Новый срок')}</Label>
          <Input
            id="tender-extend-deadline" type="datetime-local" value={value}
            onChange={(event) => setValue(event.target.value)}
          />
          {problem && <p className="text-xs text-destructive">{problem}</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={action.pending} onClick={() => onOpenChange(false)}>
            {t('tender.common.cancel', 'Отмена')}
          </Button>
          <Button
            type="button" disabled={Boolean(problem) || action.pending}
            onClick={() => action.run().then(() => onOpenChange(false), onError)}
          >
            {action.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {t('tender.tenders.extend', 'Продлить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
