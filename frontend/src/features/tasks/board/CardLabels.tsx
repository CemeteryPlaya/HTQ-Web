/**
 * Метки карточки: цветные полоски, по клику — подписи на всех карточках
 * доски сразу (как в Trello). Выбор запоминается у человека в браузере.
 */
import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';

import type { CardLabel } from './types';

export function CardLabels({ labels, expanded, onToggle }: {
  labels: CardLabel[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  if (!labels.length) return null;
  return (
    <button
      type="button"
      className="mb-1.5 flex flex-wrap gap-1 text-left"
      aria-label={expanded
        ? t('tasks.board.labels.collapse', 'Свернуть подписи меток')
        : t('tasks.board.labels.expand', 'Показать подписи меток')}
      onClick={(event) => { event.stopPropagation(); onToggle(); }}
    >
      {labels.map((label) => (
        <span
          key={label.id}
          title={label.name}
          className={cn('rounded-full', expanded
            ? 'max-w-full truncate px-2 py-0.5 text-[11px] font-semibold text-white'
            : 'h-2 w-10')}
          style={{ backgroundColor: label.color }}
        >
          {expanded ? label.name : null}
        </span>
      ))}
    </button>
  );
}
