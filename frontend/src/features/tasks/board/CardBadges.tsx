/**
 * Значки карточки (Trello): срок (красный — просрочен, жёлтый — ≤ 2 дней,
 * зелёный — выполнено), описание, комментарии, вложения, чек-лист «3/7»
 * (зелёный при полном) и приоритет.
 */
import { format, parseISO } from 'date-fns';
import { enUS, ru } from 'date-fns/locale';
import { AlignLeft, CheckSquare, Clock, MessageSquare, Paperclip } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { priorityHex, priorityLabel } from '@/lib/tasks/priority';
import { cn } from '@/lib/utils';

import { dueTone, type DueTone } from './boardUtils';
import type { BoardCard } from './types';

const DUE_CLASS: Record<DueTone, string> = {
  overdue: 'bg-board-overdue text-white',
  soon: 'bg-board-soon text-black',
  done: 'bg-board-done text-white',
  normal: 'text-muted-foreground',
};

export function CardBadges({ card }: { card: BoardCard }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language?.startsWith('en') ? enUS : ru;
  const tone = dueTone(card);
  const { checklist_done: done, checklist_total: total, comments, attachments } = card.counts;

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      {tone && card.due_date && (
        <span
          className={cn('inline-flex items-center gap-1 rounded px-1.5 py-0.5', DUE_CLASS[tone])}
          title={t('tasks.board.badge.due', 'Срок')}
        >
          <Clock className="h-3 w-3" />
          {format(parseISO(card.due_date), 'd MMM', { locale })}
        </span>
      )}
      {card.has_description && (
        <AlignLeft className="h-3.5 w-3.5 text-muted-foreground"
          aria-label={t('tasks.board.badge.description', 'Есть описание')} />
      )}
      {comments > 0 && (
        <span className="inline-flex items-center gap-1 text-muted-foreground"
          title={t('tasks.board.badge.comments', 'Комментарии')}>
          <MessageSquare className="h-3.5 w-3.5" />{comments}
        </span>
      )}
      {attachments > 0 && (
        <span className="inline-flex items-center gap-1 text-muted-foreground"
          title={t('tasks.board.badge.attachments', 'Вложения')}>
          <Paperclip className="h-3.5 w-3.5" />{attachments}
        </span>
      )}
      {total > 0 && (
        <span
          className={cn('inline-flex items-center gap-1 rounded px-1.5 py-0.5',
            done === total ? 'bg-board-done text-white' : 'text-muted-foreground')}
          title={t('tasks.board.badge.checklist', 'Чек-лист')}
        >
          <CheckSquare className="h-3.5 w-3.5" />{done}/{total}
        </span>
      )}
      <span
        className="rounded px-1.5 py-0.5 font-medium"
        style={{ backgroundColor: `${priorityHex(card.priority)}2b`, color: priorityHex(card.priority) }}
      >
        {t('tasks.board.badge.priority', 'Приоритет')}: {priorityLabel(card.priority, t)}
      </span>
    </div>
  );
}
