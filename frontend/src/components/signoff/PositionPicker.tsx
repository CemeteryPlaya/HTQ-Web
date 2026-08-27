/** Select HR positions for a route stage, never individual user accounts. */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Check, ChevronsUpDown, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { fetchPositions } from '@/api/hr';
import type { Position } from '@/types/hr';
import { cn } from '@/lib/utils';

interface Props {
  value: number[];
  onChange: (ids: number[]) => void;
  knownNames?: Record<number, string>;
  disabled?: boolean;
}

const labelOf = (position: Position) =>
  [position.title, position.department_name].filter(Boolean).join(' · ');

export function PositionPicker({ value, onChange, knownNames = {}, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const { data: positions = [], isLoading } = useQuery({
    queryKey: ['hr-positions-for-signoff'],
    queryFn: fetchPositions,
    staleTime: 5 * 60 * 1000,
  });
  const byId = useMemo(() => new Map(positions.map((row) => [row.id, row])), [positions]);
  const toggle = (id: number) =>
    onChange(value.includes(id) ? value.filter((row) => row !== id) : [...value, id]);
  const nameOf = (id: number) => {
    const position = byId.get(id);
    return position ? labelOf(position) : knownNames[id] ?? `Должность #${id}`;
  };

  return <div className="space-y-2">
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" role="combobox" aria-expanded={open}
          disabled={disabled} className="w-full justify-between font-normal">
          {value.length === 0 ? 'Выберите должности' : `Выбрано: ${value.length}`}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
        <Command>
          <CommandInput placeholder="Поиск должности или отдела" />
          <CommandList><CommandEmpty>{isLoading ? 'Загрузка…' : 'Ничего не найдено'}</CommandEmpty>
            <CommandGroup>{positions.map((position) => {
              const selected = value.includes(position.id);
              return <CommandItem key={position.id} value={labelOf(position)} onSelect={() => toggle(position.id)}>
                <Check className={cn('mr-2 h-4 w-4', selected ? 'opacity-100' : 'opacity-0')} />
                <span className="flex-1 truncate">{labelOf(position)}</span>
                {position.is_active === false && <Badge variant="outline" className="ml-2">неактивна</Badge>}
              </CommandItem>;
            })}</CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
    {value.length > 0 && <div className="flex flex-wrap gap-1.5">{value.map((id) => (
      <Badge key={id} variant="secondary" className="gap-1">{nameOf(id)}
        {!disabled && <button type="button" onClick={() => toggle(id)} aria-label={`Убрать ${nameOf(id)}`} className="hover:text-destructive"><X className="h-3 w-3" /></button>}
      </Badge>
    ))}</div>}
  </div>;
}
