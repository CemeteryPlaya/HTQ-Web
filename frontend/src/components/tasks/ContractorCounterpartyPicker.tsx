/**
 * Выбор контрагента модуля «Закупки и оплаты» в карточке партнёра (A6.1).
 *
 * Ищет своей ручкой задач (`GET /tasks/v1/contractors/counterparty-search`),
 * а не реестром `bpp`: карточку партнёра правит администратор задач, у
 * которого ролей модуля закупок может не быть. Предлагаются только
 * действующие контрагенты — заблокированный и архивный новой связи не
 * годятся (сервер ответит 409). Уже выбранный показывается по бейджу из
 * ответа партнёра — даже если с тех пор заблокирован.
 *
 * Пустой список объясняет себя: «нет действующих» (без поиска — с подсказкой,
 * где контрагента заводят), «ничего не найдено по запросу» (с поиском) или
 * отказ сервера (503 — модуль выключен: текст всплывающим сообщением через
 * `reportApiError`, в списке — «не удалось загрузить»).
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Check, ChevronsUpDown, X } from 'lucide-react';

import { searchContractorCounterparties } from '@/api/tasks';
import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { Button } from '@/components/ui/button';
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { reportApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';
import { COUNTERPARTIES_BASE } from '@/features/bpp/counterparties/api';
import type { ContractorCounterpartyOption, ContractorCounterpartyRef } from '@/types/tasks';

interface Props {
  /** Выбранный контрагент (бейдж из ответа партнёра или строка поиска). */
  value: ContractorCounterpartyRef | null;
  onChange: (option: ContractorCounterpartyOption | null) => void;
  id?: string;
  disabled?: boolean;
}

const SEARCH_DELAY_MS = 250;

const counterpartyLabel = (row: Pick<ContractorCounterpartyRef, 'name' | 'reg_number'>) =>
  row.reg_number ? `${row.name} · ${row.reg_number}` : row.name;

export function ContractorCounterpartyPicker({ value, onChange, id, disabled }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  const found = useQuery({
    queryKey: ['contractors', 'counterparty-search', query],
    queryFn: () => searchContractorCounterparties(query),
    enabled: open,
    staleTime: 30 * 1000,
    // Отказ (503) повтором не лечится — показываем его сразу.
    retry: false,
  });
  const options = found.data ?? [];

  const searchError = found.error;
  useEffect(() => {
    if (searchError) {
      reportApiError(searchError, t('tasks.pages.contractors.counterpartySearchFailed',
        'Не удалось загрузить контрагентов'));
    }
  }, [searchError, t]);

  // Пусто без поиска — действующих контрагентов нет вообще (не «ничего не
  // найдено»): под полем — ссылка туда, где контрагента заводят.
  const registryEmpty = !found.isError && found.data !== undefined && !query
    && options.length === 0;
  const emptyText = found.isLoading
    ? t('tasks.pages.contractors.counterpartyLoading', 'Загрузка…')
    : found.isError
      ? t('tasks.pages.contractors.counterpartySearchFailed', 'Не удалось загрузить контрагентов')
      : query
        ? t('tasks.pages.contractors.counterpartyNotFound', 'Ничего не найдено по запросу «{{query}}»',
          { query })
        : t('tasks.pages.contractors.counterpartyNoneActive', 'Действующих контрагентов нет');

  return (
    <div className="min-w-0 flex-1 space-y-1.5">
      <div className="flex min-w-0 gap-2">
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button
              id={id}
              type="button"
              variant="outline"
              role="combobox"
              aria-expanded={open}
              disabled={disabled}
              className="h-8 w-full justify-between rounded-xl text-xs font-normal"
            >
              <span className="truncate">
                {value
                  ? counterpartyLabel(value)
                  : t('tasks.pages.contractors.counterpartyPickPlaceholder',
                    'Не связан — выберите, чтобы подтянуть реквизиты')}
              </span>
              <ChevronsUpDown className="ml-2 h-3.5 w-3.5 shrink-0 opacity-50" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
            <Command shouldFilter={false}>
              <CommandInput
                value={search}
                onValueChange={setSearch}
                placeholder={t('tasks.pages.contractors.counterpartySearch', 'Название или БИН/ИИН…')}
              />
              <CommandList>
                <CommandEmpty>{emptyText}</CommandEmpty>
                <CommandGroup>
                  {options.map((row) => (
                    <CommandItem
                      key={row.id}
                      value={row.id}
                      onSelect={() => {
                        onChange(row);
                        setOpen(false);
                      }}
                    >
                      <Check className={cn('mr-2 h-4 w-4', row.id === value?.id ? 'opacity-100' : 'opacity-0')} />
                      <span className="flex-1 truncate">{counterpartyLabel(row)}</span>
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
            className="h-8 w-8 shrink-0 rounded-xl"
            onClick={() => onChange(null)}
            aria-label={t('tasks.pages.contractors.counterpartyClear', 'Снять связь с контрагентом')}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
      <PrerequisiteNotice
        variant="inline"
        items={[{
          when: registryEmpty,
          text: t('tasks.pages.contractors.counterpartyRegistryEmpty', 'Действующих контрагентов нет —'),
          to: `${COUNTERPARTIES_BASE}/new`,
          linkText: t('tasks.pages.contractors.counterpartyCreate', 'заведите контрагента в «Закупках и оплатах»'),
        }]}
      />
    </div>
  );
}

export default ContractorCounterpartyPicker;
