/**
 * Диалог решения по запросу согласования.
 *
 * Решений три, и разница между двумя отрицательными — в судьбе ОБЪЕКТА, а
 * не в механике: «отклонить» значит «документ не годится» и оставляет его
 * запертым, «вернуть на доработку» — открывает его автору для правки. Круг
 * закрывают оба одинаково.
 *
 * Комментарий обязателен у обоих отрицательных всегда, а при СОГЛАСИИ —
 * только если этап помечен `requiresComment` (`ProcessStage.requires_comment`).
 * Отказ и возврат без объяснения нечего дорабатывать: инициатор увидит
 * состояние и не узнает, что исправить. Согласие в объяснении по умолчанию
 * не нуждается — но этап может его потребовать, и тогда гейт бэкенда
 * (`engine.act` → `CommentRequired`) отобьёт пустой комментарий 409-м; форма
 * лишь спрашивает то же заранее.
 *
 * Документ (`requiresAttachment`) — так же: нужен только при СОГЛАСИИ.
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
import { Check, FileText, Loader2, Paperclip, Undo2, X } from 'lucide-react';
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

export type DecisionKind = 'approve' | 'reject' | 'rework';

/** Всё, чем решения отличаются друг от друга в этом диалоге. Таблицей, а не
 *  цепочкой тернарников по `kind`: их набралось бы семь на каждое новое
 *  решение, и половину неизбежно забыли бы дописать. */
const KINDS: Record<
  DecisionKind,
  {
    title: string;
    action: string;
    toast: string;
    variant: 'default' | 'destructive' | 'outline';
    /** Пусто — комментарий необязателен. */
    commentRequired?: string;
    warning?: string;
    placeholder: string;
  }
> = {
  approve: {
    title: 'Согласовать',
    action: 'Согласовать',
    toast: 'Согласовано',
    variant: 'default',
    placeholder: 'Замечания, если есть',
  },
  reject: {
    title: 'Отклонить согласование',
    action: 'Отклонить',
    toast: 'Отклонено',
    variant: 'destructive',
    commentRequired: 'Укажите причину — инициатору нужно понимать, почему отказ.',
    warning:
      'Отказ на любом этапе закрывает весь процесс сразу — оставшиеся запросы '
      + 'гаснут. Объект при этом остаётся закрытым для правки: если его нужно '
      + 'переделать, выберите «На доработку».',
    placeholder: 'Почему документ не годится',
  },
  rework: {
    title: 'Вернуть на доработку',
    action: 'На доработку',
    toast: 'Возвращено на доработку',
    variant: 'outline',
    commentRequired: 'Укажите, что исправить — за этим автора и возвращают.',
    warning:
      'Процесс закроется сразу, оставшиеся запросы погаснут, а объект '
      + 'откроется автору для правки. Доработанный он отправляется заново — '
      + 'новым кругом согласования.',
    placeholder: 'Что нужно исправить',
  },
};

export interface DecisionTarget {
  taskId: number;
  kind: DecisionKind;
  subjectLabel: string;
  /** Этап требует приложенного PDF (`ProcessStage.requires_attachment`). */
  requiresAttachment?: boolean;
  /** Этап требует пояснения к решению (`ProcessStage.requires_comment`).
   *  Действует только при согласии — у отказа и доработки комментарий
   *  обязателен и так. */
  requiresComment?: boolean;
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

  const kind = target ? KINDS[target.kind] : null;
  const isApprove = target?.kind === 'approve';
  // Документ нужен только при СОГЛАСИИ — так же устроен гейт на бэкенде:
  // подписывать нечего ни отказом, ни возвратом на доработку.
  const needsDocument = Boolean(target?.requiresAttachment) && isApprove;
  const alreadyAttached = Boolean(target?.attachedFileId);
  // Пояснение обязательно у отказа и доработки всегда (`kind.commentRequired`),
  // а у согласия — если этого требует этап. Одно эффективное правило: и подпись
  // поля, и проверка на отправке смотрят на него.
  const commentRequiredMessage =
    kind?.commentRequired
    ?? (Boolean(target?.requiresComment) && isApprove
      ? 'На этом этапе согласование возможно только с пояснением к решению.'
      : undefined);
  const needsComment = Boolean(commentRequiredMessage);

  const mutation = useMutation({
    mutationFn: async ({
      taskId,
      decision,
    }: {
      taskId: number;
      decision: DecisionKind;
    }) => {
      // Порядок обязателен: решение без загруженного документа бэкенд
      // отобьёт 409 «сначала загрузите PDF».
      if (file) await signoffApi.attachDocument(taskId, file);
      const { data } = await signoffApi.decide(taskId, { decision, comment });
      return data;
    },
    onSuccess: (process) => {
      toast.success(kind?.toast ?? 'Решение отправлено');
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
    if (!target || !kind) return;
    if (needsComment && !comment.trim()) {
      setError(commentRequiredMessage!);
      return;
    }
    if (needsDocument && !file && !alreadyAttached) {
      setError('На этом этапе согласование возможно только с приложенным PDF.');
      return;
    }
    setError('');
    mutation.mutate({ taskId: target.taskId, decision: target.kind });
  };

  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{kind?.title}</DialogTitle>
          <DialogDescription>
            {target?.subjectLabel}
            {kind?.warning && (
              <span
                className={`block mt-2 ${
                  target?.kind === 'reject' ? 'text-destructive' : ''
                }`}
              >
                {kind.warning}
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
            Комментарий{needsComment ? '' : ' (необязательно)'}
          </Label>
          <Textarea
            id="signoff-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={2000}
            rows={4}
            placeholder={kind?.placeholder}
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
            variant={kind?.variant ?? 'default'}
            onClick={submit}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : target?.kind === 'approve' ? (
              <Check className="mr-2 h-4 w-4" />
            ) : target?.kind === 'rework' ? (
              <Undo2 className="mr-2 h-4 w-4" />
            ) : (
              <X className="mr-2 h-4 w-4" />
            )}
            {kind?.action}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
