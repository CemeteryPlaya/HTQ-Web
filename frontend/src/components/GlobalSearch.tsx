import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Command as CommandPrimitive } from 'cmdk';
import {
  CheckSquare,
  Users,
  Newspaper,
  FileText,
  Loader2,
} from 'lucide-react';

import { Dialog, DialogContent } from '@/components/ui/dialog';
import {
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { globalSearch, type GlobalSearchItem, type SearchCategory } from '@/api/search';

interface GlobalSearchProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const CATEGORY_ICON: Record<SearchCategory, React.ComponentType<{ className?: string }>> = {
  task: CheckSquare,
  employee: Users,
  news: Newspaper,
  file: FileText,
};

const CATEGORY_ORDER: SearchCategory[] = ['task', 'employee', 'news', 'file'];

export const GlobalSearch: React.FC<GlobalSearchProps> = ({ open, onOpenChange }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [input, setInput] = useState('');
  const [term, setTerm] = useState('');

  // Reset query state whenever the dialog closes.
  useEffect(() => {
    if (!open) {
      setInput('');
      setTerm('');
    }
  }, [open]);

  // Debounce raw input → search term.
  useEffect(() => {
    const id = window.setTimeout(() => setTerm(input.trim()), 250);
    return () => window.clearTimeout(id);
  }, [input]);

  const { data: items = [], isFetching } = useQuery({
    queryKey: ['global-search', term],
    queryFn: () => globalSearch(term),
    enabled: open && term.length >= 2,
    staleTime: 30_000,
  });

  const grouped = useMemo(() => {
    const map = new Map<SearchCategory, GlobalSearchItem[]>();
    for (const item of items) {
      const list = map.get(item.category) ?? [];
      list.push(item);
      map.set(item.category, list);
    }
    return CATEGORY_ORDER.filter((c) => map.has(c)).map((c) => ({
      category: c,
      items: map.get(c)!,
    }));
  }, [items]);

  const categoryLabel = (c: SearchCategory): string =>
    ({
      task: t('search.categories.tasks', 'Задачи'),
      employee: t('search.categories.employees', 'Сотрудники'),
      news: t('search.categories.news', 'Новости'),
      file: t('search.categories.files', 'Документы'),
    })[c];

  const handleSelect = (item: GlobalSearchItem) => {
    onOpenChange(false);
    navigate(item.href);
  };

  const showEmpty = term.length >= 2 && !isFetching && items.length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0 shadow-lg sm:max-w-[600px]">
        <CommandPrimitive
          shouldFilter={false}
          className="flex h-full w-full flex-col overflow-hidden rounded-md bg-popover text-popover-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]]:px-2 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3"
        >
          <div className="relative">
            <CommandInput
              value={input}
              onValueChange={setInput}
              placeholder={t('search.placeholder', 'Поиск по задачам, сотрудникам, документам…')}
              autoFocus
            />
            {isFetching && (
              <Loader2 className="absolute right-3 top-3.5 h-4 w-4 animate-spin text-muted-foreground" />
            )}
          </div>
          <CommandList>
            {term.length < 2 && (
              <div className="py-6 text-center text-sm text-muted-foreground">
                {t('search.hint', 'Введите минимум 2 символа')}
              </div>
            )}
            {showEmpty && (
              <CommandEmpty>{t('search.empty', 'Ничего не найдено')}</CommandEmpty>
            )}
            {grouped.map(({ category, items: groupItems }) => {
              const Icon = CATEGORY_ICON[category];
              return (
                <CommandGroup key={category} heading={categoryLabel(category)}>
                  {groupItems.map((item) => (
                    <CommandItem
                      key={item.id}
                      value={item.id}
                      onSelect={() => handleSelect(item)}
                      className="cursor-pointer gap-3"
                    >
                      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate">{item.title}</span>
                        {item.subtitle && (
                          <span className="truncate text-xs text-muted-foreground">
                            {item.subtitle}
                          </span>
                        )}
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              );
            })}
          </CommandList>
        </CommandPrimitive>
      </DialogContent>
    </Dialog>
  );
};
