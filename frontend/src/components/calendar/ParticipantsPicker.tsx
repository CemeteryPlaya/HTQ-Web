/**
 * ParticipantsPicker — chip-style multi-select used by the calendar event form.
 *
 * The author is auto-added on the server, so a non-empty selection here
 * means "пригласить дополнительно к автору".
 */
import React, { useMemo, useState } from 'react';
import { Check, Users, X } from 'lucide-react';

import type { CalendarUserOption } from '@/api/calendar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

interface Props {
  options: CalendarUserOption[];
  value: number[];
  onChange: (next: number[]) => void;
  placeholder: string;
}

export const ParticipantsPicker: React.FC<Props> = ({
  options,
  value,
  onChange,
  placeholder,
}) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const byId = useMemo(() => {
    const m = new Map<number, CalendarUserOption>();
    for (const o of options) m.set(o.id, o);
    return m;
  }, [options]);

  const toggle = (id: number) => {
    if (value.includes(id)) {
      onChange(value.filter((v) => v !== id));
    } else {
      onChange([...value, id]);
    }
  };

  return (
    <div className="space-y-2">
      {/* modal обязателен: этот выбор используется внутри диалога, а тот
          на время открытия блокирует прокрутку документа и пропускает
          события только внутри своего поддерева. Содержимое поповера
          рендерится порталом в body, то есть снаружи, — и список участников встречи
          переставал прокручиваться колесом, оставаясь прокручиваемым
          технически. С modal поповер ставит собственную блокировку. */}
      <Popover modal open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="w-full justify-start rounded-2xl h-12 bg-muted/30 border-none focus-visible:ring-primary/40 font-normal"
          >
            <Users className="mr-2 h-4 w-4 text-muted-foreground" />
            {value.length > 0 ? t('calendar.selectedCount', { count: value.length }) : placeholder}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[360px] p-0" align="start">
          <Command>
            <CommandInput placeholder={t('calendar.searchByNameOrEmail')} />
            <CommandEmpty>{t('messenger.nobodyFound')}</CommandEmpty>
            <CommandList className="max-h-72">
              <CommandGroup>
                {options.map((u) => {
                  const selected = value.includes(u.id);
                  return (
                    <CommandItem
                      key={u.id}
                      value={`${u.full_name} ${u.email}`}
                      onSelect={() => toggle(u.id)}
                    >
                      <Check
                        className={cn(
                          'mr-2 h-4 w-4',
                          selected ? 'opacity-100' : 'opacity-0',
                        )}
                      />
                      <span className="truncate">
                        {u.full_name}
                        <span className="ml-2 text-xs text-muted-foreground">
                          {u.email}
                        </span>
                      </span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((id) => {
            const u = byId.get(id);
            return (
              <Badge
                key={id}
                variant="secondary"
                className="gap-1 rounded-xl px-2 py-1 text-xs"
              >
                {u?.full_name || `#${id}`}
                <button
                  type="button"
                  onClick={() => toggle(id)}
                  className="ml-0.5 rounded-full p-0.5 hover:bg-muted-foreground/10"
                  aria-label={t('calendar.removeParticipant')}
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            );
          })}
        </div>
      )}
    </div>
  );
};
