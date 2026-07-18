import { useState } from 'react';
import { Check, Plus, X } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { cmsApi } from '@/api/cms';
import type { TagRef } from '@/types/news';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { toast } from 'sonner';

interface Props {
  value: number[];
  onChange: (ids: number[]) => void;
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-zа-я0-9\s-]/gi, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
}

export function TagsMultiSelect({ value, onChange }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');

  const { data: tags = [] } = useQuery({
    queryKey: ['cms', 'tags'],
    // Treat 404 as "endpoint not deployed yet" — return empty list silently.
    // Backend taxonomy router exists but may not be live until migration
    // 003_news_taxonomy is applied + cms image rebuilt.
    queryFn: () =>
      cmsApi.listTags().then((r) => r.data).catch((err) => {
        if (err?.response?.status === 404) return [] as TagRef[];
        throw err;
      }),
    staleTime: 60_000,
    retry: false,
  });

  const createTag = useMutation({
    mutationFn: (name: string) => cmsApi.createTag({ slug: slugify(name), name }).then((r) => r.data),
    onSuccess: (tag: TagRef) => {
      qc.setQueryData<TagRef[]>(['cms', 'tags'], (prev) => [...(prev ?? []), tag]);
      onChange([...value, tag.id]);
      setSearch('');
      toast.success(`Создан тег #${tag.name}`);
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Не удалось создать тег'),
  });

  const selected = tags.filter((t) => value.includes(t.id));
  const toggle = (id: number) =>
    onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);

  const exactMatch = tags.some((t) => t.name.toLowerCase() === search.trim().toLowerCase());

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-1.5">
        {selected.length === 0 && (
          <span className="text-xs text-muted-foreground">Теги не выбраны</span>
        )}
        {selected.map((tag) => (
          <Badge key={tag.id} variant="secondary" className="gap-1 pr-1">
            #{tag.name}
            <button
              type="button"
              onClick={() => toggle(tag.id)}
              className="ml-0.5 rounded-full p-0.5 hover:bg-muted-foreground/20"
              aria-label={`Убрать тег ${tag.name}`}
            >
              <X className="h-3 w-3" />
            </button>
          </Badge>
        ))}
      </div>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" size="sm" className="w-fit">
            <Plus className="mr-1 h-3.5 w-3.5" /> Добавить тег
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="start">
          <Command shouldFilter>
            <CommandInput
              value={search}
              onValueChange={setSearch}
              placeholder="Поиск или новое имя…"
            />
            <CommandList>
              <CommandEmpty>
                {search.trim() ? 'Ничего не найдено' : 'Начните вводить'}
              </CommandEmpty>
              <CommandGroup>
                {tags.map((tag) => {
                  const checked = value.includes(tag.id);
                  return (
                    <CommandItem key={tag.id} value={tag.name} onSelect={() => toggle(tag.id)}>
                      <Check
                        className={`mr-2 h-4 w-4 ${checked ? 'opacity-100' : 'opacity-0'}`}
                      />
                      #{tag.name}
                    </CommandItem>
                  );
                })}
                {search.trim() && !exactMatch && (
                  <CommandItem
                    value={`__create__${search}`}
                    onSelect={() => createTag.mutate(search.trim())}
                  >
                    <Plus className="mr-2 h-4 w-4" /> Создать «{search.trim()}»
                  </CommandItem>
                )}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
