/**
 * Вкладка «Шаблоны чек-листов» настроек доски (этап S3): готовые списки
 * пунктов. Кнопка «Чек-лист» в окне задачи копирует пункты шаблона домашней
 * доски, автоматизация (этап S4) добавляет чек-лист по шаблону. Пункты —
 * по одному в строке; сохраняется вся вкладка разом.
 */
import { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import type { ChecklistTemplate } from '@/types/tasks';

import { useBoardSettings, useSaveTemplates } from '../hooks/useBoardFields';
import type { SharedBoardKey } from '../types';

/** Пределы сервера: шаблонов на доске, пунктов в шаблоне, длина пункта. */
const TEMPLATE_LIMIT = 20;
const ITEM_LIMIT = 50;
const ITEM_LENGTH = 500;

interface Draft {
  id?: string;
  title: string;
  text: string;
}

const toDraft = (template: ChecklistTemplate): Draft => ({
  id: template.id, title: template.title, text: template.items.join('\n'),
});

const itemsOf = (draft: Draft) => draft.text.split('\n').map((line) => line.trim()).filter(Boolean);

export function TemplatesTab({ boardKey, onDone }: { boardKey: SharedBoardKey; onDone: () => void }) {
  const { t } = useTranslation();
  const { data: settings, isLoading } = useBoardSettings(boardKey, true);
  const save = useSaveTemplates(boardKey);
  const [drafts, setDrafts] = useState<Draft[]>([]);

  useEffect(() => {
    if (settings) setDrafts(settings.checklist_templates.map(toDraft));
  }, [settings]);

  const patch = (index: number, change: Partial<Draft>) =>
    setDrafts((current) => current.map((draft, at) => (at === index ? { ...draft, ...change } : draft)));

  const problems = drafts.map((draft) => {
    const items = itemsOf(draft);
    if (!draft.title.trim()) return t('tasks.templates.titleRequired', 'Назовите шаблон');
    if (items.length > ITEM_LIMIT) {
      return t('tasks.templates.tooMany', 'В шаблоне не больше {{count}} пунктов', { count: ITEM_LIMIT });
    }
    if (items.some((item) => item.length > ITEM_LENGTH)) {
      return t('tasks.templates.tooLong', 'Пункт — не длиннее {{count}} символов', { count: ITEM_LENGTH });
    }
    return null;
  });

  const submit = () => save.mutate(
    drafts.map((draft) => ({ ...(draft.id ? { id: draft.id } : {}), title: draft.title.trim(),
      items: itemsOf(draft) })),
    { onSuccess: onDone },
  );

  if (isLoading) return <Skeleton className="h-24 w-full" />;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {t('tasks.templates.hint', 'Кнопка «Чек-лист» в окне задачи предложит скопировать пункты шаблона.')}
      </p>
      {drafts.length === 0 && (
        <p className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
          {t('tasks.templates.empty', 'Шаблонов пока нет.')}
        </p>
      )}
      {drafts.map((draft, index) => (
        <div key={draft.id ?? `new-${index}`} className="space-y-2 rounded-lg border p-3">
          <div className="flex items-center gap-2">
            <Input value={draft.title} maxLength={200}
              aria-label={t('tasks.templates.title', 'Название шаблона')}
              placeholder={t('tasks.templates.titlePlaceholder', 'Например, «Чек-лист»')}
              onChange={(event) => patch(index, { title: event.target.value })} />
            <Button variant="ghost" size="icon" className="h-9 w-9 shrink-0"
              aria-label={t('tasks.templates.delete', 'Удалить шаблон «{{name}}»', { name: draft.title })}
              onClick={() => setDrafts((current) => current.filter((_item, at) => at !== index))}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
          <Textarea value={draft.text} rows={4}
            aria-label={t('tasks.templates.items', 'Пункты шаблона «{{name}}»', { name: draft.title })}
            placeholder={t('tasks.templates.itemsPlaceholder', 'По пункту в строке')}
            onChange={(event) => patch(index, { text: event.target.value })} />
          <p className="text-xs text-muted-foreground">
            {t('tasks.templates.count', 'Пунктов: {{count}}', { count: itemsOf(draft).length })}
          </p>
          {problems[index] && <p role="alert" className="text-xs text-destructive">{problems[index]}</p>}
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" disabled={drafts.length >= TEMPLATE_LIMIT}
          onClick={() => setDrafts((current) => [...current,
            { title: t('tasks.checklist.defaultTitle', 'Чек-лист'), text: '' }])}>
          <Plus className="mr-1.5 h-4 w-4" />{t('tasks.templates.new', 'Новый шаблон')}
        </Button>
        <Button size="sm" className="ml-auto" disabled={save.isPending || problems.some(Boolean)}
          onClick={submit}>
          {t('tasks.board.settings.save', 'Сохранить')}
        </Button>
      </div>
    </div>
  );
}
