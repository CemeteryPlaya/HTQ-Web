/**
 * Диалог решения по запросу согласования.
 *
 * Комментарий обязателен ТОЛЬКО при отказе. Схема бэкенда его не требует ни
 * там, ни там (`comment: str = ""`), но отказ без объяснения нечего
 * дорабатывать: инициатор увидит «отклонено» и не узнает, что исправить.
 * Согласие в объяснении не нуждается.
 *
 * Ответ на решение — карточка всего процесса, а не задачи: одно решение
 * может закрыть этап, открыть следующий и завершить процесс целиком.
 * Поэтому `onDecided` получает процесс, а инвалидация после него обновляет
 * и очередь, и списки.
 */

import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Check, Loader2, X } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
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
import { signoffApi } from '@/api/signoff';
import type { ApprovalProcess } from '@/types/signoff';

import { reportApiError } from './apiError';

export type DecisionKind = 'approve' | 'reject';

interface Props {
  /** `null` — диалог закрыт. Пара «задача + вид решения» задаёт его целиком. */
  target: { taskId: number; kind: DecisionKind; subjectLabel: string } | null;
  onOpenChange: (open: boolean) => void;
  onDecided: (process: ApprovalProcess) => void;
}

export function DecisionDialog({ target, onOpenChange, onDecided }: Props) {
  const [comment, setComment] = useState('');
  const [error, setError] = useState('');

  // Комментарий к предыдущему решению не должен утечь в следующее.
  useEffect(() => {
    if (target) {
      setComment('');
      setError('');
    }
  }, [target]);

  const mutation = useMutation({
    mutationFn: ({ taskId, kind }: { taskId: number; kind: DecisionKind }) =>
      signoffApi.decide(taskId, { decision: kind, comment }).then((r) => r.data),
    onSuccess: (process) => {
      toast.success(
        target?.kind === 'approve' ? 'Согласовано' : 'Отклонено',
      );
      onOpenChange(false);
      onDecided(process);
    },
    // 409 здесь — «запрос адресован другому», «решение уже принято»,
    // «согласование завершено»: текст объясняет причину, показываем его.
    onError: (err) => reportApiError(err, 'Не удалось отправить решение'),
  });

  const isReject = target?.kind === 'reject';

  const submit = () => {
    if (!target) return;
    if (isReject && !comment.trim()) {
      setError('Укажите причину — инициатору нужно понимать, что исправить.');
      return;
    }
    setError('');
    mutation.mutate({ taskId: target.taskId, kind: target.kind });
  };

  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isReject ? 'Отклонить согласование' : 'Согласовать'}
          </DialogTitle>
          <DialogDescription>
            {target?.subjectLabel}
            {isReject && (
              <span className="block mt-2 text-destructive">
                Отказ на любом этапе отклоняет весь процесс сразу —
                оставшиеся запросы гаснут, а объект возвращается на доработку.
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="signoff-comment">
            Комментарий{isReject ? '' : ' (необязательно)'}
          </Label>
          <Textarea
            id="signoff-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={2000}
            rows={4}
            placeholder={
              isReject ? 'Что нужно исправить' : 'Замечания, если есть'
            }
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
          >
            Отмена
          </Button>
          <Button
            variant={isReject ? 'destructive' : 'default'}
            onClick={submit}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : isReject ? (
              <X className="mr-2 h-4 w-4" />
            ) : (
              <Check className="mr-2 h-4 w-4" />
            )}
            {isReject ? 'Отклонить' : 'Согласовать'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
