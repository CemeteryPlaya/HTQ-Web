/**
 * Подтверждение действия поставщика («Отозвать», «Отказаться»); с
 * `commentMin` — обязательная причина со счётчиком. Свой, а не
 * `DocumentActionButton` БЗО: тот разбирает ошибки конверта axios, а портал
 * ходит голым `fetch`.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { Button, type ButtonProps } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  confirmLabel: string;
  variant?: ButtonProps['variant'];
  commentMin?: number;
  commentLabel?: string;
  pending: boolean;
  onConfirm: (comment: string) => void;
}

export function ConfirmDialog({
  open, onOpenChange, title, description, confirmLabel, variant = 'default', commentMin,
  commentLabel, pending, onConfirm,
}: Props) {
  const { t } = useTranslation();
  const [comment, setComment] = useState('');
  const length = comment.trim().length;
  const short = commentMin !== undefined && length < commentMin;

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!pending) onOpenChange(next); }}>
      <DialogContent {...(description ? {} : { 'aria-describedby': undefined })}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {commentMin !== undefined && (
          <div className="space-y-1.5">
            <Label htmlFor="portal-confirm-comment">{commentLabel}</Label>
            <Textarea
              id="portal-confirm-comment" rows={4} className="text-base" value={comment}
              onChange={(event) => setComment(event.target.value)}
            />
            <p className={short ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'} aria-live="polite">
              {t('tender.portal.commentCounter', 'Минимум {{min}} символов, сейчас {{count}}', { min: commentMin, count: length })}
            </p>
          </div>
        )}
        <DialogFooter className="gap-2">
          <Button type="button" variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            {t('tender.portal.cancel', 'Отмена')}
          </Button>
          <Button type="button" variant={variant} disabled={pending || short} onClick={() => onConfirm(comment.trim())}>
            {pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
