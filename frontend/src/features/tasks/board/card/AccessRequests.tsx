/**
 * Запросы доступа в окне карточки (K-31). Тому, кто видит задачу, но не в
 * роли, — «Запросить доступ» и плашка «ждёт решения» с отзывом. Решающим —
 * плашка «Запросы доступа: N» с кнопками: «на исполнение» — только заменой
 * (с именем того, кого снимут), «на владение» — заменой или делегатом.
 * Кнопки — по `can` карточки: права решает сервер.
 */
import { useState } from 'react';
import { KeyRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import type { Task, TaskAccessKind } from '@/types/tasks';

import { CardButton } from './CardButton';
import { useAccessRequests } from './hooks';
import type { AccessRequest } from './types';

function useKindText() {
  const { t } = useTranslation();
  return {
    title: (kind: TaskAccessKind) => (kind === 'execute'
      ? t('tasks.access.kind.execute', 'на исполнение') : t('tasks.access.kind.own', 'на владение')),
    hint: (kind: TaskAccessKind) => (kind === 'execute'
      ? t('tasks.access.hint.execute', 'Вы станете основным исполнителем; прежний основной исполнитель будет снят.')
      : t('tasks.access.hint.own', 'Вы станете руководителем задачи — или делегатом с полной правкой, если так решит владелец.')),
  };
}

export function RequestAccessDialog({ task, kinds, open, onOpenChange }: {
  task: Task;
  kinds: TaskAccessKind[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const text = useKindText();
  const { request } = useAccessRequests(task.id, false);
  const [kind, setKind] = useState<TaskAccessKind>(kinds[0] ?? 'execute');
  const [comment, setComment] = useState('');

  const send = async () => {
    try {
      await request.mutateAsync({ kind, comment: comment.trim() });
      setComment('');
      onOpenChange(false);
    } catch {
      // Причину показал onError мутации; окно остаётся открытым.
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('tasks.access.requestTitle', 'Запросить доступ к задаче')}</DialogTitle>
          <DialogDescription>{task.key} · {task.summary}</DialogDescription>
        </DialogHeader>
        <RadioGroup value={kind} onValueChange={(value) => setKind(value as TaskAccessKind)}
          className="space-y-2">
          {kinds.map((option) => (
            <label key={option} className="flex cursor-pointer items-start gap-3 rounded-md border p-3">
              <RadioGroupItem value={option} className="mt-0.5" />
              <span>
                <span className="block text-sm font-medium">
                  {t('tasks.access.requestKind', 'Доступ {{kind}}', { kind: text.title(option) })}
                </span>
                <span className="block text-xs text-muted-foreground">{text.hint(option)}</span>
              </span>
            </label>
          ))}
        </RadioGroup>
        <div className="space-y-1.5">
          <Label>{t('tasks.access.comment', 'Комментарий для решающих')}</Label>
          <Textarea rows={3} value={comment} maxLength={2000}
            onChange={(event) => setComment(event.target.value)} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('tasks.board.cancel', 'Отмена')}
          </Button>
          <Button onClick={() => void send()} disabled={request.isPending}>
            {t('tasks.access.send', 'Отправить запрос')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DecisionRow({ row, task }: { row: AccessRequest; task: Task }) {
  const { t } = useTranslation();
  const text = useKindText();
  const { approve, reject } = useAccessRequests(task.id, false);
  const [rejecting, setRejecting] = useState(false);
  const [comment, setComment] = useState('');
  const busy = approve.isPending || reject.isPending;
  const replacedName = row.kind === 'execute' ? task.assignee_name : task.supervisor_name;

  return (
    <li className="space-y-2 rounded-md bg-background p-3 ring-1 ring-border">
      <p className="text-sm">
        <span className="font-semibold">{row.requester?.name ?? `#${row.requester?.id}`}</span>
        {' — '}
        {t('tasks.access.requestKind', 'Доступ {{kind}}', { kind: text.title(row.kind) })}
      </p>
      {row.comment && <p className="whitespace-pre-wrap text-sm text-muted-foreground">{row.comment}</p>}
      {rejecting ? (
        <div className="space-y-2">
          <Textarea rows={2} value={comment} maxLength={2000}
            placeholder={t('tasks.access.rejectReason', 'Причина отказа (увидит запросивший)')}
            onChange={(event) => setComment(event.target.value)} />
          <div className="flex gap-2">
            <Button size="sm" variant="destructive" disabled={busy}
              onClick={() => reject.mutate({ id: row.id, comment: comment.trim() })}>
              {t('tasks.access.reject', 'Отклонить')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>
              {t('tasks.board.cancel', 'Отмена')}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {row.kind === 'execute' ? (
            <Button size="sm" disabled={busy} onClick={() => approve.mutate({ id: row.id })}>
              {replacedName
                ? t('tasks.access.replaceExecutor', 'Заменить исполнителя (снимется: {{name}})',
                  { name: replacedName })
                : t('tasks.access.makeExecutor', 'Сделать исполнителем')}
            </Button>
          ) : (
            <>
              <Button size="sm" disabled={busy}
                onClick={() => approve.mutate({ id: row.id, mode: 'replace' })}>
                {t('tasks.access.transferOwnership', 'Передать владение')}
              </Button>
              <CardButton disabled={busy}
                onClick={() => approve.mutate({ id: row.id, mode: 'delegate' })}>
                {t('tasks.access.makeDelegate', 'Сделать делегатом')}
              </CardButton>
            </>
          )}
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setRejecting(true)}>
            {t('tasks.access.reject', 'Отклонить')}
          </Button>
        </div>
      )}
    </li>
  );
}

export function AccessRequestsBlock({ task, myId }: { task: Task; myId: number }) {
  const { t } = useTranslation();
  const text = useKindText();
  const kinds = task.can?.request_access ?? [];
  const deciding = (task.pending_access_requests ?? 0) > 0;
  const { list, cancel } = useAccessRequests(task.id, true);
  const [dialog, setDialog] = useState(false);
  const rows = list.data ?? [];
  const mine = rows.filter((row) => row.status === 'pending' && row.requester?.id === myId);
  const toDecide = rows.filter((row) => row.status === 'pending' && row.requester?.id !== myId);

  if (!kinds.length && !mine.length && !(deciding && toDecide.length)) return null;
  return (
    <section className="space-y-2">
      {deciding && toDecide.length > 0 && (
        <div className="space-y-2 rounded-lg bg-amber-500/10 p-3">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <KeyRound className="h-4 w-4" />
            {t('tasks.access.banner', 'Запросы доступа: {{count}}', { count: toDecide.length })}
          </p>
          <ul className="space-y-2">
            {toDecide.map((row) => <DecisionRow key={row.id} row={row} task={task} />)}
          </ul>
        </div>
      )}
      {mine.map((row) => (
        <div key={row.id} className="flex flex-wrap items-center gap-2 rounded-lg bg-muted p-3 text-sm">
          <span className="min-w-0 flex-1">
            {t('tasks.access.pendingMine', 'Запрос доступа {{kind}} отправлен и ждёт решения',
              { kind: text.title(row.kind) })}
          </span>
          <Button size="sm" variant="ghost" disabled={cancel.isPending}
            onClick={() => cancel.mutate(row.id)}>
            {t('tasks.access.cancel', 'Отозвать')}
          </Button>
        </div>
      ))}
      {kinds.length > 0 && (
        <>
          <CardButton onClick={() => setDialog(true)}>
            <KeyRound className="mr-1.5 h-4 w-4" />
            {t('tasks.access.request', 'Запросить доступ')}
          </CardButton>
          <RequestAccessDialog task={task} kinds={kinds} open={dialog} onOpenChange={setDialog} />
        </>
      )}
    </section>
  );
}
