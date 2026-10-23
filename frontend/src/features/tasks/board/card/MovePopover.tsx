/**
 * «Переместить» из окна карточки (Trello: чип колонки в шапке окна). Только
 * колонки, куда пускает схема переходов; названия и цвета — доски (K-34).
 * Скрытая колонка тоже предлагается: на доске её не видно, но статус есть.
 */
import { type ReactNode, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { canTransition } from '@/lib/tasks/transitions';
import type { TaskStatus } from '@/types/tasks';

import { swatchStyle } from '../boardColors';
import { useColumnTitle } from '../boardUtils';
import type { BoardColumn } from '../types';

export interface MovePopoverProps {
  status: TaskStatus;
  columns: Array<Pick<BoardColumn, 'status' | 'title' | 'color' | 'hidden'>>;
  onMove: (status: TaskStatus) => void;
  disabled?: boolean;
  trigger: ReactNode;
}

export function MovePopover({ status, columns, onMove, disabled = false, trigger }: MovePopoverProps) {
  const { t } = useTranslation();
  const columnTitle = useColumnTitle();
  const [open, setOpen] = useState(false);
  const targets = columns.filter((column) => column.status !== status
    && canTransition(status, column.status));

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={disabled}>{trigger}</PopoverTrigger>
      <PopoverContent align="start" className="w-64 space-y-1 p-2">
        <p className="pb-1 text-center text-sm font-semibold">
          {t('tasks.card.move.title', 'Переместить в колонку')}
        </p>
        {targets.map((column) => (
          <button key={column.status} type="button"
            onClick={() => { onMove(column.status); setOpen(false); }}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted">
            <span className="h-3 w-3 shrink-0 rounded-sm border"
              style={column.color ? swatchStyle(column.color) : undefined} />
            <span className="min-w-0 flex-1 truncate">{columnTitle(column)}</span>
            {column.hidden && (
              <span className="text-xs text-muted-foreground">{t('tasks.card.move.hidden', 'скрыта')}</span>
            )}
            <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        ))}
        {targets.length === 0 && (
          <p className="px-2 py-1.5 text-xs text-muted-foreground">
            {t('tasks.card.move.none', 'Из этой колонки задачу перенести некуда по схеме переходов.')}
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}
