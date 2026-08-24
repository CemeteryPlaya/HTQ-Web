import { useState, useMemo } from 'react';
import { Check, ChevronsUpDown, Search, UserRound, BriefcaseBusiness, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Badge } from '@/components/ui/badge';
import { useTranslation } from 'react-i18next';

export interface EntityOption {
  id: number;
  label: string;
  subLabel?: string | null;
  departmentName?: string | null;
  avatarUrl?: string | null;
  level?: number | null;
  grade?: number | null;
  type?: 'employee' | 'position';
}

interface SingleProps {
  mode?: 'single';
  value: string;
  onChange: (value: string) => void;
}

interface MultiProps {
  mode: 'multi';
  value: string[];
  onChange: (value: string[]) => void;
}

type EntityComboboxProps = (SingleProps | MultiProps) & {
  options: EntityOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  className?: string;
  disabled?: boolean;
};

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] ?? '' : '';
  return (first + last).toUpperCase() || '?';
}

export function EntityCombobox(props: EntityComboboxProps) {
  const { t } = useTranslation();
  const {
    options,
    placeholder = t('hr.orgChart.pickFromList'),
    searchPlaceholder = t('hr.orgChart.searchEntity'),
    emptyText = t('common.nothingFound'),
    className,
    disabled = false,
  } = props;

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');

  const optionMap = useMemo(() => {
    const map = new Map<string, EntityOption>();
    options.forEach((opt) => map.set(String(opt.id), opt));
    return map;
  }, [options]);

  const filteredOptions = useMemo(() => {
    if (!search.trim()) return options;
    const query = search.toLowerCase();
    return options.filter((opt) => {
      const labelMatch = opt.label.toLowerCase().includes(query);
      const subMatch = opt.subLabel?.toLowerCase().includes(query);
      const deptMatch = opt.departmentName?.toLowerCase().includes(query);
      return labelMatch || subMatch || deptMatch;
    });
  }, [options, search]);

  const isMulti = props.mode === 'multi';

  // Selected labels for preview
  const renderTriggerContent = () => {
    if (isMulti) {
      const selectedIds = props.value;
      if (selectedIds.length === 0) {
        return <span className="text-muted-foreground">{placeholder}</span>;
      }
      if (selectedIds.length === 1) {
        const item = optionMap.get(selectedIds[0]);
        return (
          <span className="truncate font-medium">
            {item ? item.label : selectedIds[0]}
          </span>
        );
      }
      return (
        <div className="flex items-center gap-1.5 overflow-hidden">
          <Badge variant="secondary" className="px-1.5 py-0 text-xs font-semibold">
            {t('calendar.selectedCount', { count: selectedIds.length })}
          </Badge>
          <span className="truncate text-xs text-muted-foreground">
            {selectedIds.map((id) => optionMap.get(id)?.label ?? id).join(', ')}
          </span>
        </div>
      );
    }

    const selectedId = props.value;
    if (!selectedId) {
      return <span className="text-muted-foreground">{placeholder}</span>;
    }
    const item = optionMap.get(selectedId);
    if (!item) return <span className="text-muted-foreground">{placeholder}</span>;

    return (
      <div className="flex items-center gap-2 truncate">
        {item.avatarUrl ? (
          <img src={item.avatarUrl} alt="" className="h-5 w-5 rounded-full object-cover shrink-0" />
        ) : (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
            {getInitials(item.label)}
          </span>
        )}
        <span className="truncate font-medium">{item.label}</span>
        {item.departmentName && (
          <span className="text-xs text-muted-foreground truncate hidden sm:inline">
            · {item.departmentName}
          </span>
        )}
      </div>
    );
  };

  const handleSelect = (idStr: string) => {
    if (isMulti) {
      const current = props.value;
      const next = current.includes(idStr)
        ? current.filter((x) => x !== idStr)
        : [...current, idStr];
      props.onChange(next);
    } else {
      props.onChange(idStr);
      setOpen(false);
    }
  };

  const handleRemoveItem = (idStr: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (isMulti) {
      props.onChange(props.value.filter((x) => x !== idStr));
    } else {
      props.onChange('');
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn(
            'h-9 w-full justify-between px-3 text-left font-normal bg-background/80 hover:bg-background transition-all border-border/80 shadow-xs hover:border-primary/50',
            className,
          )}
        >
          <div className="flex items-center gap-2 truncate flex-1 min-w-0">
            {renderTriggerContent()}
          </div>
          <div className="flex items-center gap-1 shrink-0 ml-1">
            {(!isMulti && props.value) && (
              <span
                role="button"
                tabIndex={0}
                className="rounded-full p-0.5 hover:bg-muted text-muted-foreground hover:text-foreground"
                onClick={(e) => handleRemoveItem(props.value, e)}
              >
                <X className="h-3.5 w-3.5" />
              </span>
            )}
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </div>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[340px] sm:w-[380px] p-0 shadow-lg border-border" align="start">
        <Command shouldFilter={false} className="max-h-[380px]">
          <div className="flex items-center border-b px-2.5">
            <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={searchPlaceholder}
              className="flex h-10 w-full rounded-md bg-transparent py-2 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
            />
            {search && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
                onClick={() => setSearch('')}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
          <CommandList className="max-h-[280px] overflow-y-auto p-1">
            {filteredOptions.length === 0 ? (
              <CommandEmpty className="py-6 text-center text-xs text-muted-foreground">
                {emptyText}
              </CommandEmpty>
            ) : (
              <CommandGroup>
                {filteredOptions.map((option) => {
                  const idStr = String(option.id);
                  const isSelected = isMulti
                    ? props.value.includes(idStr)
                    : props.value === idStr;

                  return (
                    <CommandItem
                      key={option.id}
                      value={idStr}
                      onSelect={() => handleSelect(idStr)}
                      className={cn(
                        'flex items-center justify-between gap-2.5 px-2.5 py-2 rounded-md cursor-pointer transition-colors text-sm',
                        isSelected ? 'bg-primary/10 text-primary font-medium' : 'hover:bg-accent/60',
                      )}
                    >
                      <div className="flex items-center gap-2.5 min-w-0 flex-1">
                        {option.avatarUrl ? (
                          <img
                            src={option.avatarUrl}
                            alt=""
                            className="h-8 w-8 rounded-full object-cover shrink-0 ring-1 ring-border"
                          />
                        ) : (
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted font-bold text-xs text-foreground/80 ring-1 ring-border">
                            {option.type === 'position' ? (
                              <BriefcaseBusiness className="h-4 w-4 text-muted-foreground" />
                            ) : option.label ? (
                              getInitials(option.label)
                            ) : (
                              <UserRound className="h-4 w-4 text-muted-foreground" />
                            )}
                          </span>
                        )}

                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="truncate text-xs font-semibold leading-snug">
                              {option.label}
                            </span>
                            {option.level != null && (
                              <Badge variant="outline" className="text-[10px] px-1 py-0 h-4 shrink-0 font-normal">
                                L{option.level}
                              </Badge>
                            )}
                          </div>
                          {(option.subLabel || option.departmentName) && (
                            <p className="truncate text-[11px] text-muted-foreground leading-tight mt-0.5">
                              {[option.subLabel, option.departmentName].filter(Boolean).join(' · ')}
                            </p>
                          )}
                        </div>
                      </div>

                      <div className="shrink-0 pl-1">
                        {isSelected ? (
                          <div className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                            <Check className="h-3 w-3 stroke-[3]" />
                          </div>
                        ) : (
                          <div className="h-5 w-5 rounded-full border border-border/80" />
                        )}
                      </div>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            )}
          </CommandList>
          {isMulti && (
            <div className="flex items-center justify-between border-t p-2 bg-muted/30">
              <span className="text-xs text-muted-foreground">
                {t('calendar.selectedCount', { count: props.value.length })}
              </span>
              <div className="flex gap-1.5">
                {props.value.length > 0 && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-xs"
                    onClick={() => props.onChange([])}
                  >
                    {t('common.reset')}
                  </Button>
                )}
                <Button
                  size="sm"
                  className="h-7 px-3 text-xs"
                  onClick={() => setOpen(false)}
                >
                  {t('common.done')}
                </Button>
              </div>
            </div>
          )}
        </Command>
      </PopoverContent>
    </Popover>
  );
}
