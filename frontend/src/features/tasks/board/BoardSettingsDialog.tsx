/**
 * Настройки доски, правит администратор (K-39). «Колонки» (K-34): у каждого
 * статуса — своё название, цвет из палитры и признак «скрыта»; сервер не
 * даёт скрыть все колонки (`board_columns_hidden`). У досок отделов и
 * проектов ещё «Поля» и «Шаблоны чек-листов» (K-35, этап S3).
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TASK_STATUS } from '@/lib/tasks/status';
import { cn } from '@/lib/utils';
import type { TaskStatus } from '@/types/tasks';

import { swatchStyle } from './boardColors';
import { FieldsTab } from './settings/FieldsTab';
import { TemplatesTab } from './settings/TemplatesTab';
import {
  BOARD_COLORS, type BoardColor, type BoardKey, type ColumnSetting, type ColumnsSettings,
} from './types';

const ORDER: TaskStatus[] = ['backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled'];

export interface BoardSettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  boardKey: BoardKey;
  columns: ColumnsSettings;
  saving: boolean;
  onSave: (columns: ColumnsSettings) => Promise<unknown>;
}

export function BoardSettingsDialog({
  open, onOpenChange, boardKey, columns, saving, onSave,
}: BoardSettingsDialogProps) {
  const { t } = useTranslation();
  const columnsPanel = (
    <ColumnsPanel open={open} onOpenChange={onOpenChange} columns={columns} saving={saving}
      onSave={onSave} />
  );
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('tasks.board.settings.boardTitle', 'Настройки доски')}</DialogTitle>
          <DialogDescription>
            {t('tasks.board.settings.description', 'Настройки меняет администратор доски.')}
          </DialogDescription>
        </DialogHeader>
        {boardKey.kind === 'personal' ? columnsPanel : (
          <Tabs defaultValue="columns">
            <TabsList>
              <TabsTrigger value="columns">{t('tasks.board.settings.title', 'Колонки доски')}</TabsTrigger>
              <TabsTrigger value="fields">{t('tasks.fields.tab', 'Поля')}</TabsTrigger>
              <TabsTrigger value="templates">{t('tasks.templates.tab', 'Шаблоны чек-листов')}</TabsTrigger>
            </TabsList>
            <TabsContent value="columns">{columnsPanel}</TabsContent>
            <TabsContent value="fields"><FieldsTab boardKey={boardKey} /></TabsContent>
            <TabsContent value="templates">
              <TemplatesTab boardKey={boardKey} onDone={() => onOpenChange(false)} />
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ColumnsPanel({ open, onOpenChange, columns, saving, onSave }: Omit<BoardSettingsDialogProps, 'boardKey'>) {
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
    <>
      <p className="text-sm text-muted-foreground">
        {t('tasks.board.settings.hint',
          'Колонка — это статус задачи. Доска может назвать его по-своему, покрасить и скрыть; переходы между статусами от этого не меняются.')}
      </p>
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
    </>
  );
}
