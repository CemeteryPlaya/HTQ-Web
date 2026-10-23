/**
 * Общие помощники доски: соседи места вставки, тон срока, название колонки,
 * ссылка на карточку. Отдельно от компонентов — так их видят и тесты, и
 * быстрая перезагрузка Vite (файл компонента экспортирует только компоненты).
 */
import { differenceInCalendarDays, parseISO } from 'date-fns';
import { useTranslation } from 'react-i18next';

import { TASK_STATUS } from '@/lib/tasks/status';

import type { BoardCard, BoardColumn } from './types';

/** Соседи по месту вставки: `index` — позиция в целевой колонке БЕЗ
 * перетаскиваемой карточки. */
export function neighboursAt(cards: BoardCard[], movingId: number, index: number):
  { before_id: number | null; after_id: number | null } {
  const rest = cards.filter((card) => card.id !== movingId);
  return {
    before_id: index > 0 ? rest[index - 1]?.id ?? null : null,
    after_id: rest[index]?.id ?? null,
  };
}

export type DueTone = 'overdue' | 'soon' | 'done' | 'normal';

/** Цвет срока как в Trello: просрочен, скоро (≤ 2 дней), выполнено. */
export function dueTone(card: Pick<BoardCard, 'due_date' | 'status'>, today = new Date()): DueTone | null {
  if (!card.due_date) return null;
  if (card.status === 'done') return 'done';
  if (card.status === 'cancelled') return 'normal';
  const days = differenceInCalendarDays(parseISO(card.due_date), today);
  if (days < 0) return 'overdue';
  if (days <= 2) return 'soon';
  return 'normal';
}

/** Название колонки: своё у доски (K-34) или название статуса. */
export function useColumnTitle() {
  const { t } = useTranslation();
  return (column: Pick<BoardColumn, 'status' | 'title'>) =>
    column.title || t(TASK_STATUS[column.status].labelKey, column.status);
}

/** Ссылка на задачу — её страница (с окном карточки этапа S2 — `?card=`). */
export function cardLink(card: Pick<BoardCard, 'id'>): string {
  return `${window.location.origin}/tasks/${card.id}`;
}
