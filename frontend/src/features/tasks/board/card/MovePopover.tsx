/**
 * «Переместить» из окна карточки (Trello: чип колонки в шапке окна). Только
 * видимые колонки, куда пускает схема переходов; названия и цвета — доски
 * (K-34). Скрытой колонки в процессе доски нет — вручную в неё не переносят
 * (спецификация логики автоматизаций §5), а отмена задачи — отдельной
 * строкой, даже когда колонка «Отменена» скрыта.
 */
import { type ReactNode, useState } from 'react';
import { ArrowRight, Ban } from 'lucide-react';
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
    && !column.hidden && canTransition(status, column.status));
  const cancellable = status !== 'cancelled' && canTransition(status, 'cancelled')
    && !targets.some((column) => column.status === 'cancelled');

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
            <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        ))}
        {cancellable && (
          <>
            {targets.length > 0 && <div className="my-1 border-t" />}
            <button type="button" onClick={() => { onMove('cancelled'); setOpen(false); }}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-destructive hover:bg-muted">
              <Ban className="h-3.5 w-3.5" />
              <span className="min-w-0 flex-1 truncate">{t('tasks.card.move.cancel', 'Отменить задачу')}</span>
            </button>
          </>
        )}
        {targets.length === 0 && !cancellable && (
          <p className="px-2 py-1.5 text-xs text-muted-foreground">
            {t('tasks.card.move.none', 'Из этой колонки задачу перенести некуда по схеме переходов.')}
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}
