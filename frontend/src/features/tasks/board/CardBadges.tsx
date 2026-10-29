/**
 * Значки карточки (Trello): срок (красный — просрочен, жёлтый — ≤ 2 дней,
 * зелёный — выполнено), описание, комментарии, вложения, чек-лист «3/7»
 * (зелёный при полном), приоритет и свои поля «на карточке» (этап S3).
 */
import { format, parseISO } from 'date-fns';
import { enUS, ru } from 'date-fns/locale';
import { AlignLeft, CheckSquare, Clock, MessageSquare, Paperclip } from 'lucide-react';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

import { priorityHex, priorityLabel } from '@/lib/tasks/priority';
import { cn } from '@/lib/utils';

import { chipStyle } from './boardColors';
import { dueTone, type DueTone } from './boardUtils';
import { fieldDate, fieldNumber } from './fields/fieldFormat';
import type { BoardCard, CardFieldBadge } from './types';

const DUE_CLASS: Record<DueTone, string> = {
  overdue: 'bg-board-overdue text-white',
  soon: 'bg-board-soon text-black',
  done: 'bg-board-done text-white',
  normal: 'text-muted-foreground',
};

/** Подпись значка поля: у списка — вариант, у флажка — само название. */
function fieldText(badge: CardFieldBadge, t: TFunction, language: string | undefined): string {
  if (badge.type === 'list') return badge.option?.name ?? '';
  if (badge.type === 'checkbox') return badge.name;
  const value = String(badge.value);
  const shown = badge.type === 'date' ? fieldDate(value, language)
    : badge.type === 'number' ? fieldNumber(value, language)
      : value.length > 40 ? `${value.slice(0, 40)}…` : value;
  return t('tasks.board.badge.field', '{{name}}: {{value}}', { name: badge.name, value: shown });
}

export function CardBadges({ card }: { card: BoardCard }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language?.startsWith('en') ? enUS : ru;
  const tone = dueTone(card);
  const { checklist_done: done, checklist_total: total, comments, attachments } = card.counts;
  // Обычный приоритет на карточке не пишем: значок на каждой карточке —
  // шум, который глушит срочные.
  const showPriority = card.priority !== 'medium';
  const fields = card.fields ?? [];
  if (!tone && !card.has_description && !comments && !attachments && !total && !showPriority
      && fields.length === 0) {
    return null;
  }

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
      {showPriority && (
        <span
          className="rounded px-1.5 py-0.5 font-medium"
          style={{ backgroundColor: `${priorityHex(card.priority)}2b`, color: priorityHex(card.priority) }}
        >
          {t('tasks.board.badge.priority', 'Приоритет')}: {priorityLabel(card.priority, t)}
        </span>
      )}
      {fields.map((badge) => (
        <span key={badge.id} title={badge.name}
          className={cn('inline-flex max-w-full items-center gap-1 truncate rounded px-1.5 py-0.5',
            badge.type === 'list' && !badge.option?.color ? 'bg-muted' : 'text-muted-foreground',
            badge.type === 'list' && 'text-foreground')}
          style={badge.type === 'list' ? chipStyle(badge.option?.color ?? null) : undefined}>
          {badge.type === 'checkbox' && <CheckSquare className="h-3.5 w-3.5 shrink-0" />}
          {fieldText(badge, t, i18n.language)}
        </span>
      ))}
    </div>
  );
}
