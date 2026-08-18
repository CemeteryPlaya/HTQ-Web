/**
 * Выбор согласующих этапа — поимённо.
 *
 * Именно поимённо, а не по роли или группе: платформенных групп нет,
 * `User` сознательно без `PermissionsMixin`, и маршрут перечисляет
 * конкретные user id. Смысл этапа несёт его НАЗВАНИЕ («Финансовый
 * контроль»), а не роль исполнителя.
 *
 * Список берётся из администраторского реестра аккаунтов
 * (`users/v1/admin/users/`) — тот же, что показывает /admin/users. Страница
 * маршрутов и так админская, чужого доступа это не открывает.
 *
 * Деактивированные аккаунты не прячутся, а помечаются: этап, где ВСЕ
 * согласующие деактивированы, движок не запустит (409), и увидеть причину
 * надо здесь, а не в момент чужой неудачной отправки.
 */

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Check, ChevronsUpDown, X } from 'lucide-react';

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
import { fetchPlatformAccounts, type PlatformAccount } from '@/api/accounts';
import { cn } from '@/lib/utils';

function accountLabel(account: PlatformAccount): string {
  const full = [account.last_name, account.first_name].filter(Boolean).join(' ');
  return account.display_name || full || account.username || account.email;
}

interface Props {
  value: number[];
  onChange: (ids: number[]) => void;
  /** Имена уже выбранных, если аккаунты ещё не загрузились (карточка этапа
   *  приходит с бэкенда уже с `full_name`). */
  knownNames?: Record<number, string>;
  disabled?: boolean;
}

export function ApproverPicker({ value, onChange, knownNames = {}, disabled }: Props) {
  const [open, setOpen] = useState(false);

  const { data: accounts = [], isLoading } = useQuery({
    queryKey: ['platform-accounts'],
    queryFn: fetchPlatformAccounts,
    staleTime: 5 * 60 * 1000,
  });

  const byId = useMemo(
    () => new Map(accounts.map((account) => [account.id, account])),
    [accounts],
  );

  const toggle = (id: number) =>
    onChange(value.includes(id) ? value.filter((row) => row !== id) : [...value, id]);

  const nameOf = (id: number) => {
    const account = byId.get(id);
    return account ? accountLabel(account) : knownNames[id] ?? `Пользователь #${id}`;
  };

  return (
    <div className="space-y-2">
      {/* modal обязателен: этот выбор используется внутри диалога, а тот на
    время открытия блокирует прокрутку документа и пропускает события
    только внутри своего поддерева. Содержимое поповера рендерится
    порталом в body, то есть снаружи, — и список согласующих переставал
    прокручиваться колесом, оставаясь прокручиваемым технически.
    С modal поповер ставит собственную блокировку. */}
      <Popover modal open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            role="combobox"
            aria-expanded={open}
            disabled={disabled}
            className="w-full justify-between font-normal"
          >
            {value.length === 0
              ? 'Выберите согласующих'
              : `Выбрано: ${value.length}`}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
          <Command>
            <CommandInput placeholder="Поиск по имени или почте" />
            <CommandList>
              <CommandEmpty>
                {isLoading ? 'Загрузка…' : 'Никого не найдено'}
              </CommandEmpty>
              <CommandGroup>
                {accounts.map((account) => {
                  const selected = value.includes(account.id);
                  return (
                    <CommandItem
                      key={account.id}
                      // Radix ищет по value, поэтому в него кладётся всё, по
                      // чему разумно искать человека.
                      value={`${accountLabel(account)} ${account.email} ${account.username}`}
                      onSelect={() => toggle(account.id)}
                    >
                      <Check
                        className={cn(
                          'mr-2 h-4 w-4',
                          selected ? 'opacity-100' : 'opacity-0',
                        )}
                      />
                      <span className="flex-1 min-w-0">
                        <span className="block truncate">{accountLabel(account)}</span>
                        <span className="block text-xs text-muted-foreground truncate">
                          {account.email}
                        </span>
                      </span>
                      {account.status !== 'active' && (
                        <Badge variant="outline" className="ml-2 text-muted-foreground">
                          {account.status === 'pending' ? 'не активирован' : 'отключён'}
                        </Badge>
                      )}
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
            const account = byId.get(id);
            const inactive = account !== undefined && account.status !== 'active';
            return (
              <Badge
                key={id}
                variant="secondary"
                className={cn('gap-1', inactive && 'opacity-60')}
              >
                {nameOf(id)}
                {inactive && ' (отключён)'}
                {!disabled && (
                  <button
                    type="button"
                    onClick={() => toggle(id)}
                    aria-label={`Убрать ${nameOf(id)}`}
                    className="hover:text-destructive"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </Badge>
            );
          })}
        </div>
      )}
    </div>
  );
}
