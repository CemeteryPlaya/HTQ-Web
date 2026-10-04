/**
 * Кнопка действия документа модуля (ТЗ §05, §26.2; BR-060).
 *
 * - Запрос — через `useIdempotentAction`: кнопка заблокирована до ответа
 *   сервера, второй клик второго запроса не шлёт, повтор после 5xx идёт тем
 *   же `Idempotency-Key`. Хук живёт в этом компоненте, поэтому ключ
 *   переживает закрытие и повторное открытие диалога комментария.
 * - `confirm` — диалог подтверждения; с `commentMin` в нём поле
 *   комментария со счётчиком (ТЗ §13.2 «Длина текста»), и кнопка действия
 *   в диалоге неактивна, пока комментарий короче. Сервер проверяет длину сам
 *   (BR-060) — здесь лишь не даём отправить заведомый отказ.
 * - Ошибка — тостом через `reportApiError`; диалог остаётся открытым, чтобы
 *   повторить с тем же комментарием.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { Button, type ButtonProps } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { reportApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';

import { useIdempotentAction } from './useIdempotentAction';

export interface BppDocumentAction {
  label: string;
  variant?: ButtonProps['variant'];
  /** Спросить подтверждение; `commentMin` — обязательный комментарий. */
  confirm?: { title: string; description?: string; commentMin?: number };
  /** `key` — `Idempotency-Key`; `comment` — текст из диалога, если он есть. */
  run: (key: string, comment?: string) => Promise<unknown>;
}

interface Props {
  actionKey: string;
  action: BppDocumentAction;
  /** Идёт другое действие этого документа — два перехода сразу не шлём. */
  disabled?: boolean;
  onPendingChange: (actionKey: string, pending: boolean) => void;
  onDone: (actionKey: string) => void;
}

export function DocumentActionButton({
  actionKey, action, disabled = false, onPendingChange, onDone,
}: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState('');
  const { run, pending } = useIdempotentAction(
    (key) => action.run(key, action.confirm?.commentMin !== undefined ? comment.trim() : undefined),
  );

  useEffect(() => {
    onPendingChange(actionKey, pending);
    // Кнопка исчезает вместе со сменой статуса (после «Оплачено» её нет в
    // `allowed_actions`) и размонтируется, пока действие ещё «идёт»: без
    // сброса `busy[actionKey]` остался бы true, и соседние действия
    // документа («Запросить закрывающие») были бы закрыты до перезагрузки.
    return () => onPendingChange(actionKey, false);
  }, [actionKey, pending, onPendingChange]);

  const execute = () => {
    run().then(
      () => {
        setOpen(false);
        setComment('');
        onDone(actionKey);
      },
      (error: unknown) => {
        reportApiError(error, t('bpp.document.actionFailed', 'Не удалось выполнить действие'));
      },
    );
  };

  const commentMin = action.confirm?.commentMin;
  const length = comment.trim().length;
  const commentShort = commentMin !== undefined && length < commentMin;

  return (
    <>
      <Button
        type="button"
        variant={action.variant ?? 'default'}
        disabled={disabled || pending}
        aria-busy={pending || undefined}
        onClick={() => (action.confirm ? setOpen(true) : execute())}
      >
        {pending && !open && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
        {action.label}
      </Button>

      {action.confirm && (
        <Dialog open={open} onOpenChange={(next) => { if (!pending) setOpen(next); }}>
          {/* Без описания — явный `aria-describedby={undefined}`: так Radix
              понимает, что описания нет намеренно. */}
          <DialogContent
            {...(action.confirm.description ? {} : { 'aria-describedby': undefined })}
          >
            <DialogHeader>
              <DialogTitle>{action.confirm.title}</DialogTitle>
              {action.confirm.description && (
                <DialogDescription>{action.confirm.description}</DialogDescription>
              )}
            </DialogHeader>

            {commentMin !== undefined && (
              <div className="space-y-1.5">
                <Label htmlFor={`bpp-action-comment-${actionKey}`}>
                  {t('bpp.document.comment', 'Комментарий')}
                </Label>
                <Textarea
                  id={`bpp-action-comment-${actionKey}`}
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  disabled={pending}
                  rows={4}
                  aria-invalid={commentShort && length > 0 ? true : undefined}
                />
                <p
                  className={cn(
                    'text-xs',
                    commentShort ? 'text-destructive' : 'text-muted-foreground',
                  )}
                  aria-live="polite"
                >
                  {t('bpp.document.commentCounter', 'Минимум {{min}} символов, сейчас {{count}}', {
                    min: commentMin,
                    count: length,
                  })}
                </p>
              </div>
            )}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={pending}
                onClick={() => setOpen(false)}
              >
                {t('bpp.document.cancel', 'Отмена')}
              </Button>
              <Button
                type="button"
                variant={action.variant ?? 'default'}
                disabled={pending || commentShort}
                onClick={execute}
              >
                {pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
                {action.label}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
