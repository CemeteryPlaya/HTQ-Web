/**
 * Выбор HR-должностей для этапа или флага маршрута — никогда не учётных
 * записей людей.
 *
 * Должность — пара «компания + должность» (мастер-план БЗО, B8.1): маршрут
 * дочерней компании может стоять на должности ВЫШЕСТОЯЩЕЙ — директора в
 * штате холдинга. Есть вышестоящие — над списком появляется выбор компании;
 * нет — всё как раньше, должности своей компании. Справочник — из signoff
 * (`positions`, право — как у правки маршрутов), а не из кадрового API: тот
 * отдаёт только компанию запроса, а ФД и АДМ, правящие маршруты модуля,
 * кадровых прав могут и не иметь.
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Check, ChevronsUpDown, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { signoffApi } from '@/api/signoff';
import type { PositionOption, PositionRef } from '@/types/signoff';
import { refKey } from '@/components/signoff/crossCompany';
import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { cn } from '@/lib/utils';

interface Props {
  value: PositionRef[];
  onChange: (refs: PositionRef[]) => void;
  /** Подписи уже выбранных должностей из карточки маршрута: `refKey → подпись`. */
  knownNames?: Record<string, string>;
  /** Одна должность (эскалация): выбор заменяет прежнюю. */
  single?: boolean;
  disabled?: boolean;
}

const OWN = '';
/** Radix Select не принимает пустое значение пункта — своя компания под этим ключом. */
const OWN_VALUE = '__own__';

const labelOf = (position: PositionOption) =>
  [position.title, position.department_name].filter(Boolean).join(' · ');

export function PositionPicker({ value, onChange, knownNames = {}, single, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [company, setCompany] = useState(OWN);
  const { data: companies = [] } = useQuery({
    queryKey: ['signoff', 'position-companies'],
    queryFn: () => signoffApi.positionCompanies().then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });
  const { data: positions = [], isLoading } = useQuery({
    queryKey: ['signoff', 'positions', company],
    queryFn: () => signoffApi.positions(company).then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });
  const upper = companies.filter((row) => !row.own);
  const companyName = (slug: string) =>
    companies.find((row) => !row.own && row.slug === slug)?.name || slug;

  const byKey = useMemo(
    () => new Map(positions.map((row) => [refKey({ company, position_id: row.id }), row])),
    [positions, company],
  );
  const selected = new Set(value.map(refKey));
  const toggle = (id: number) => {
    const ref = { company, position_id: id };
    if (selected.has(refKey(ref))) onChange(value.filter((row) => refKey(row) !== refKey(ref)));
    else onChange(single ? [ref] : [...value, ref]);
  };
  const nameOf = (ref: PositionRef) => {
    const known = knownNames[refKey(ref)];
    if (known) return known;
    const position = byKey.get(refKey(ref));
    const title = position ? labelOf(position) : `Должность #${ref.position_id}`;
    return ref.company ? `${title} · ${companyName(ref.company)}` : title;
  };

  return <div className="space-y-2">
    {upper.length > 0 && (
      <Select value={company || OWN_VALUE} onValueChange={(next) => setCompany(next === OWN_VALUE ? OWN : next)}
        disabled={disabled}>
        <SelectTrigger aria-label="Компания должности">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={OWN_VALUE}>Своя компания</SelectItem>
          {upper.map((row) => (
            <SelectItem key={row.slug} value={row.slug}>{row.name || row.slug}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    )}
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
              const isSelected = selected.has(refKey({ company, position_id: position.id }));
              return <CommandItem key={position.id} value={labelOf(position)} onSelect={() => toggle(position.id)}>
                <Check className={cn('mr-2 h-4 w-4', isSelected ? 'opacity-100' : 'opacity-0')} />
                <span className="flex-1 truncate">{labelOf(position)}</span>
                {position.is_active === false && <Badge variant="outline" className="ml-2">неактивна</Badge>}
              </CommandItem>;
            })}</CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
      </Popover>
      {/* Этап «по должности» без единой должности в справочнике не запустится
          вовсе — маршрут окажется неисполнимым. */}
      <PrerequisiteNotice
        variant="inline"
        items={[{
          when: !isLoading && positions.length === 0 && company === OWN,
          text: 'Справочник должностей пуст — этап «по должности» будет некому исполнять,',
          to: '/hr/positions',
          linkText: 'заведите должность',
        }]}
      />
    {value.length > 0 && <div className="flex flex-wrap gap-1.5">{value.map((ref) => (
      <Badge key={refKey(ref)} variant="secondary" className="gap-1">{nameOf(ref)}
        {!disabled && <button type="button" onClick={() => onChange(value.filter((row) => refKey(row) !== refKey(ref)))}
          aria-label={`Убрать ${nameOf(ref)}`} className="hover:text-destructive"><X className="h-3 w-3" /></button>}
      </Badge>
    ))}</div>}
  </div>;
}
