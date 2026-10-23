/**
 * Чек-листы в окне карточки (Trello): полоса прогресса (зелёная при полном),
 * «Скрыть отмеченные», пункты с отметкой, правкой на месте и удалением,
 * «Добавить элемент». Отметить, добавить, переименовать — кто ведёт задачу
 * (`soft_edit`); удалить чек-лист — только с полной правкой.
 */
import { useState } from 'react';
import { CheckSquare, Trash2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Progress } from '@/components/ui/progress';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import type { Checklist } from '@/types/tasks';

import { EditableText } from './EditableText';
import { useChecklistActions } from './hooks';

export interface ChecklistBlockProps {
  taskId: number;
  checklist: Checklist;
  canEdit: boolean;
  canDelete: boolean;
}

function AddItem({ onAdd }: { onAdd: (text: string) => Promise<unknown> }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const submit = async () => {
    const value = text.trim();
    if (!value) return;
    try {
      await onAdd(value);
      setText('');
    } catch {
      // Причину показал onError мутации; текст остаётся — можно повторить.
    }
  };
  if (!open) {
    return (
      <Button variant="secondary" size="sm" className="ml-7" onClick={() => setOpen(true)}>
        {t('tasks.checklist.addItem', 'Добавить элемент')}
      </Button>
    );
  }
  return (
    <div className="ml-7 space-y-2">
      <Textarea autoFocus rows={2} value={text} maxLength={500} className="resize-none"
        placeholder={t('tasks.checklist.itemPlaceholder', 'Добавьте элемент')}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(); }
          if (event.key === 'Escape') { event.stopPropagation(); setOpen(false); setText(''); }
        }} />
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => void submit()} disabled={!text.trim()}>
          {t('tasks.checklist.add', 'Добавить')}
        </Button>
        <Button size="icon" variant="ghost" className="h-8 w-8"
          aria-label={t('tasks.board.cancel', 'Отмена')}
          onClick={() => { setOpen(false); setText(''); }}>
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

export function ChecklistBlock({ taskId, checklist, canEdit, canDelete }: ChecklistBlockProps) {
  const { t } = useTranslation();
  const actions = useChecklistActions(taskId);
  const [hideDone, setHideDone] = useState(false);
  const percent = checklist.total ? Math.round((checklist.done / checklist.total) * 100) : 0;
  const items = hideDone ? checklist.items.filter((item) => !item.is_done) : checklist.items;

  return (
    <section className="space-y-2" aria-label={checklist.title}>
      <div className="flex items-center gap-2">
        <CheckSquare className="h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1 font-semibold">
          <EditableText singleLine value={checklist.title} canEdit={canEdit} maxLength={200}
            label={t('tasks.checklist.rename', 'Название чек-листа')}
            onSave={(title) => actions.rename.mutate({ id: checklist.id, title })} />
        </div>
        {checklist.done > 0 && (
          <Button variant="secondary" size="sm" onClick={() => setHideDone((value) => !value)}>
            {hideDone
              ? t('tasks.checklist.showDone', 'Показать отмеченные ({{count}})', { count: checklist.done })
              : t('tasks.checklist.hideDone', 'Скрыть отмеченные')}
          </Button>
        )}
        {canDelete && (
          <Button variant="secondary" size="sm" onClick={() => actions.remove.mutate(checklist.id)}>
            {t('tasks.checklist.delete', 'Удалить')}
          </Button>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span className="w-9 text-right text-xs text-muted-foreground">{percent}%</span>
        <Progress value={percent}
          className={cn('h-2 flex-1', percent === 100 && '[&>div]:bg-board-done')} />
      </div>
      <ul className="space-y-0.5">
        {items.map((item) => (
          <li key={item.id} className="group flex items-start gap-2 rounded-md px-1 py-1 hover:bg-muted/50">
            <Checkbox className="mt-1" checked={item.is_done} disabled={!canEdit}
              aria-label={item.text}
              onCheckedChange={(value) => actions.updateItem.mutate({ itemId: item.id,
                is_done: value === true })} />
            <div className={cn('min-w-0 flex-1 text-sm', item.is_done && 'text-muted-foreground line-through')}>
              <EditableText singleLine value={item.text} canEdit={canEdit} maxLength={500}
                label={t('tasks.checklist.renameItem', 'Текст пункта')}
                onSave={(text) => actions.updateItem.mutate({ itemId: item.id, text })} />
            </div>
            {canEdit && (
              <button type="button" onClick={() => actions.removeItem.mutate(item.id)}
                className="rounded p-1 text-muted-foreground opacity-0 transition hover:bg-muted group-hover:opacity-100 focus-visible:opacity-100"
                aria-label={t('tasks.checklist.deleteItem', 'Удалить пункт')}>
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </li>
        ))}
        {hideDone && items.length === 0 && (
          <li className="px-1 text-xs text-muted-foreground">
            {t('tasks.checklist.allDone', 'Все пункты отмечены.')}
          </li>
        )}
      </ul>
      {canEdit && (
        <AddItem onAdd={(text) => actions.addItem.mutateAsync({ checklistId: checklist.id, text })} />
      )}
    </section>
  );
}
