/**
 * Диалог решения по запросу согласования.
 *
 * Решений три, и разница между двумя отрицательными — в судьбе ОБЪЕКТА, а
 * не в механике: «отклонить» значит «документ не годится» и оставляет его
 * запертым, «вернуть на доработку» — открывает его автору для правки. Круг
 * закрывают оба одинаково.
 *
 * Комментарий обязателен у обоих отрицательных. Схема бэкенда его не
 * требует нигде (`comment: str = ""`), но отказ и возврат без объяснения
 * нечего дорабатывать: инициатор увидит состояние и не узнает, что
 * исправить. Согласие в объяснении не нуждается.
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

import { reportApiError } from '@/lib/apiError';
import { useTranslation } from 'react-i18next';

export type DecisionKind = 'approve' | 'reject' | 'rework';

/** Всё, чем решения отличаются друг от друга в этом диалоге. Таблицей, а не
 *  цепочкой тернарников по `kind`: их набралось бы семь на каждое новое
 *  решение, и половину неизбежно забыли бы дописать. */
const KINDS: Record<
  DecisionKind,
  {
    titleKey: string;
    actionKey: string;
    toastKey: string;
    variant: 'default' | 'destructive' | 'outline';
    /** Пусто — комментарий необязателен. */
    commentRequiredKey?: string;
    warningKey?: string;
    placeholderKey: string;
  }
> = {
  approve: {
    titleKey: 'signoff.decision.approve.title',
    actionKey: 'signoff.decision.approve.action',
    toastKey: 'signoff.decision.approve.toast',
    variant: 'default',
    placeholderKey: 'signoff.decision.approve.placeholder',
  },
  reject: {
    titleKey: 'signoff.decision.reject.title',
    actionKey: 'signoff.decision.reject.action',
    toastKey: 'signoff.decision.reject.toast',
    variant: 'destructive',
    commentRequiredKey: 'signoff.decision.reject.commentRequired',
    warningKey: 'signoff.decision.reject.warning',
    placeholderKey: 'signoff.decision.reject.placeholder',
  },
  rework: {
    titleKey: 'signoff.decision.rework.title',
    actionKey: 'signoff.decision.rework.action',
    toastKey: 'signoff.decision.rework.toast',
    variant: 'outline',
    commentRequiredKey: 'signoff.decision.rework.commentRequired',
    warningKey: 'signoff.decision.rework.warning',
    placeholderKey: 'signoff.decision.rework.placeholder',
  },
};

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
  const { t } = useTranslation();
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
      toast.success(kind ? t(kind.toastKey) : t('signoff.decision.sent'));
      onOpenChange(false);
      onDecided(process);
    },
    // 409 здесь — «запрос адресован другому», «решение уже принято»,
    // «согласование завершено», «нужен документ»; 413/415 — файл слишком
    // большой или не PDF. Во всех случаях текст объясняет причину.
    onError: (err) => reportApiError(err, t('signoff.decision.submitError')),
  });

  const pickFile = (chosen: File | null) => {
    // Проверяем здесь, хотя проверит и media_files (по magic-байтам):
    // сказать «нужен PDF» до загрузки 20 МБ дешевле для всех.
    if (chosen && chosen.type !== 'application/pdf') {
      setError(t('signoff.decision.pdfOnly'));
      setFile(null);
      if (fileInput.current) fileInput.current.value = '';
      return;
    }
    setError('');
    setFile(chosen);
  };

  const submit = () => {
    if (!target || !kind) return;
    if (kind.commentRequiredKey && !comment.trim()) {
      setError(t(kind.commentRequiredKey));
      return;
    }
    if (needsDocument && !file && !alreadyAttached) {
      setError(t('signoff.decision.pdfRequired'));
      return;
    }
    setError('');
    mutation.mutate({ taskId: target.taskId, decision: target.kind });
  };

  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{kind && t(kind.titleKey)}</DialogTitle>
          <DialogDescription>
            {target?.subjectLabel}
            {kind?.warningKey && (
              <span
                className={`block mt-2 ${
                  target?.kind === 'reject' ? 'text-destructive' : ''
                }`}
              >
                {t(kind.warningKey)}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {needsDocument && (
          <div className="space-y-2">
            <Label htmlFor="signoff-document">{t('signoff.decision.documentLabel')}</Label>
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
                  {t('signoff.decision.documentAttached')}
                </p>
              )
            )}
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="signoff-comment">
            {t('signoff.decision.comment')}
            {kind?.commentRequiredKey ? '' : t('signoff.decision.optionalSuffix')}
          </Label>
          <Textarea
            id="signoff-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={2000}
            rows={4}
            placeholder={kind && t(kind.placeholderKey)}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
          >
            {t('common.cancel')}
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
            {kind && t(kind.actionKey)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
