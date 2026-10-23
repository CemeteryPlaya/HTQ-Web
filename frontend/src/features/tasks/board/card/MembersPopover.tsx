/**
 * Участники карточки (Trello «Участники»): исполнители с ролью и ×, поиск
 * сотрудника по имени, логину или почте. Первый добавленный становится
 * основным исполнителем; звёздочка делает основным другого. Состав
 * исполнителей сервер заменяет целиком (`PATCH tasks/<id>/assignees`).
 */
import { type ReactNode, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Star, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { UserAvatar } from '@/components/ui/UserAvatar';
import { cn } from '@/lib/utils';
import type { AssigneeRole, TaskAssigneeRef } from '@/types/tasks';

import { cardKeys, peopleApi } from './api';

export type Crew = Array<{ user_id: number; role: AssigneeRole }>;

export interface MembersPopoverProps {
  assignees: TaskAssigneeRef[];
  onChange: (crew: Crew) => void;
  disabled?: boolean;
  trigger: ReactNode;
}

function useDebounced(value: string, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function MembersPopover({ assignees, onChange, disabled = false, trigger }: MembersPopoverProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const search = useDebounced(query.trim());
  const { data: people = [], isFetching } = useQuery({
    queryKey: cardKeys.people(search),
    queryFn: () => peopleApi.search(search),
    enabled: open && search.length >= 2,
  });
  const crew: Crew = assignees.map((row) => ({ user_id: row.user_id, role: row.role }));
  const inCrew = new Set(crew.map((row) => row.user_id));
  const candidates = people.filter((person) => !inCrew.has(person.id));

  const add = (userId: number) => onChange([...crew, {
    user_id: userId, role: crew.some((row) => row.role === 'primary') ? 'collaborator' : 'primary',
  }]);
  const remove = (userId: number) => {
    const rest = crew.filter((row) => row.user_id !== userId);
    // Снят основной — основным становится первый из оставшихся.
    if (rest.length && !rest.some((row) => row.role === 'primary')) rest[0] = { ...rest[0], role: 'primary' };
    onChange(rest);
  };
  const makePrimary = (userId: number) => onChange(crew.map((row) => ({
    user_id: row.user_id, role: row.user_id === userId ? 'primary' : 'collaborator',
  })));

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={disabled}>{trigger}</PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-3 p-3">
        <p className="text-center text-sm font-semibold">{t('tasks.card.members.title', 'Участники')}</p>
        <Input value={query} placeholder={t('tasks.card.members.search', 'Найти сотрудника')}
          onChange={(event) => setQuery(event.target.value)} />
        {assignees.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-semibold text-muted-foreground">
              {t('tasks.card.members.onCard', 'Исполнители карточки')}
            </p>
            {assignees.map((row) => (
              <div key={row.user_id} className="flex items-center gap-2 rounded-md p-1 hover:bg-muted/60">
                <UserAvatar url={row.avatar_url} name={row.name} size={24} />
                <span className="min-w-0 flex-1 truncate text-sm">{row.name ?? `#${row.user_id}`}</span>
                <button type="button" onClick={() => makePrimary(row.user_id)}
                  className={cn('rounded p-1 text-muted-foreground hover:text-foreground',
                    row.role === 'primary' && 'text-amber-500 hover:text-amber-500')}
                  aria-pressed={row.role === 'primary'}
                  aria-label={t('tasks.card.members.primary', 'Основной исполнитель')}>
                  <Star className={cn('h-4 w-4', row.role === 'primary' && 'fill-current')} />
                </button>
                <button type="button" onClick={() => remove(row.user_id)}
                  className="rounded p-1 text-muted-foreground hover:text-foreground"
                  aria-label={t('tasks.card.members.remove', 'Убрать из исполнителей')}>
                  <X className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="max-h-56 space-y-1 overflow-y-auto">
          {search.length >= 2 && candidates.map((person) => (
            <button key={person.id} type="button" onClick={() => add(person.id)}
              className="flex w-full items-center gap-2 rounded-md p-1 text-left hover:bg-muted">
              <UserAvatar name={person.full_name} size={24} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm">{person.full_name || person.username}</span>
                <span className="block truncate text-xs text-muted-foreground">{person.email}</span>
              </span>
            </button>
          ))}
          {search.length < 2 && (
            <p className="px-1 text-xs text-muted-foreground">
              {t('tasks.card.members.hint', 'Введите хотя бы две буквы имени, логина или почты.')}
            </p>
          )}
          {search.length >= 2 && !isFetching && candidates.length === 0 && (
            <p className="px-1 text-xs text-muted-foreground">
              {people.length === 0
                ? t('tasks.card.members.notFound', 'Никого не нашлось — проверьте написание.')
                : t('tasks.card.members.allAdded', 'Все найденные уже на карточке.')}
            </p>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
