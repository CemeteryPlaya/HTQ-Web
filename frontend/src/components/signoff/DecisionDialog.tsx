/**
 * Диалог решения по запросу согласования.
 *
 * Комментарий обязателен ТОЛЬКО при отказе. Схема бэкенда его не требует ни
 * там, ни там (`comment: str = ""`), но отказ без объяснения нечего
 * дорабатывать: инициатор увидит «отклонено» и не узнает, что исправить.
 * Согласие в объяснении не нуждается.
 *
 * Документ (`requiresAttachment`) — зеркально: нужен только при СОГЛАСИИ.
 * Так устроен и гейт на бэкенде: требовать PDF от того, кто отклоняет,
 * незачем — документа, который ему полагалось бы подписать, не существует.
 * Поэтому поле файла исчезает, стоит переключиться на отказ.
 *
 * Отправка при этом двухшаговая — `attachDocument`, затем `decide`, — потому
 * что таков контракт бэкенда (загрузка в хранилище не идёт внутри
 * транзакции, держащей блокировку процесса). Оба шага живут в ОДНОЙ мутации:
 * если файл не загрузился, решение не отправляется вовсе, и повторное
 * нажатие начинает с загрузки заново.
 *
 * Ответ на решение — карточка всего процесса, а не задачи: одно решение
 * может закрыть этап, открыть следующий и завершить процесс целиком.
 * Поэтому `onDecided` получает процесс, а инвалидация после него обновляет
 * и очередь, и списки.
 */

import { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Check, FileText, Loader2, Paperclip, X } from 'lucide-react';
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

export interface DecisionTarget {
  taskId: number;
  kind: DecisionKind;
  subjectLabel: string;
  /** Этап требует приложенного PDF (`ProcessStage.requires_attachment`). */
  requiresAttachment?: boolean;
  /** Документ, приложенный к этому запросу РАНЬШЕ: человек мог загрузить
   *  его, закрыть диалог и вернуться. Тогда файл выбирать заново не нужно —
   *  но заменить можно. */
  attachedFileId?: string | null;
}

interface Props {
  /** `null` — диалог закрыт. Пара «задача + вид решения» задаёт его целиком. */
  target: DecisionTarget | null;
  onOpenChange: (open: boolean) => void;
  onDecided: (process: ApprovalProcess) => void;
}

export function DecisionDialog({ target, onOpenChange, onDecided }: Props) {
  const [comment, setComment] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);

  // Ни комментарий, ни файл предыдущего решения не должны утечь в следующее.
  useEffect(() => {
    if (target) {
      setComment('');
      setFile(null);
      setError('');
    }
  }, [target]);

  const isReject = target?.kind === 'reject';
  const needsDocument = Boolean(target?.requiresAttachment) && !isReject;
  const alreadyAttached = Boolean(target?.attachedFileId);

  const mutation = useMutation({
    mutationFn: async ({ taskId, kind }: { taskId: number; kind: DecisionKind }) => {
      // Порядок обязателен: решение без загруженного документа бэкенд
      // отобьёт 409 «сначала загрузите PDF».
      if (file) await signoffApi.attachDocument(taskId, file);
      const { data } = await signoffApi.decide(taskId, { decision: kind, comment });
      return data;
    },
    onSuccess: (process) => {
      toast.success(target?.kind === 'approve' ? 'Согласовано' : 'Отклонено');
      onOpenChange(false);
      onDecided(process);
    },
    // 409 здесь — «запрос адресован другому», «решение уже принято»,
    // «согласование завершено», «нужен документ»; 413/415 — файл слишком
    // большой или не PDF. Во всех случаях текст объясняет причину.
    onError: (err) => reportApiError(err, 'Не удалось отправить решение'),
  });

  const pickFile = (chosen: File | null) => {
    // Проверяем здесь, хотя проверит и media_files (по magic-байтам):
    // сказать «нужен PDF» до загрузки 20 МБ дешевле для всех.
    if (chosen && chosen.type !== 'application/pdf') {
      setError('Документ принимается только в PDF.');
      setFile(null);
      if (fileInput.current) fileInput.current.value = '';
      return;
    }
    setError('');
    setFile(chosen);
  };

  const submit = () => {
    if (!target) return;
    if (isReject && !comment.trim()) {
      setError('Укажите причину — инициатору нужно понимать, что исправить.');
      return;
    }
    if (needsDocument && !file && !alreadyAttached) {
      setError('На этом этапе согласование возможно только с приложенным PDF.');
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

        {needsDocument && (
          <div className="space-y-2">
            <Label htmlFor="signoff-document">Документ (PDF)</Label>
            <input
              ref={fileInput}
              id="signoff-document"
              type="file"
              accept="application/pdf"
              onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
              disabled={mutation.isPending}
              className="block w-full text-sm text-muted-foreground
                         file:mr-3 file:rounded-md file:border-0
                         file:bg-secondary file:px-3 file:py-1.5
                         file:text-sm file:font-medium file:text-secondary-foreground"
            />
            {file ? (
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <FileText className="h-4 w-4" />
                {file.name}
              </p>
            ) : (
              alreadyAttached && (
                <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <Paperclip className="h-4 w-4" />
                  Документ уже приложен — выберите файл, чтобы заменить его.
                </p>
              )
            )}
          </div>
        )}

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
