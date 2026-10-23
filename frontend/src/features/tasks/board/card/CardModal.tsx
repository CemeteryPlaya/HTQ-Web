/**
 * Окно карточки поверх доски (решение K-19, Trello): слева — название,
 * «Добавить» (метки, даты, чек-лист, участники), участники, метки, даты,
 * приоритет, запросы доступа, описание, чек-листы; справа — «Комментарии и
 * события». Адрес — `?card=<id>`; «назад» и Esc закрывают. Кнопки — по
 * `can` карточки: права решает сервер.
 */
import { useEffect, useState } from 'react';
import { format, parseISO } from 'date-fns';
import { enUS, ru } from 'date-fns/locale';
import { CheckCircle2, Circle, Clock, Eye, EyeOff, Flag, Plus, Tag, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import { UserAvatar } from '@/components/ui/UserAvatar';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { errorStatus } from '@/lib/apiError';
import { priorityHex, priorityLabel, TASK_PRIORITY_ORDER } from '@/lib/tasks/priority';
import { canTransition } from '@/lib/tasks/transitions';
import { cn } from '@/lib/utils';
import type { Task, TaskStatus } from '@/types/tasks';

import { swatchStyle } from '../boardColors';
import { dueTone, useColumnTitle } from '../boardUtils';
import { useMarkSeen } from '../hooks/useBoard';
import type { BoardColumn } from '../types';
import { AccessRequestsBlock } from './AccessRequests';
import { ActivityFeed } from './ActivityFeed';
import { CardButton } from './CardButton';
import { ChecklistBlock } from './ChecklistBlock';
import { DatesPopover } from './DatesPopover';
import { EditableText } from './EditableText';
import { useCard, useCardPeople, useChecklistActions, useUpdateCard } from './hooks';
import { LabelsPopover } from './LabelsPopover';
import { MembersPopover } from './MembersPopover';
import { MovePopover } from './MovePopover';

export interface CardModalProps {
  taskId: number;
  columns: Array<Pick<BoardColumn, 'status' | 'title' | 'color' | 'hidden'>>;
  onClose: () => void;
  onMove: (task: Task, status: TaskStatus) => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <h4 className="text-xs font-semibold text-muted-foreground">{title}</h4>
      {children}
    </div>
  );
}

function NewChecklist({ onCreate, disabled }: { onCreate: (title: string) => void; disabled: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  useEffect(() => { if (open) setTitle(t('tasks.checklist.defaultTitle', 'Чек-лист')); }, [open, t]);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={disabled}>
        <CardButton><Plus className="mr-1.5 h-4 w-4" />
          {t('tasks.card.add.checklist', 'Чек-лист')}
        </CardButton>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 space-y-2 p-3">
        <p className="text-center text-sm font-semibold">{t('tasks.checklist.new', 'Добавить чек-лист')}</p>
        <Input autoFocus value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && title.trim()) { onCreate(title.trim()); setOpen(false); }
          }} />
        <Button size="sm" className="w-full" disabled={!title.trim()}
          onClick={() => { onCreate(title.trim()); setOpen(false); }}>
          {t('tasks.checklist.add', 'Добавить')}
        </Button>
      </PopoverContent>
    </Popover>
  );
}

function CardBody({ task, columns, onMove }: { task: Task } & Pick<CardModalProps, 'columns' | 'onMove'>) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language?.startsWith('en') ? enUS : ru;
  // Как значок срока на доске; год — только если не текущий.
  const dateLabel = (iso: string) => {
    const date = parseISO(iso);
    return format(date, date.getFullYear() === new Date().getFullYear() ? 'd MMM' : 'd MMM yyyy', { locale });
  };
  const { activeProfile } = useActiveProfile();
  const myId = Number(activeProfile?.id);
  const columnTitle = useColumnTitle();
  const update = useUpdateCard(task.id);
  const people = useCardPeople(task.id);
  const checklists = useChecklistActions(task.id);
  const full = Boolean(task.can?.full_edit);
  const soft = Boolean(task.can?.soft_edit);
  const column = columns.find((item) => item.status === task.status)
    ?? { status: task.status, title: null, color: null, hidden: false };
  const done = task.status === 'done';
  const canComplete = soft && !done && canTransition(task.status, 'done');
  const watching = (task.watchers ?? []).some((row) => row.user_id === myId);
  const tone = dueTone({ due_date: task.due_date, status: task.status });
  const labelIds = task.labels.map((label) => label.id);

  return (
    <div className="grid min-h-0 flex-1 md:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-h-0 space-y-5 overflow-y-auto p-5">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <MovePopover status={task.status} columns={columns} disabled={!soft}
            onMove={(status) => onMove(task, status)}
            trigger={(
              <button type="button" disabled={!soft}
                className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs font-medium hover:bg-muted/70 disabled:cursor-default">
                <span className="h-2.5 w-2.5 rounded-sm border"
                  style={column.color ? swatchStyle(column.color) : undefined} />
                {columnTitle(column)}
              </button>
            )} />
          <span className="text-xs text-muted-foreground">{task.key}</span>
          <Button variant="ghost" size="sm" className="ml-auto h-7"
            onClick={() => people.watch.mutate(!watching)} disabled={people.watch.isPending}>
            {watching ? <EyeOff className="mr-1.5 h-4 w-4" /> : <Eye className="mr-1.5 h-4 w-4" />}
            {watching ? t('tasks.card.unwatch', 'Не наблюдать') : t('tasks.card.watch', 'Наблюдать')}
          </Button>
        </div>

        <div className="flex items-start gap-2">
          {(done || canComplete) && (
            <button type="button" disabled={done} onClick={() => onMove(task, 'done')}
              className={cn('mt-1.5 shrink-0', done ? 'text-board-done' : 'text-muted-foreground hover:text-foreground')}
              aria-label={done ? t('tasks.board.card.completed', 'Выполнена')
                : t('tasks.board.card.complete', 'Отметить выполненной')}>
              {done ? <CheckCircle2 className="h-5 w-5" /> : <Circle className="h-5 w-5" />}
            </button>
          )}
          <div className="min-w-0 flex-1 text-xl font-semibold">
            <EditableText singleLine value={task.summary} canEdit={full} maxLength={500}
              label={t('tasks.card.title', 'Название задачи')}
              onSave={(summary) => update.mutate({ summary })} />
          </div>
        </div>

        {(full || soft) && (
          <div className="flex flex-wrap gap-2">
            <LabelsPopover selected={labelIds} disabled={!full}
              onChange={(ids) => update.mutate({ label_ids: ids })}
              trigger={<CardButton disabled={!full}>
                <Tag className="mr-1.5 h-4 w-4" />{t('tasks.card.add.labels', 'Метки')}</CardButton>} />
            <DatesPopover startDate={task.start_date} dueDate={task.due_date} disabled={!full}
              onSave={(dates) => update.mutate(dates)}
              trigger={<CardButton disabled={!full}>
                <Clock className="mr-1.5 h-4 w-4" />{t('tasks.card.add.dates', 'Даты')}</CardButton>} />
            <NewChecklist disabled={!soft} onCreate={(title) => checklists.create.mutate(title)} />
            <MembersPopover assignees={task.assignees ?? []} disabled={!full}
              onChange={(crew) => people.assignees.mutate(crew)}
              trigger={<CardButton disabled={!full}>
                <Users className="mr-1.5 h-4 w-4" />{t('tasks.card.add.members', 'Участники')}</CardButton>} />
          </div>
        )}

        <div className="flex flex-wrap gap-x-6 gap-y-4">
          <Section title={t('tasks.card.members.title', 'Участники')}>
            <div className="flex items-center gap-1">
              {(task.assignees ?? []).map((row) => (
                <span key={row.user_id} title={row.name ?? undefined}
                  className={cn('rounded-full', row.role === 'primary' && 'ring-2 ring-primary')}>
                  <UserAvatar url={row.avatar_url} name={row.name} size={32} />
                </span>
              ))}
              {(task.assignees ?? []).length === 0 && (
                <span className="text-sm text-muted-foreground">{t('tasks.card.members.none', 'Нет исполнителей')}</span>
              )}
              {full && (
                <MembersPopover assignees={task.assignees ?? []}
                  onChange={(crew) => people.assignees.mutate(crew)}
                  trigger={<button type="button" aria-label={t('tasks.card.members.add', 'Добавить участника')}
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-muted hover:bg-muted/70">
                    <Plus className="h-4 w-4" /></button>} />
              )}
            </div>
          </Section>
          {task.supervisor_name && (
            <Section title={t('tasks.card.supervisor', 'Руководитель')}>
              <span className="text-sm">{task.supervisor_name}</span>
            </Section>
          )}
          <Section title={t('tasks.card.labels.title', 'Метки')}>
            <div className="flex flex-wrap items-center gap-1">
              {task.labels.map((label) => (
                <span key={label.id} className="h-8 rounded px-3 text-sm font-medium leading-8 text-white"
                  style={{ backgroundColor: label.color }}>{label.name}</span>
              ))}
              {full && (
                <LabelsPopover selected={labelIds} onChange={(ids) => update.mutate({ label_ids: ids })}
                  trigger={<button type="button" aria-label={t('tasks.card.labels.edit', 'Изменить метки')}
                    className="flex h-8 w-8 items-center justify-center rounded bg-muted hover:bg-muted/70">
                    <Plus className="h-4 w-4" /></button>} />
              )}
              {!full && task.labels.length === 0 && <span className="text-sm text-muted-foreground">—</span>}
            </div>
          </Section>
          <Section title={t('tasks.card.dates.title', 'Даты')}>
            <DatesPopover startDate={task.start_date} dueDate={task.due_date} disabled={!full}
              onSave={(dates) => update.mutate(dates)}
              trigger={(
                <button type="button" disabled={!full}
                  className={cn('inline-flex h-8 items-center gap-1.5 rounded px-2 text-sm',
                    tone === 'overdue' ? 'bg-board-overdue text-white'
                      : tone === 'soon' ? 'bg-board-soon text-black'
                        : tone === 'done' ? 'bg-board-done text-white' : 'bg-muted')}>
                  <Clock className="h-4 w-4" />
                  {task.start_date || task.due_date
                    ? `${task.start_date ? dateLabel(task.start_date) : '…'} — ${task.due_date ? dateLabel(task.due_date) : '…'}`
                    : t('tasks.card.dates.none', 'Без дат')}
                </button>
              )} />
          </Section>
          <Section title={t('tasks.card.priority', 'Приоритет')}>
            <DropdownMenu>
              <DropdownMenuTrigger asChild disabled={!full}>
                <button type="button" disabled={!full}
                  className="inline-flex h-8 items-center gap-1.5 rounded px-2 text-sm font-medium"
                  style={{ backgroundColor: `${priorityHex(task.priority)}2b`, color: priorityHex(task.priority) }}>
                  <Flag className="h-4 w-4" />{priorityLabel(task.priority, t)}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                {TASK_PRIORITY_ORDER.map((priority) => (
                  <DropdownMenuItem key={priority} onSelect={() => update.mutate({ priority })}>
                    <span className="mr-2 h-2.5 w-2.5 rounded-full"
                      style={{ backgroundColor: priorityHex(priority) }} />
                    {priorityLabel(priority, t)}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </Section>
        </div>

        <AccessRequestsBlock task={task} myId={myId} />

        <Section title={t('tasks.card.description', 'Описание')}>
          <EditableText value={task.description ?? ''} canEdit={full} maxLength={20000}
            label={t('tasks.card.description', 'Описание')}
            placeholder={full ? t('tasks.card.descriptionPlaceholder', 'Добавьте подробное описание…')
              : t('tasks.card.noDescription', 'Описания нет')}
            className="min-h-[3rem] px-2 py-1.5 text-sm"
            onSave={(description) => update.mutate({ description })} />
        </Section>

        {(task.checklists ?? []).map((checklist) => (
          <ChecklistBlock key={checklist.id} taskId={task.id} checklist={checklist}
            canEdit={soft} canDelete={full} />
        ))}
      </div>
      <div className="min-h-0 overflow-y-auto border-t bg-muted/40 p-5 md:border-l md:border-t-0">
        <ActivityFeed taskId={task.id} canComment={Boolean(task.can?.comment ?? true)} />
      </div>
    </div>
  );
}

export function CardModal({ taskId, columns, onClose, onMove }: CardModalProps) {
  const { t } = useTranslation();
  const { data: task, isLoading, error } = useCard(taskId);
  useMarkSeen(taskId);

  useEffect(() => {
    if (error && errorStatus(error) === 404) {
      toast.error(t('tasks.card.unavailable', 'Карточка недоступна: задачи нет или она вам не видна'));
      onClose();
    }
  }, [error, onClose, t]);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
        className="flex h-[100dvh] max-w-none flex-col gap-0 p-0 sm:h-[min(90dvh,880px)] sm:max-w-[min(1100px,96vw)] sm:rounded-xl"
        // Esc в поле ввода отменяет правку, а не закрывает окно (как в Trello):
        // Radix ловит Esc раньше поля, поэтому закрытие здесь и отменяется,
        // а правку сбрасывает обработчик самого поля.
        onEscapeKeyDown={(event) => {
          const active = document.activeElement;
          if (active instanceof HTMLTextAreaElement || active instanceof HTMLInputElement) {
            event.preventDefault();
          }
        }}
      >
        <DialogTitle className="sr-only">{task ? `${task.key} ${task.summary}` : t('tasks.card.loading', 'Карточка')}</DialogTitle>
        <DialogDescription className="sr-only">{t('tasks.card.dialogHint', 'Окно карточки задачи')}</DialogDescription>
        {isLoading && (
          <div className="space-y-4 p-5">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-8 w-3/4" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
        {error && errorStatus(error) !== 404 && (
          <p role="alert" className="p-5 text-sm text-destructive">
            {t('tasks.card.loadFailed', 'Карточку не удалось загрузить')}
          </p>
        )}
        {task && <CardBody task={task} columns={columns} onMove={onMove} />}
      </DialogContent>
    </Dialog>
  );
}
