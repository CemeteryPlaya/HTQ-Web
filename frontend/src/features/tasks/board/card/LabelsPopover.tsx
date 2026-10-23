/**
 * Метки карточки (Trello «Метки»): поиск, отметка, у администратора задач —
 * новая метка. Метки общие на компанию (K-22), поэтому заводит их
 * администратор, а не каждый на своей доске.
 */
import { type ReactNode, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { createLabel, fetchLabels } from '@/api/tasks';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { usePermissions } from '@/hooks/usePermissions';
import { reportApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';

const NEW_LABEL_COLORS = ['#4bce97', '#f5cd47', '#fea362', '#f87168', '#9f8fef', '#579dff',
  '#6cc3e0', '#94c748', '#e774bb', '#8590a2'];

export interface LabelsPopoverProps {
  selected: number[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
  trigger: ReactNode;
}

export function LabelsPopover({ selected, onChange, disabled = false, trigger }: LabelsPopoverProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const canCreate = permissions.atLeast('tasks', 'admin');
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [name, setName] = useState('');
  const [color, setColor] = useState(NEW_LABEL_COLORS[0]);
  const { data: labels = [], isLoading } = useQuery({
    queryKey: ['hr-labels'], queryFn: fetchLabels, enabled: open,
  });
  const shown = useMemo(() => labels.filter((label) =>
    label.name.toLowerCase().includes(query.trim().toLowerCase())), [labels, query]);

  const create = useMutation({
    mutationFn: () => createLabel({ name: name.trim(), color }),
    onSuccess: (label) => {
      void queryClient.invalidateQueries({ queryKey: ['hr-labels'] });
      setName('');
      onChange([...selected, label.id]);
    },
    onError: (error) => reportApiError(error, t('tasks.card.labels.createFailed', 'Не удалось создать метку')),
  });

  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={disabled}>{trigger}</PopoverTrigger>
      <PopoverContent align="start" className="w-72 space-y-3 p-3">
        <p className="text-center text-sm font-semibold">{t('tasks.card.labels.title', 'Метки')}</p>
        <Input value={query} placeholder={t('tasks.card.labels.search', 'Найти метку')}
          onChange={(event) => setQuery(event.target.value)} />
        <div className="max-h-60 space-y-1 overflow-y-auto">
          {shown.map((label) => {
            const on = selected.includes(label.id);
            return (
              <button key={label.id} type="button" onClick={() => toggle(label.id)}
                aria-pressed={on}
                className="flex w-full items-center gap-2 rounded-md p-1 text-left hover:bg-muted">
                <span className={cn('flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                  on && 'border-primary bg-primary text-primary-foreground')}>
                  {on && <Check className="h-3 w-3" />}
                </span>
                <span className="h-7 min-w-0 flex-1 truncate rounded px-2 text-sm font-medium leading-7 text-white"
                  style={{ backgroundColor: label.color }}>
                  {label.name}
                </span>
              </button>
            );
          })}
          {!isLoading && labels.length === 0 && (
            <p className="px-1 text-xs text-muted-foreground">
              {canCreate
                ? t('tasks.card.labels.emptyAdmin', 'Меток пока нет — создайте первую ниже.')
                : t('tasks.card.labels.empty', 'Меток пока нет — их заводит администратор задач.')}
            </p>
          )}
          {labels.length > 0 && shown.length === 0 && (
            <p className="px-1 text-xs text-muted-foreground">
              {t('tasks.card.labels.notFound', 'Таких меток нет')}
            </p>
          )}
        </div>
        {canCreate && (
          <div className="space-y-2 border-t pt-3">
            <Input value={name} maxLength={50}
              placeholder={t('tasks.card.labels.newName', 'Название новой метки')}
              onChange={(event) => setName(event.target.value)} />
            <div className="grid grid-cols-5 gap-1.5">
              {NEW_LABEL_COLORS.map((hex) => (
                <button key={hex} type="button" aria-label={hex} aria-pressed={color === hex}
                  className={cn('h-6 rounded ring-offset-2 ring-offset-background',
                    color === hex && 'ring-2 ring-foreground')}
                  style={{ backgroundColor: hex }} onClick={() => setColor(hex)} />
              ))}
            </div>
            <Button size="sm" className="w-full" disabled={!name.trim() || create.isPending}
              onClick={() => create.mutate()}>
              {t('tasks.card.labels.create', 'Создать метку')}
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
