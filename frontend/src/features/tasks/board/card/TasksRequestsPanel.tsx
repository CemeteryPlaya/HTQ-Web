/**
 * Панель «Запросы» (решение K-32): «Ждут моего решения» — одобрить или
 * отклонить прямо из списка, «Мои запросы» — статус и отзыв, главе отдела
 * текущей доски — «История отдела» (запросы и передачи владения). Адрес —
 * `?panel=requests`: туда ведут уведомления о запросах.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { enUS, ru } from 'date-fns/locale';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { errorStatus } from '@/lib/apiError';

import { accessApi, cardKeys } from './api';
import { useAccessRequests, useRequestsInbox } from './hooks';
import type { AccessRequest, HistoryItem } from './types';

function When({ value }: { value: string | null }) {
  const { i18n } = useTranslation();
  if (!value) return null;
  const locale = i18n.language?.startsWith('en') ? enUS : ru;
  return <time className="text-xs text-muted-foreground">{format(parseISO(value), 'd MMM, HH:mm', { locale })}</time>;
}

function useLabels() {
  const { t } = useTranslation();
  return {
    kind: (kind: string) => (kind === 'execute'
      ? t('tasks.access.kind.execute', 'на исполнение') : t('tasks.access.kind.own', 'на владение')),
    status: (status: string) => ({
      pending: t('tasks.access.status.pending', 'ждёт решения'),
      approved: t('tasks.access.status.approved', 'одобрен'),
      rejected: t('tasks.access.status.rejected', 'отклонён'),
      cancelled: t('tasks.access.status.cancelled', 'отозван'),
    }[status] ?? status),
  };
}

function TaskLink({ task, onOpen }: { task: AccessRequest['task']; onOpen: (id: number) => void }) {
  return (
    <button type="button" onClick={() => onOpen(task.id)}
      className="min-w-0 text-left text-sm font-medium hover:underline">
      <span className="text-muted-foreground">{task.key}</span> {task.summary}
    </button>
  );
}

function InboxRow({ row, onOpen }: { row: AccessRequest; onOpen: (id: number) => void }) {
  const { t } = useTranslation();
  const labels = useLabels();
  const { approve, reject } = useAccessRequests(row.task.id, false);
  const busy = approve.isPending || reject.isPending;
  return (
    <li className="space-y-1.5 rounded-md border p-3">
      <TaskLink task={row.task} onOpen={onOpen} />
      <p className="text-sm">
        <span className="font-semibold">{row.requester?.name ?? `#${row.requester?.id}`}</span>
        {' — '}{t('tasks.access.requestKind', 'Доступ {{kind}}', { kind: labels.kind(row.kind) })}
      </p>
      {row.comment && <p className="whitespace-pre-wrap text-xs text-muted-foreground">{row.comment}</p>}
      <div className="flex flex-wrap gap-2 pt-1">
        {row.kind === 'execute' ? (
          <Button size="sm" disabled={busy} onClick={() => approve.mutate({ id: row.id })}>
            {t('tasks.access.makeExecutor', 'Сделать исполнителем')}
          </Button>
        ) : (
          <>
            <Button size="sm" disabled={busy} onClick={() => approve.mutate({ id: row.id, mode: 'replace' })}>
              {t('tasks.access.transferOwnership', 'Передать владение')}
            </Button>
            <Button size="sm" variant="secondary" disabled={busy}
              onClick={() => approve.mutate({ id: row.id, mode: 'delegate' })}>
              {t('tasks.access.makeDelegate', 'Сделать делегатом')}
            </Button>
          </>
        )}
        <Button size="sm" variant="ghost" disabled={busy}
          onClick={() => reject.mutate({ id: row.id, comment: '' })}>
          {t('tasks.access.reject', 'Отклонить')}
        </Button>
      </div>
    </li>
  );
}

function MineRow({ row, onOpen }: { row: AccessRequest; onOpen: (id: number) => void }) {
  const { t } = useTranslation();
  const labels = useLabels();
  const { cancel } = useAccessRequests(row.task.id, false);
  return (
    <li className="space-y-1 rounded-md border p-3">
      <TaskLink task={row.task} onOpen={onOpen} />
      <p className="text-sm">
        {t('tasks.access.requestKind', 'Доступ {{kind}}', { kind: labels.kind(row.kind) })}
        {' · '}<span className="font-medium">{labels.status(row.status)}</span>
        {row.decided_by && <> {' · '}{row.decided_by.name}</>}
      </p>
      {row.decision_comment && <p className="text-xs text-muted-foreground">{row.decision_comment}</p>}
      <div className="flex items-center justify-between gap-2">
        <When value={row.decided_at ?? row.created_at} />
        {row.status === 'pending' && (
          <Button size="sm" variant="ghost" disabled={cancel.isPending} onClick={() => cancel.mutate(row.id)}>
            {t('tasks.access.cancel', 'Отозвать')}
          </Button>
        )}
      </div>
    </li>
  );
}

const HISTORY_KINDS = ['', 'execute', 'own', 'transfer'] as const;

function History({ departmentId, onOpen }: { departmentId: number; onOpen: (id: number) => void }) {
  const { t } = useTranslation();
  const labels = useLabels();
  const [kind, setKind] = useState<(typeof HISTORY_KINDS)[number]>('');
  const filters: Record<string, string> = kind ? { kind } : {};
  const history = useQuery({
    queryKey: cardKeys.history(departmentId, filters),
    queryFn: () => accessApi.history(departmentId, filters),
  });
  const items: HistoryItem[] = history.data?.items ?? [];
  const kindTitle = (value: string) => ({
    '': t('tasks.requests.history.all', 'Всё'),
    execute: t('tasks.access.kind.execute', 'на исполнение'),
    own: t('tasks.access.kind.own', 'на владение'),
    transfer: t('tasks.requests.history.transfers', 'передачи владения'),
  }[value] ?? value);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {HISTORY_KINDS.map((value) => (
          <Button key={value || 'all'} size="sm" variant={kind === value ? 'default' : 'secondary'}
            onClick={() => setKind(value)}>{kindTitle(value)}</Button>
        ))}
      </div>
      {history.isError && (
        <p className="text-sm text-muted-foreground">
          {errorStatus(history.error) === 404
            ? t('tasks.requests.history.forbidden', 'История видна главе этого отдела.')
            : t('tasks.requests.history.failed', 'Историю не удалось загрузить.')}
        </p>
      )}
      <ul className="space-y-2">
        {items.map((item) => (item.type === 'request' ? (
          <li key={`r-${item.request.id}`} className="space-y-1 rounded-md border p-3">
            <TaskLink task={item.request.task} onOpen={onOpen} />
            <p className="text-sm">
              <span className="font-semibold">{item.request.requester?.name}</span>
              {' — '}{labels.kind(item.request.kind)}{' · '}{labels.status(item.request.status)}
              {item.request.approve_mode === 'delegate' && ` · ${t('tasks.requests.history.delegate', 'делегатом')}`}
              {item.request.replaced && ` · ${t('tasks.requests.history.replaced', 'снят: {{name}}', { name: item.request.replaced.name })}`}
            </p>
            <When value={item.at} />
          </li>
        ) : (
          <li key={`t-${item.task.id}-${item.at}`} className="space-y-1 rounded-md border p-3">
            <TaskLink task={item.task} onOpen={onOpen} />
            <p className="text-sm">
              {t('tasks.requests.history.ownerChange', 'Руководитель: {{from}} → {{to}}',
                { from: item.from?.name ?? '—', to: item.to?.name ?? '—' })}
              {item.by && ` · ${item.by.name}`}
            </p>
            <When value={item.at} />
          </li>
        )))}
      </ul>
      {!history.isLoading && !history.isError && items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('tasks.requests.history.empty', 'Запросов и передач пока не было.')}</p>
      )}
    </div>
  );
}

export function TasksRequestsPanel({ open, onOpenChange, onOpenCard, departmentId }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenCard: (taskId: number) => void;
  /** Доска отдела, где смотрящий — её администратор: показать историю. */
  departmentId: number | null;
}) {
  const { t } = useTranslation();
  const inbox = useRequestsInbox();
  const toDecide = inbox.data?.to_decide ?? [];
  const mine = inbox.data?.mine ?? [];
  const openCard = (taskId: number) => { onOpenChange(false); onOpenCard(taskId); };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
        <SheetHeader className="border-b px-4 py-3 text-left">
          <SheetTitle>{t('tasks.requests.title', 'Запросы доступа')}</SheetTitle>
          <SheetDescription className="text-xs">
            {t('tasks.requests.hint', 'Запросы на исполнение и владение задачами.')}
          </SheetDescription>
        </SheetHeader>
        <Tabs defaultValue="decide" className="flex min-h-0 flex-1 flex-col px-4 pt-3">
          <TabsList className="w-full">
            <TabsTrigger value="decide" className="flex-1">
              {t('tasks.requests.toDecide', 'Ждут решения')}{toDecide.length ? ` (${toDecide.length})` : ''}
            </TabsTrigger>
            <TabsTrigger value="mine" className="flex-1">{t('tasks.requests.mine', 'Мои')}</TabsTrigger>
            {departmentId !== null && (
              <TabsTrigger value="history" className="flex-1">{t('tasks.requests.history.title', 'История отдела')}</TabsTrigger>
            )}
          </TabsList>
          <TabsContent value="decide" className="min-h-0 flex-1 overflow-y-auto pb-4">
            <ul className="space-y-2">
              {toDecide.map((row) => <InboxRow key={row.id} row={row} onOpen={openCard} />)}
            </ul>
            {!inbox.isLoading && toDecide.length === 0 && (
              <p className="text-sm text-muted-foreground">{t('tasks.requests.noneToDecide', 'Нет запросов, которые ждут вашего решения.')}</p>
            )}
          </TabsContent>
          <TabsContent value="mine" className="min-h-0 flex-1 overflow-y-auto pb-4">
            <ul className="space-y-2">
              {mine.map((row) => <MineRow key={row.id} row={row} onOpen={openCard} />)}
            </ul>
            {!inbox.isLoading && mine.length === 0 && (
              <p className="text-sm text-muted-foreground">{t('tasks.requests.noneMine', 'Вы не отправляли запросов за последние 90 дней.')}</p>
            )}
          </TabsContent>
          {departmentId !== null && (
            <TabsContent value="history" className="min-h-0 flex-1 overflow-y-auto pb-4">
              <History departmentId={departmentId} onOpen={openCard} />
            </TabsContent>
          )}
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}
