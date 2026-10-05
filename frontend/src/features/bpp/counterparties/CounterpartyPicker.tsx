/**
 * Выбор контрагента поиском по реестру (`GET /bpp/v1/counterparties?q=`) —
 * для чужих форм: заказчик проекта (`customer_counterparty_id`).
 *
 * Предлагаются только действующие: заблокированный или архивный
 * контрагент новым документам не годится. Уже выбранный показывается по
 * его карточке — даже если он с тех пор заблокирован (так и видно, что
 * выбор устарел). Выбор снимается крестиком: поле необязательное.
 *
 * Три пустых списка не путаются: «ничего не найдено по запросу» (поиск
 * есть, совпадений нет), «нет действующих контрагентов» (поиска нет — под
 * полем ещё и ссылка туда, где контрагента заводят) и отказ сервера
 * (403 — нет прав на реестр, 503 — модуль выключен): его текст уходит
 * всплывающим сообщением через `reportApiError`, а в списке — «не удалось
 * загрузить», а не «ничего не найдено», которое читалось бы как «таких нет».
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Check, ChevronsUpDown, X } from 'lucide-react';

import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { Button } from '@/components/ui/button';
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { reportApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';

import { COUNTERPARTIES_BASE, counterpartyApi, counterpartyKey, type CounterpartyRow } from './api';

interface Props {
  value: string | null;
  onChange: (id: string | null) => void;
  id?: string;
  disabled?: boolean;
}

const SEARCH_DELAY_MS = 250;

const labelOf = (row: Pick<CounterpartyRow, 'name' | 'reg_number'>) =>
  row.reg_number ? `${row.name} · ${row.reg_number}` : row.name;

export function CounterpartyPicker({ value, onChange, id, disabled }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  // Строка, выбранная из списка: подпись известна сразу, не дожидаясь
  // карточки (и не теряется, когда поиск сменил первую страницу).
  const [picked, setPicked] = useState<CounterpartyRow | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  const found = useQuery({
    queryKey: ['bpp', 'counterparties', 'picker', query],
    queryFn: () => counterpartyApi.search(query),
    enabled: open,
    staleTime: 30 * 1000,
    // Отказ (403/503) повтором не лечится — показываем его сразу.
    retry: false,
  });
  const options = found.data?.items ?? [];

  // Одно сообщение на отказ, а не на каждую перерисовку.
  const searchError = found.error;
  useEffect(() => {
    if (searchError) {
      reportApiError(searchError, t('bpp.projects.customerCounterpartyFailed',
        'Не удалось загрузить контрагентов'));
    }
  }, [searchError, t]);

  // Выбранный — по карточке: в первой странице поиска его может не быть.
  const selected = useQuery({
    queryKey: value ? counterpartyKey(value) : ['bpp', 'counterparty', 'none'],
    queryFn: () => counterpartyApi.get(value as string),
    enabled: Boolean(value),
    retry: false,
  });
  const known = selected.data
    ?? (picked?.id === value ? picked : options.find((row) => row.id === value));
  const selectedLabel = value
    ? (known ? labelOf(known) : t('bpp.projects.customerCounterpartyUnknown', 'Контрагент выбран'))
    : null;

  // Пусто без поиска — действующих контрагентов нет вообще (не «ничего не
  // найдено»). Ответ остаётся в кеше и после закрытия списка, поэтому
  // плашка не мигает.
  const registryEmpty = !found.isError && found.data !== undefined && !query
    && options.length === 0;
  const emptyText = found.isLoading
    ? t('bpp.projects.customerCounterpartyLoading', 'Загрузка…')
    : found.isError
      ? t('bpp.projects.customerCounterpartyFailed', 'Не удалось загрузить контрагентов')
      : query
        ? t('bpp.projects.customerCounterpartyNotFound', 'Ничего не найдено по запросу «{{query}}»',
          { query })
        : t('bpp.projects.customerCounterpartyNone', 'Нет действующих контрагентов');

  return (
    <div className="space-y-1.5">
      <div className="flex gap-2">
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button
              id={id}
              type="button"
              variant="outline"
              role="combobox"
              aria-expanded={open}
              disabled={disabled}
              className="w-full justify-between font-normal"
            >
              <span className="truncate">
                {selectedLabel ?? t('bpp.projects.customerCounterpartyChoose', 'Выберите контрагента')}
              </span>
              <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
            <Command shouldFilter={false}>
              <CommandInput
                value={search}
                onValueChange={setSearch}
                placeholder={t('bpp.projects.customerCounterpartySearch', 'Наименование или БИН/ИИН')}
              />
              <CommandList>
                <CommandEmpty>{emptyText}</CommandEmpty>
                <CommandGroup>
                  {options.map((row) => (
                    <CommandItem
                      key={row.id}
                      value={row.id}
                      onSelect={() => {
                        setPicked(row);
                        onChange(row.id);
                        setOpen(false);
                      }}
                    >
                      <Check className={cn('mr-2 h-4 w-4', row.id === value ? 'opacity-100' : 'opacity-0')} />
                      <span className="flex-1 truncate">{labelOf(row)}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
        {value && !disabled && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => onChange(null)}
            aria-label={t('bpp.projects.customerCounterpartyClear', 'Убрать контрагента')}
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>
      <PrerequisiteNotice
        variant="inline"
        items={[{
          when: registryEmpty,
          text: t('bpp.projects.customerCounterpartyEmpty', 'Действующих контрагентов нет —'),
          to: `${COUNTERPARTIES_BASE}/new`,
          linkText: t('bpp.projects.customerCounterpartyCreate', 'заведите контрагента'),
        }]}
      />
    </div>
  );
}

export default CounterpartyPicker;
