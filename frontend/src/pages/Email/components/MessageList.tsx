import React from 'react';
import { useTranslation } from 'react-i18next';
import { format, isToday, isYesterday } from 'date-fns';
import { ru } from 'date-fns/locale';
import { Paperclip, Star } from 'lucide-react';
import type {
  EmailAccount,
  EmailMessageSummary,
} from '@/pages/Email/types';

interface Props {
  messages: EmailMessageSummary[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  accounts: EmailAccount[];
  /** Show the per-message account chip when looking at the unified view. */
  showAccountChip: boolean;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (isToday(d)) return format(d, 'HH:mm');
  if (isYesterday(d)) return format(d, 'HH:mm');
  return format(d, 'd MMM', { locale: ru });
}

function senderLabel(m: EmailMessageSummary): string {
  return m.sender_name || m.sender_email || '—';
}

export const MessageList: React.FC<Props> = ({
  messages,
  loading,
  selectedId,
  onSelect,
  accounts,
  showAccountChip,
}) => {
  const { t } = useTranslation();
  const accountsById = React.useMemo(() => {
    const m = new Map<number, EmailAccount>();
    for (const a of accounts) m.set(a.id, a);
    return m;
  }, [accounts]);

  if (loading && messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t('email.list.loading', 'Загрузка…')}
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center text-muted-foreground">
        <div className="text-sm">{t('email.list.empty', 'В этой папке пусто')}</div>
      </div>
    );
  }

  return (
    <ul className="divide-y">
      {messages.map((m) => {
        const isActive = m.id === selectedId;
        const account = m.account_id ? accountsById.get(m.account_id) : null;
        return (
          <li key={m.id}>
            <button
              type="button"
              onClick={() => onSelect(m.id)}
              className={`flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors ${
                isActive
                  ? 'bg-primary/10'
                  : 'hover:bg-muted'
              } ${m.is_read ? '' : 'font-semibold'}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm">{senderLabel(m)}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {fmtDate(m.date)}
                </span>
              </div>
              <div className="flex items-center gap-1 text-sm">
                {m.is_flagged && (
                  <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-500" />
                )}
                <span className="truncate">{m.subject || t('email.noSubject', '(без темы)')}</span>
                {m.has_attachments && (
                  <Paperclip className="h-3.5 w-3.5 text-muted-foreground" />
                )}
              </div>
              <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span className="truncate">{m.snippet}</span>
                {showAccountChip && account && (
                  <span className="shrink-0 rounded bg-muted px-1.5 py-0.5">
                    {account.address}
                  </span>
                )}
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
};

export default MessageList;
