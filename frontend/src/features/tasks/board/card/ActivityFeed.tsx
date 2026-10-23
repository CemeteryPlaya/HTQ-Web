/**
 * «Комментарии и события» (Trello, правая панель окна карточки): поле
 * комментария сверху, лента новыми сверху, «Показать подробности» — весь
 * журнал, без него — комментарии и ключевые события (§6.4). Событие без
 * автора — работа автоматизации (этап S4). Фразы безличные: глагол в
 * прошедшем времени выдал бы род автора, которого мы не знаем.
 */
import { useState } from 'react';
import { format, parseISO } from 'date-fns';
import { enUS, ru } from 'date-fns/locale';
import { Zap } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { UserAvatar } from '@/components/ui/UserAvatar';
import { priorityLabel } from '@/lib/tasks/priority';
import { TASK_STATUS } from '@/lib/tasks/status';
import type { TaskPriority, TaskStatus } from '@/types/tasks';

import { useAddComment, useTaskFeed } from './hooks';
import type { FeedActivity, FeedEntry } from './types';

const KIND_KEYS: Record<string, [string, string]> = {
  execute: ['tasks.access.kind.execute', 'на исполнение'],
  own: ['tasks.access.kind.own', 'на владение'],
};

function useDescribe() {
  const { t } = useTranslation();
  const status = (value: string | null) => (value && value in TASK_STATUS
    ? t(TASK_STATUS[value as TaskStatus].labelKey, value) : value ?? '—');
  const kind = (value: string | null) => {
    const [key, fallback] = KIND_KEYS[(value ?? '').split(':')[0]] ?? [];
    return key ? t(key, fallback) : value ?? '';
  };
  return (entry: FeedActivity): string => {
    const oldLabel = entry.old_label ?? entry.old ?? '—';
    const newLabel = entry.new_label ?? entry.new ?? '—';
    switch (entry.field) {
      case 'status':
        return t('tasks.feed.status', 'статус: {{from}} → {{to}}',
          { from: status(entry.old), to: status(entry.new) });
      case 'claim':
        return t('tasks.feed.claim', 'задача взята в работу');
      case 'assignee_id':
        return entry.new
          ? t('tasks.feed.assignee', 'основной исполнитель — {{name}}', { name: newLabel })
          : t('tasks.feed.assigneeRemoved', 'основной исполнитель снят');
      case 'supervisor_id':
        return entry.new
          ? t('tasks.feed.supervisor', 'руководитель — {{name}}', { name: newLabel })
          : t('tasks.feed.supervisorRemoved', 'руководитель снят');
      case 'reporter_id':
        return t('tasks.feed.reporter', 'автор — {{name}}', { name: newLabel });
      case 'delegates':
        return entry.new
          ? t('tasks.feed.delegateAdded', 'делегат — {{name}}', { name: newLabel })
          : t('tasks.feed.delegateRemoved', 'делегирование снято: {{name}}', { name: oldLabel });
      case 'transfer':
        return t('tasks.feed.transfer', 'передана из отдела «{{from}}» в «{{to}}»',
          { from: oldLabel, to: newLabel });
      case 'department_id':
        return t('tasks.feed.department', 'отдел — {{name}}', { name: newLabel });
      case 'summary':
        return t('tasks.feed.summary', 'название: «{{name}}»', { name: newLabel });
      case 'description':
        return t('tasks.feed.description', 'описание изменено');
      case 'due_date':
        return entry.new ? t('tasks.feed.due', 'срок — {{date}}', { date: entry.new })
          : t('tasks.feed.dueRemoved', 'срок снят');
      case 'start_date':
        return entry.new ? t('tasks.feed.start', 'начало — {{date}}', { date: entry.new })
          : t('tasks.feed.startRemoved', 'дата начала снята');
      case 'priority':
        return t('tasks.feed.priority', 'приоритет: {{to}}',
          { to: entry.new ? priorityLabel(entry.new as TaskPriority, t) : '—' });
      case 'progress_percent':
        return t('tasks.feed.progress', 'прогресс {{value}}%', { value: newLabel });
      case 'checklist_added':
        return t('tasks.feed.checklistAdded', 'чек-лист «{{name}}» добавлен', { name: newLabel });
      case 'checklist_renamed':
        return t('tasks.feed.checklistRenamed', 'чек-лист «{{from}}» переименован в «{{to}}»',
          { from: oldLabel, to: newLabel });
      case 'checklist_deleted':
        return t('tasks.feed.checklistDeleted', 'чек-лист «{{name}}» удалён', { name: oldLabel });
      case 'checklist_item_added':
        return t('tasks.feed.itemAdded', 'пункт «{{name}}» добавлен', { name: newLabel });
      case 'checklist_item_renamed':
        return t('tasks.feed.itemRenamed', 'пункт «{{from}}» → «{{to}}»', { from: oldLabel, to: newLabel });
      case 'checklist_item_deleted':
        return t('tasks.feed.itemDeleted', 'пункт «{{name}}» удалён', { name: oldLabel });
      case 'checklist_item_checked':
        return t('tasks.feed.itemChecked', 'пункт «{{name}}» выполнен', { name: newLabel });
      case 'checklist_item_unchecked':
        return t('tasks.feed.itemUnchecked', 'пункт «{{name}}» снова не выполнен', { name: newLabel });
      case 'access_requested':
        return t('tasks.feed.accessRequested', 'запрос доступа {{kind}}', { kind: kind(entry.new) });
      case 'access_approved':
        return t('tasks.feed.accessApproved', 'запрос доступа {{kind}} одобрен', { kind: kind(entry.new) });
      case 'access_rejected':
        return t('tasks.feed.accessRejected', 'запрос доступа {{kind}} отклонён', { kind: kind(entry.new) });
      case 'access_cancelled':
        return t('tasks.feed.accessCancelled', 'запрос доступа {{kind}} отозван', { kind: kind(entry.new) });
      default:
        return t('tasks.feed.changed', '{{field}}: {{from}} → {{to}}',
          { field: entry.field, from: oldLabel, to: newLabel });
    }
  };
}

function Stamp({ value }: { value: string }) {
  const { i18n } = useTranslation();
  const locale = i18n.language?.startsWith('en') ? enUS : ru;
  return (
    <time className="text-xs text-muted-foreground" dateTime={value}>
      {format(parseISO(value), 'd MMM yyyy, HH:mm', { locale })}
    </time>
  );
}

function Entry({ entry, describe }: { entry: FeedEntry; describe: (entry: FeedActivity) => string }) {
  const { t } = useTranslation();
  const name = entry.actor?.name
    ?? (entry.actor ? `#${entry.actor.id}` : t('tasks.feed.automation', 'Автоматизация'));
  return (
    <li className="flex gap-2">
      {entry.actor ? (
        <UserAvatar url={entry.actor.avatar_url} name={entry.actor.name} size={32} />
      ) : (
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted">
          <Zap className="h-4 w-4 text-amber-500" />
        </span>
      )}
      <div className="min-w-0 flex-1">
        {entry.kind === 'comment' ? (
          <>
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-sm font-semibold">{name}</span>
              <Stamp value={entry.created_at} />
            </div>
            <p className="mt-1 whitespace-pre-wrap break-words rounded-lg bg-background px-3 py-2 text-sm shadow-sm ring-1 ring-border">
              {entry.body}
            </p>
          </>
        ) : (
          <>
            <p className="text-sm">
              <span className="font-semibold">{name}</span>
              {' · '}
              {describe(entry)}
            </p>
            <Stamp value={entry.created_at} />
          </>
        )}
      </div>
    </li>
  );
}

export function ActivityFeed({ taskId, canComment }: { taskId: number; canComment: boolean }) {
  const { t } = useTranslation();
  const [details, setDetails] = useState(false);
  const [text, setText] = useState('');
  const feed = useTaskFeed(taskId, details);
  const addComment = useAddComment(taskId);
  const describe = useDescribe();
  const entries = feed.data?.pages.flatMap((page) => page.items) ?? [];

  const send = async () => {
    const body = text.trim();
    if (!body) return;
    try {
      await addComment.mutateAsync(body);
      setText('');
    } catch {
      // Причину показал onError мутации; текст остаётся — можно повторить.
    }
  };

  return (
    <section className="space-y-3" aria-label={t('tasks.feed.title', 'Комментарии и события')}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t('tasks.feed.title', 'Комментарии и события')}</h3>
        <Button variant="secondary" size="sm" onClick={() => setDetails((value) => !value)}>
          {details ? t('tasks.feed.hideDetails', 'Скрыть подробности')
            : t('tasks.feed.showDetails', 'Показать подробности')}
        </Button>
      </div>
      {canComment && (
        <div className="space-y-2">
          <Textarea rows={2} value={text} maxLength={10000}
            placeholder={t('tasks.feed.commentPlaceholder', 'Напишите комментарий…')}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                void send();
              }
            }} />
          {text.trim() && (
            <Button size="sm" onClick={() => void send()} disabled={addComment.isPending}>
              {t('tasks.feed.send', 'Сохранить')}
            </Button>
          )}
        </div>
      )}
      {feed.isLoading && <p className="text-sm text-muted-foreground">{t('tasks.feed.loading', 'Загрузка…')}</p>}
      {feed.isError && (
        <p role="alert" className="text-sm text-destructive">
          {t('tasks.feed.loadFailed', 'Ленту не удалось загрузить')}
        </p>
      )}
      <ul className="space-y-3">
        {entries.map((entry) => (
          <Entry key={`${entry.kind}-${entry.id}`} entry={entry} describe={describe} />
        ))}
      </ul>
      {!feed.isLoading && !feed.isError && entries.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('tasks.feed.empty', 'Пока ни комментариев, ни событий.')}</p>
      )}
      {feed.hasNextPage && (
        <Button variant="ghost" size="sm" className="w-full" disabled={feed.isFetchingNextPage}
          onClick={() => void feed.fetchNextPage()}>
          {t('tasks.feed.more', 'Показать ещё')}
        </Button>
      )}
    </section>
  );
}
