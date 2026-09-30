/**
 * Диалог с комментарием — общий для «Подтвердить», «Отменить сопоставление»
 * и «Исключить» (BR-060: комментарий не короче 10 символов).
 *
 * Пока комментарий короче, кнопка закрыта и рядом счётчик «7 из 10». Отказ
 * сервера остаётся в диалоге: по полю (`fields` конверта D-28, например
 * `invoice_id` у «Подтвердить») — текстом под комментарием, иначе тостом
 * (`reportApiError`); введённое не теряется. Ключ `Idempotency-Key` держит
 * `useIdempotentAction`: повтор после обрыва сети идёт тем же ключом.
 */
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { errorDetail, reportApiError } from '@/lib/apiError';

import { errorFields } from '../counterparties/errors';
import { useIdempotentAction } from '../core/useIdempotentAction';

import { COMMENT_MIN } from './api';

interface Props {
  title: string;
  description?: string;
  submitLabel: string;
  destructive?: boolean;
  /** Содержимое над комментарием (например, остатки счетов). */
  children?: ReactNode;
  /** Что сказать, если сервер ответил без текста. */
  failureText: string;
  onSubmit: (comment: string, key: string) => Promise<unknown>;
  /** Закрыть диалог; `done` — действие выполнено. */
  onClose: (done: boolean) => void;
}

export function CommentDialog({
  title, description, submitLabel, destructive, children, failureText, onSubmit, onClose,
}: Props) {
  const { t } = useTranslation();
  const [comment, setComment] = useState('');
  const [fieldError, setFieldError] = useState<string | null>(null);
  const action = useIdempotentAction((key) => onSubmit(comment.trim(), key));
  const length = comment.trim().length;
  const valid = length >= COMMENT_MIN;

  const submit = () => {
    if (!valid) return;
    setFieldError(null);
    action.run().then(
      () => onClose(true),
      (error: unknown) => {
        const fields = errorFields(error);
        if (fields.length > 0) {
          setFieldError(errorDetail(error) ?? fields.map((item) => item.message).join('; '));
        } else {
          reportApiError(error, failureText);
        }
      },
    );
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !action.pending) onClose(false); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {children}
        <div className="space-y-1.5">
          <Label htmlFor="recon-comment">{t('bpp.bank.commentLabel', 'Комментарий')}</Label>
          <Textarea
            id="recon-comment"
            value={comment}
            onChange={(event) => { setComment(event.target.value); setFieldError(null); }}
            rows={3}
            maxLength={1000}
            aria-invalid={Boolean(fieldError)}
            aria-describedby="recon-comment-hint"
          />
          <p id="recon-comment-hint" className="text-xs text-muted-foreground">
            {t('bpp.bank.commentHint', 'Не короче {{min}} символов: {{count}} из {{min}}', {
              min: COMMENT_MIN, count: Math.min(length, COMMENT_MIN),
            })}
          </p>
          {fieldError && <p role="alert" className="text-sm text-destructive">{fieldError}</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" disabled={action.pending} onClick={() => onClose(false)}>
            {t('bpp.bank.dialogCancel', 'Отмена')}
          </Button>
          <Button
            type="button"
            variant={destructive ? 'destructive' : 'default'}
            disabled={!valid || action.pending}
            onClick={submit}
          >
            {action.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
