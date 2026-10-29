/**
 * Карточка на доске (Trello): метки, название, значки, аватары. При
 * наведении — обводка, кружок «выполнено» и карандаш быстрой правки.
 * Отрисовка без перетаскивания — `Draggable` обёртывает её в колонке.
 */
import { memo } from 'react';
import { CheckCircle2, Circle, Pencil } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { UserAvatar } from '@/components/ui/UserAvatar';
import { canTransition } from '@/lib/tasks/transitions';
import { cn } from '@/lib/utils';

import { CardBadges } from './CardBadges';
import { CardLabels } from './CardLabels';
import type { BoardCard as Card } from './types';

const MAX_AVATARS = 4;

export interface BoardCardProps {
  card: Card;
  labelsExpanded: boolean;
  onToggleLabels: () => void;
  onOpen: (card: Card) => void;
  onQuickEdit: (card: Card, anchor: HTMLElement) => void;
  onComplete: (card: Card) => void;
  dragging?: boolean;
}

export const BoardCard = memo(function BoardCard({
  card, labelsExpanded, onToggleLabels, onOpen, onQuickEdit, onComplete, dragging = false,
}: BoardCardProps) {
  const { t } = useTranslation();
  const done = card.status === 'done';
  const canComplete = card.can_move && !done && canTransition(card.status, 'done');
  const shown = card.members.slice(0, MAX_AVATARS);
  const extra = card.members.length - shown.length;

  return (
    <div
      role="button"
      tabIndex={0}
      data-testid={`board-card-${card.id}`}
      onClick={() => onOpen(card)}
      onKeyDown={(event) => { if (event.key === 'Enter') onOpen(card); }}
      className={cn(
        'group relative rounded-lg bg-board-card px-2.5 py-2 text-sm text-card-foreground shadow-sm',
        'ring-1 ring-black/5 transition hover:ring-2 hover:ring-board-ring focus-visible:outline-none',
        'focus-visible:ring-2 focus-visible:ring-board-ring',
        dragging && 'rotate-3 shadow-elevated',
      )}
    >
      <CardLabels labels={card.labels} expanded={labelsExpanded} onToggle={onToggleLabels} />

      <div className="flex items-start gap-1.5 pr-6">
        {(done || canComplete) && (
          <button
            type="button"
            className={cn('mt-0.5 shrink-0 transition',
              done ? 'text-board-done' : 'w-0 overflow-hidden opacity-0 group-hover:w-4 group-hover:opacity-100')}
            aria-label={done
              ? t('tasks.board.card.completed', 'Выполнена')
              : t('tasks.board.card.complete', 'Отметить выполненной')}
            disabled={done}
            onClick={(event) => { event.stopPropagation(); onComplete(card); }}
          >
            {done ? <CheckCircle2 className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
          </button>
        )}
        <span className={cn('min-w-0 break-words leading-snug', done && 'text-muted-foreground')}>
          {card.is_new && (
            <span className="mr-1 inline-block h-2 w-2 rounded-full bg-board-ring align-middle"
              aria-label={t('tasks.board.card.new', 'Новая задача')} />
          )}
          {card.summary}
        </span>
      </div>

      <button
        type="button"
        className="absolute right-1.5 top-1.5 rounded p-1 text-muted-foreground opacity-0 transition hover:bg-muted group-hover:opacity-100 focus-visible:opacity-100"
        aria-label={t('tasks.board.card.quickEdit', 'Быстрая правка')}
        onClick={(event) => { event.stopPropagation(); onQuickEdit(card, event.currentTarget); }}
      >
        <Pencil className="h-3.5 w-3.5" />
      </button>

      <CardBadges card={card} />

      {card.members.length > 0 && (
        <div className="mt-1.5 flex justify-end -space-x-1.5">
          {shown.map((member) => (
            <span key={member.user_id} title={member.name ?? undefined}
              className="rounded-full ring-2 ring-board-card">
              <UserAvatar url={member.avatar_url} name={member.name} size={24} />
            </span>
          ))}
          {extra > 0 && (
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-muted text-[10px] ring-2 ring-board-card">
              +{extra}
            </span>
          )}
        </div>
      )}
    </div>
  );
});
