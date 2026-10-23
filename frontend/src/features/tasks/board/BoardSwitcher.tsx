/**
 * Переключатель досок в шапке (Trello: название доски со стрелкой). Список —
 * `GET boards/`: личная доска, доски видимых отделов и проектов (§6.1).
 * Отделы — деревом по глубине, проекты — с цветной точкой.
 */
import { useState } from 'react';
import { Check, ChevronDown, FolderKanban, Network, User } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

import { boardUrl } from './boardRoutes';
import { useBoardsList } from './hooks/useBoard';
import type { BoardKey } from './types';

const same = (a: BoardKey, b: BoardKey) =>
  a.kind === b.kind && (a.kind === 'personal' || (b.kind !== 'personal' && a.id === b.id));

export function BoardSwitcher({ current, title }: { current: BoardKey; title: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useBoardsList();
  const departments = data?.departments ?? [];
  const projects = data?.projects ?? [];

  const go = (key: BoardKey) => {
    setOpen(false);
    if (!same(key, current)) navigate(boardUrl(key));
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost"
          className="h-9 max-w-[min(420px,70vw)] gap-1.5 px-2 text-lg font-bold hover:bg-black/10 dark:hover:bg-white/10"
          aria-label={t('tasks.board.switcher.open', 'Другие доски')}>
          <span className="truncate">{title}</span>
          <ChevronDown className="h-4 w-4 shrink-0 opacity-70" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0">
        <Command>
          <CommandInput placeholder={t('tasks.board.switcher.search', 'Найти доску')} />
          <CommandList className="max-h-[60vh]">
            <CommandEmpty>{t('tasks.board.switcher.notFound', 'Доска не найдена')}</CommandEmpty>
            <CommandGroup heading={t('tasks.board.switcher.departments', 'Доски отделов')}>
              {departments.map((department) => (
                <CommandItem key={`d-${department.id}`} value={`d-${department.id} ${department.path}`}
                  onSelect={() => go({ kind: 'department', id: department.id })}>
                  <Network className="mr-2 h-4 w-4 shrink-0 text-muted-foreground"
                    style={{ marginLeft: Math.min(department.depth, 4) * 12 }} />
                  <span className={cn('truncate', !department.is_active && 'text-muted-foreground')}>
                    {department.name}
                  </span>
                  {same(current, { kind: 'department', id: department.id }) && (
                    <Check className="ml-auto h-4 w-4" />
                  )}
                </CommandItem>
              ))}
              {!isLoading && departments.length === 0 && (
                <p className="px-2 py-1.5 text-xs text-muted-foreground">
                  {t('tasks.board.switcher.noDepartments',
                    'Досок отделов нет: в кадрах вы не числитесь ни в одном отделе.')}
                </p>
              )}
            </CommandGroup>
            {projects.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading={t('tasks.board.switcher.projects', 'Доски проектов')}>
                  {projects.map((project) => (
                    <CommandItem key={`p-${project.id}`} value={`p-${project.id} ${project.name}`}
                      onSelect={() => go({ kind: 'project', id: project.id })}>
                      <FolderKanban className="mr-2 h-4 w-4 shrink-0" style={{ color: project.color }} />
                      <span className="truncate">{project.name}</span>
                      {same(current, { kind: 'project', id: project.id }) && (
                        <Check className="ml-auto h-4 w-4" />
                      )}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
            <CommandSeparator />
            <CommandGroup>
              <CommandItem value="personal" onSelect={() => go({ kind: 'personal' })}>
                <User className="mr-2 h-4 w-4 text-muted-foreground" />
                {t('tasks.board.personalTitle', 'Мои задачи')}
                {current.kind === 'personal' && <Check className="ml-auto h-4 w-4" />}
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
