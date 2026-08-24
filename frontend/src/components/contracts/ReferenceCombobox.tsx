import { useMemo, useState } from 'react';
import { Check, ChevronsUpDown, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useTranslation } from 'react-i18next';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';

/**
 * Выбор существующей записи справочника ИЛИ ввод новой, одним полем.
 *
 * Смысл в том, чтобы заполняющий заявку на бюджет не уходил заводить
 * страну/программу/администратора в отдельные экраны и не возвращался.
 * Набранный текст, не совпавший ни с чем, предлагается создать прямо
 * здесь — но создаётся он не сразу, а на отправке всей формы, вместе с
 * бюджетом и в одной транзакции (POST /budgets/full). До этого момента
 * выбор живёт только в состоянии формы, поэтому брошенная на полпути
 * заявка не оставляет мусора в справочниках.
 *
 * Соответственно `value` — это либо `{ id }` (выбрано существующее), либо
 * `{ label }` (введено новое), либо null.
 */

export interface ReferenceOption {
  id: number;
  /** Что показывать в списке и в поле. */
  label: string;
  /** Необязательная вторая строка — например, статья расходов у программы. */
  hint?: string;
}

export type ReferenceValue =
  | { kind: 'existing'; id: number; label: string }
  | { kind: 'new'; label: string }
  | null;

interface Props {
  options: ReferenceOption[];
  value: ReferenceValue;
  onChange: (value: ReferenceValue) => void;
  placeholder: string;
  searchPlaceholder?: string;
  /** Подпись пункта «создать»: получает набранный текст. */
  createLabel?: (input: string) => string;
  disabled?: boolean;
  loading?: boolean;
  /** Показать поле как ошибочное (react-hook-form сюда не подключён). */
  invalid?: boolean;
  id?: string;
}

export function ReferenceCombobox({
  options,
  value,
  onChange,
  placeholder,
  searchPlaceholder,
  createLabel,
  disabled = false,
  loading = false,
  invalid = false,
  id,
}: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');

  const trimmed = search.trim();

  // Пункт «создать» показывается, только если набранное не совпадает
  // ТОЧНО с существующим вариантом — иначе рядом со «Казахстан» висел бы
  // соблазн создать второй «Казахстан».
  const canCreate = useMemo(() => {
    if (!trimmed) return false;
    return !options.some(
      (option) => option.label.toLowerCase() === trimmed.toLowerCase(),
    );
  }, [options, trimmed]);

  const select = (next: ReferenceValue) => {
    onChange(next);
    setOpen(false);
    setSearch('');
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled || loading}
          className={cn(
            'w-full justify-between font-normal',
            !value && 'text-muted-foreground',
            invalid && 'border-destructive',
          )}
        >
          <span className="truncate">
            {value
              ? value.kind === 'new'
                ? t('contracts.combobox.newRecordSuffix', { label: value.label })
                : value.label
              : loading
                ? t('signoff.loadingEllipsis')
                : placeholder}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>

      <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
        <Command
          // Фильтрация своя (по label + hint), встроенная бы не увидела hint.
          filter={(itemValue, searchValue) =>
            itemValue.toLowerCase().includes(searchValue.toLowerCase()) ? 1 : 0
          }
        >
          <CommandInput
            placeholder={searchPlaceholder ?? t('contracts.combobox.search')}
            value={search}
            onValueChange={setSearch}
          />
          <CommandList>
            {!canCreate && <CommandEmpty>{t('common.nothingFound')}</CommandEmpty>}

            {options.length > 0 && (
              <CommandGroup heading={t('contracts.combobox.existing')}>
                {options.map((option) => (
                  <CommandItem
                    key={option.id}
                    value={`${option.label} ${option.hint ?? ''}`}
                    onSelect={() =>
                      select({ kind: 'existing', id: option.id, label: option.label })
                    }
                  >
                    <Check
                      className={cn(
                        'mr-2 h-4 w-4',
                        value?.kind === 'existing' && value.id === option.id
                          ? 'opacity-100'
                          : 'opacity-0',
                      )}
                    />
                    <span className="flex flex-col">
                      <span>{option.label}</span>
                      {option.hint && (
                        <span className="text-xs text-muted-foreground">
                          {option.hint}
                        </span>
                      )}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            {canCreate && (
              <CommandGroup heading={t('contracts.combobox.newRecord')}>
                <CommandItem
                  value={trimmed}
                  onSelect={() => select({ kind: 'new', label: trimmed })}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  {createLabel
                    ? createLabel(trimmed)
                    : t('contracts.combobox.createNamed', { input: trimmed })}
                </CommandItem>
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
