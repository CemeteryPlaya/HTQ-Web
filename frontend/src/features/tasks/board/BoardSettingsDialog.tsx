/**
 * Настройки колонок доски (K-34): у каждого статуса — своё название, цвет из
 * палитры и признак «скрыта». Правит администратор доски (K-39); сервер
 * проверяет это сам и не даёт скрыть все колонки (`board_columns_hidden`).
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { TASK_STATUS } from '@/lib/tasks/status';
import { cn } from '@/lib/utils';
import type { TaskStatus } from '@/types/tasks';

import { swatchStyle } from './boardColors';
import { BOARD_COLORS, type BoardColor, type ColumnSetting, type ColumnsSettings } from './types';

const ORDER: TaskStatus[] = ['backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled'];

export interface BoardSettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  columns: ColumnsSettings;
  saving: boolean;
  onSave: (columns: ColumnsSettings) => Promise<unknown>;
}

export function BoardSettingsDialog({ open, onOpenChange, columns, saving, onSave }: BoardSettingsDialogProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<ColumnsSettings>(columns);

  useEffect(() => { if (open) setDraft(columns); }, [open, columns]);

  const patch = (status: TaskStatus, change: Partial<ColumnSetting>) =>
    setDraft((current) => ({ ...current, [status]: { ...current[status], ...change } }));

  const allHidden = ORDER.every((status) => draft[status]?.hidden);

  const save = async () => {
    const cleaned = Object.fromEntries(ORDER.map((status) => [status, {
      title: draft[status].title?.trim() || null,
      color: draft[status].color,
      hidden: draft[status].hidden,
    }])) as ColumnsSettings;
    try {
      await onSave(cleaned);
      onOpenChange(false);
    } catch {
      // Причину уже показал onError мутации (reportApiError); окно остаётся
      // открытым с правками, чтобы их не набирать заново.
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('tasks.board.settings.title', 'Колонки доски')}</DialogTitle>
          <DialogDescription>
            {t('tasks.board.settings.hint',
              'Колонка — это статус задачи. Доска может назвать его по-своему, покрасить и скрыть; переходы между статусами от этого не меняются.')}
          </DialogDescription>
        </DialogHeader>

        <div className="divide-y">
          {ORDER.map((status) => {
            const column = draft[status];
            const fallbackTitle = t(TASK_STATUS[status].labelKey, status);
            return (
              <div key={status} className="grid gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="w-28 shrink-0 text-xs text-muted-foreground">{fallbackTitle}</span>
                    <Input
                      value={column.title ?? ''}
                      maxLength={60}
                      placeholder={fallbackTitle}
                      aria-label={t('tasks.board.settings.columnTitle', 'Название колонки «{{status}}»',
                        { status: fallbackTitle })}
                      onChange={(event) => patch(status, { title: event.target.value })}
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 sm:pl-[7.5rem]">
                    {BOARD_COLORS.map((color) => (
                      <button
                        key={color}
                        type="button"
                        aria-label={t(`tasks.board.colors.${color}`, color)}
                        aria-pressed={column.color === color}
                        className={cn('h-6 w-8 rounded ring-offset-2 ring-offset-background',
                          column.color === color && 'ring-2 ring-foreground')}
                        style={swatchStyle(color)}
                        onClick={() => patch(status, { color: color as BoardColor })}
                      />
                    ))}
                    <button
                      type="button"
                      aria-pressed={column.color === null}
                      className={cn('h-6 rounded border px-2 text-xs text-muted-foreground ring-offset-2 ring-offset-background',
                        column.color === null && 'ring-2 ring-foreground')}
                      onClick={() => patch(status, { color: null })}
                    >
                      {t('tasks.board.column.noColor', 'Без цвета')}
                    </button>
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm sm:justify-end">
                  <Switch checked={column.hidden}
                    onCheckedChange={(hidden) => patch(status, { hidden })} />
                  {t('tasks.board.settings.hidden', 'Скрыта')}
                </label>
              </div>
            );
          })}
        </div>

        {allHidden && (
          <p role="alert" className="text-sm text-destructive">
            {t('tasks.board.settings.allHidden', 'Хотя бы одна колонка должна остаться на доске.')}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('tasks.board.cancel', 'Отмена')}
          </Button>
          <Button onClick={() => void save()} disabled={saving || allHidden}>
            {t('tasks.board.settings.save', 'Сохранить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
