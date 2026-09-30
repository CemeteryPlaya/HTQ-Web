/**
 * «Отменить загрузку» (ТЗ §11.2): перед отменой диалог называет, сколько
 * счетов и строк она заденет (`GET bank/imports/<id>/impact`) — статусы
 * сверки этих счетов пересчитаются, а сама выписка снова загружается и
 * сверяется. Комментарий необязателен.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { reportApiError } from '@/lib/apiError';

import { useIdempotentAction } from '../core/useIdempotentAction';

import { bankImportApi, bankImportKey, type BankImportCard } from './api';

interface Props {
  card: BankImportCard;
  onClose: (done: boolean) => void;
}

export function CancelImportDialog({ card, onClose }: Props) {
  const { t } = useTranslation();
  const [comment, setComment] = useState('');
  const impact = useQuery({
    queryKey: [...bankImportKey(card.id), 'impact'],
    queryFn: () => bankImportApi.impact(card.id),
    // Число счетов не должно быть «вчерашним»: открытие диалога — новое чтение.
    gcTime: 0,
  });
  const action = useIdempotentAction((key) => bankImportApi.cancel(key, card.id, comment.trim()));

  const submit = () => {
    action.run().then(
      () => onClose(true),
      (error: unknown) => reportApiError(error, t('bpp.bank.cancelFailed', 'Не удалось отменить загрузку')),
    );
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !action.pending) onClose(false); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t('bpp.bank.cancelTitle', 'Отменить загрузку {{number}}', { number: card.number })}
          </DialogTitle>
          <DialogDescription>
            {t('bpp.bank.cancelDescription', 'Строки загрузки и их сопоставления будут сняты, статусы сверки счетов пересчитаются. Ту же выписку можно загрузить и сверить заново.')}
          </DialogDescription>
        </DialogHeader>

        {impact.isLoading && <Skeleton className="h-10 w-full" />}
        {impact.isError && (
          <p role="alert" className="text-sm text-destructive">
            {t('bpp.bank.impactError', 'Не удалось узнать, какие счета заденет отмена. Повторите позже.')}
          </p>
        )}
        {impact.data && (
          <p role="status" className="rounded-lg border border-amber-500/50 p-3 text-sm">
            {t('bpp.bank.impact', 'Отмена затронет счетов: {{invoices}}, строк выписки: {{lines}}', {
              invoices: impact.data.invoices, lines: impact.data.lines,
            })}
          </p>
        )}

        <div className="space-y-1.5">
          <Label htmlFor="cancel-comment">{t('bpp.bank.commentOptional', 'Комментарий (необязательно)')}</Label>
          <Textarea
            id="cancel-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            rows={2}
            maxLength={1000}
          />
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" disabled={action.pending} onClick={() => onClose(false)}>
            {t('bpp.bank.dialogCancel', 'Отмена')}
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={!impact.data || action.pending}
            onClick={submit}
          >
            {action.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {t('bpp.bank.cancelSubmit', 'Отменить загрузку')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
