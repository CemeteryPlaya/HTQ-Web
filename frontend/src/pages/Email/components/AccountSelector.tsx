import React from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, Inbox, Mail, Plus, Server, AlertTriangle } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type { ActiveAccountId, EmailAccount } from '@/pages/Email/types';

interface Props {
  accounts: EmailAccount[];
  activeId: ActiveAccountId;
  onChange: (id: ActiveAccountId) => void;
  unreadByAccount: Record<string, number>;
  onAddAccount: () => void;
  onAddImap: () => void;
}

function providerEmoji(provider: string): string {
  if (provider === 'google') return '🟢';
  if (provider === 'microsoft') return '🟦';
  if (provider === 'imap') return '📨'; // свой сервер, подключён пользователем
  return '🏢'; // mailcow / corporate
}

function totalUnread(unreadByAccount: Record<string, number>): number {
  return Object.values(unreadByAccount).reduce((a, b) => a + (b || 0), 0);
}

export const AccountSelector: React.FC<Props> = ({
  accounts,
  activeId,
  onChange,
  unreadByAccount,
  onAddAccount,
  onAddImap,
}) => {
  const { t } = useTranslation();
  const active =
    activeId === 'all'
      ? null
      : accounts.find((a) => a.id === activeId) ?? null;
  const triggerLabel = active
    ? active.address
    : t('email.accounts.unifiedView', 'Все аккаунты');
  const triggerUnread = active
    ? unreadByAccount[String(active.id)] || 0
    : totalUnread(unreadByAccount);

  return (
    // modal={false} — не косметика, а лечение полностью мёртвой страницы.
    //
    // Пункты этого меню открывают диалоги («Подключить аккаунт», «Другая
    // почта (IMAP)»). И меню, и диалог по-своему ставят на body
    // `pointer-events: none` и снимают это каждый в своём обработчике.
    // Меню закрывается в момент клика — раньше, чем диалог возьмёт
    // блокировку на себя, — и снятие происходит не в том порядке: диалог
    // уходит, а `pointer-events: none` остаётся навсегда. Внешне страница
    // выглядит обычной, но не принимает ни одного клика до перезагрузки.
    //
    // Немодальному меню собственная блокировка не нужна, и конфликтовать
    // становится нечему.
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="mb-3 flex w-full items-center justify-between gap-2 rounded-lg border bg-background px-3 py-2 text-left text-sm font-medium shadow-sm hover:bg-accent"
        >
          <span className="flex min-w-0 items-center gap-2">
            <span>{active ? providerEmoji(active.provider) : '📬'}</span>
            <span className="truncate">{triggerLabel}</span>
          </span>
          <span className="flex items-center gap-2">
            {triggerUnread > 0 && (
              <span className="rounded-full bg-primary px-2 py-0.5 text-xs text-primary-foreground">
                {triggerUnread}
              </span>
            )}
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>
          {t('email.accounts.switch', 'Переключить аккаунт')}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => onChange('all')}>
          <Inbox className="mr-2 h-4 w-4" />
          <span className="flex-1">
            {t('email.accounts.unifiedView', 'Все аккаунты')}
          </span>
          {totalUnread(unreadByAccount) > 0 && (
            <span className="ml-2 text-xs text-muted-foreground">
              {totalUnread(unreadByAccount)}
            </span>
          )}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {accounts.length === 0 && (
          <DropdownMenuItem disabled>
            <Mail className="mr-2 h-4 w-4 text-muted-foreground" />
            {t('email.accounts.empty', 'Нет подключённых аккаунтов')}
          </DropdownMenuItem>
        )}
        {accounts.map((acc) => {
          const unread = unreadByAccount[String(acc.id)] || 0;
          return (
            <DropdownMenuItem key={acc.id} onClick={() => onChange(acc.id)}>
              <span className="mr-2">{providerEmoji(acc.provider)}</span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate">{acc.address}</span>
                {acc.is_default && !acc.last_sync_error && (
                  <span className="text-xs text-muted-foreground">
                    {t('email.accounts.default', 'основной')}
                  </span>
                )}
                {acc.last_sync_error && (
                  <span className="flex items-center gap-1 text-xs text-destructive">
                    <AlertTriangle className="h-3 w-3 shrink-0" />
                    {t('email.accounts.syncFailed', 'синхронизация не идёт')}
                  </span>
                )}
              </span>
              {unread > 0 && (
                <span className="ml-2 rounded-full bg-primary px-1.5 py-0.5 text-xs text-primary-foreground">
                  {unread}
                </span>
              )}
            </DropdownMenuItem>
          );
        })}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={onAddAccount}>
          <Plus className="mr-2 h-4 w-4" />
          {t('email.accounts.connect', 'Подключить аккаунт')}
        </DropdownMenuItem>
        {/* Отдельным пунктом: внутри диалога эту кнопку не находят —
            до неё три клика, и она не видна из списка аккаунтов. */}
        <DropdownMenuItem onClick={onAddImap}>
          <Server className="mr-2 h-4 w-4" />
          {t('email.accounts.addImap', 'Другая почта (IMAP)')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default AccountSelector;
