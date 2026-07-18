import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Pencil, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

import { EmailLayout } from '@/pages/Email/layout/EmailLayout';
import { AccountSelector } from '@/pages/Email/components/AccountSelector';
import { FolderList } from '@/pages/Email/components/FolderList';
import { MessageList } from '@/pages/Email/components/MessageList';
import { MessageView } from '@/pages/Email/components/MessageView';
import { ComposeDialog } from '@/pages/Email/components/ComposeDialog';
import { ConnectAccountDialog } from '@/pages/Email/components/ConnectAccountDialog';

import {
  useEmailAccounts,
  useSyncAccount,
} from '@/pages/Email/hooks/useEmailAccounts';
import { useUnreadCounts } from '@/pages/Email/hooks/useUnreadCounts';
import { useFolderQuery } from '@/pages/Email/hooks/useFolderQuery';
import {
  useMarkRead,
  useMessageDetail,
} from '@/pages/Email/hooks/useMessageDetail';
import type { ActiveAccountId, Folder } from '@/pages/Email/types';

const ACTIVE_ACCOUNT_KEY = 'htq.email.activeAccountId';
const ACTIVE_FOLDER_KEY = 'htq.email.activeFolder';

function readStoredAccountId(): ActiveAccountId {
  if (typeof window === 'undefined') return 'all';
  const v = window.localStorage.getItem(ACTIVE_ACCOUNT_KEY);
  if (v === 'all' || v === null) return 'all';
  const n = Number(v);
  return Number.isNaN(n) ? 'all' : n;
}

function readStoredFolder(): Folder {
  if (typeof window === 'undefined') return 'inbox';
  const v = window.localStorage.getItem(ACTIVE_FOLDER_KEY);
  const valid: Folder[] = ['inbox', 'sent', 'drafts', 'trash', 'archive', 'spam'];
  return (valid.includes(v as Folder) ? v : 'inbox') as Folder;
}

export default function EmailPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();

  const accountsQuery = useEmailAccounts();
  const accounts = accountsQuery.data ?? [];
  const unreadQuery = useUnreadCounts();
  const unread = unreadQuery.data ?? { by_account: {}, by_folder: {} };

  // Active account: URL ?account=N wins, otherwise localStorage, otherwise 'all'.
  const initialAccountId = React.useMemo<ActiveAccountId>(() => {
    const fromUrl = searchParams.get('account');
    if (fromUrl === 'all') return 'all';
    if (fromUrl) {
      const n = Number(fromUrl);
      if (!Number.isNaN(n)) return n;
    }
    return readStoredAccountId();
  }, [searchParams]);

  const initialFolder = (searchParams.get('folder') as Folder | null) || readStoredFolder();
  const initialMessageId = searchParams.get('id');

  const [activeAccountId, setActiveAccountId] =
    React.useState<ActiveAccountId>(initialAccountId);
  const [folder, setFolder] = React.useState<Folder>(initialFolder);
  const [selectedId, setSelectedId] = React.useState<string | null>(initialMessageId);
  const [composeOpen, setComposeOpen] = React.useState(false);
  const [connectOpen, setConnectOpen] = React.useState(false);

  // Persist active selections.
  React.useEffect(() => {
    window.localStorage.setItem(ACTIVE_ACCOUNT_KEY, String(activeAccountId));
    window.localStorage.setItem(ACTIVE_FOLDER_KEY, folder);
    const next = new URLSearchParams(searchParams);
    next.set('account', String(activeAccountId));
    next.set('folder', folder);
    if (selectedId) next.set('id', selectedId);
    else next.delete('id');
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeAccountId, folder, selectedId]);

  // Reset selection when switching account/folder so we don't show a
  // message from the previous context.
  React.useEffect(() => {
    setSelectedId(null);
  }, [activeAccountId, folder]);

  const messagesQuery = useFolderQuery(activeAccountId, folder);
  const messages = messagesQuery.data ?? [];

  const detailQuery = useMessageDetail(selectedId);
  const markRead = useMarkRead();
  React.useEffect(() => {
    if (detailQuery.data && !detailQuery.data.is_read && selectedId) {
      markRead.mutate(selectedId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailQuery.data?.id]);

  const syncMutation = useSyncAccount();
  const onRefresh = () => {
    if (activeAccountId === 'all') {
      accounts.forEach((a) => syncMutation.mutate(a.id));
    } else {
      syncMutation.mutate(activeAccountId);
    }
    accountsQuery.refetch();
    messagesQuery.refetch();
    unreadQuery.refetch();
  };

  const defaultSenderId = React.useMemo<number | null>(() => {
    if (activeAccountId !== 'all') return activeAccountId;
    const def = accounts.find((a) => a.is_default);
    return def?.id ?? accounts[0]?.id ?? null;
  }, [accounts, activeAccountId]);

  const sidebar = (
    <div className="flex flex-col gap-4">
      <Button
        type="button"
        className="w-full justify-start gap-2"
        onClick={() => setComposeOpen(true)}
        disabled={accounts.filter((a) => a.is_active).length === 0}
      >
        <Pencil className="h-4 w-4" />
        {t('email.compose.new', 'Новое письмо')}
      </Button>
      <AccountSelector
        accounts={accounts}
        activeId={activeAccountId}
        onChange={setActiveAccountId}
        unreadByAccount={unread.by_account}
        onAddAccount={() => setConnectOpen(true)}
      />
      <FolderList
        active={folder}
        onSelect={setFolder}
        unreadByFolder={unread.by_folder}
      />
    </div>
  );

  return (
    <EmailLayout sidebar={sidebar}>
      <div className="flex h-[calc(100vh-200px)] min-h-[500px] overflow-hidden rounded-2xl border bg-card shadow-[var(--shadow-soft)]">
        <div className="flex w-full flex-col lg:w-[380px] lg:border-r">
          <div className="flex items-center justify-between border-b p-3">
            <div className="text-sm font-semibold">
              {t(`email.folders.${folder}`, folder)}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onRefresh}
              disabled={syncMutation.isPending}
              title={t('email.actions.refresh', 'Обновить')}
            >
              <RefreshCw
                className={`h-4 w-4 ${
                  syncMutation.isPending ? 'animate-spin' : ''
                }`}
              />
            </Button>
          </div>
          <div className="flex-1 overflow-auto">
            <MessageList
              messages={messages}
              loading={messagesQuery.isLoading}
              selectedId={selectedId}
              onSelect={setSelectedId}
              accounts={accounts}
              showAccountChip={activeAccountId === 'all'}
            />
          </div>
        </div>
        <div className={`hidden flex-1 lg:block ${selectedId ? '' : ''}`}>
          <MessageView
            message={detailQuery.data ?? null}
            loading={detailQuery.isLoading}
          />
        </div>
        {selectedId && (
          <div className="absolute inset-0 z-10 flex bg-card lg:hidden">
            <div className="flex-1">
              <MessageView
                message={detailQuery.data ?? null}
                loading={detailQuery.isLoading}
                onBack={() => setSelectedId(null)}
              />
            </div>
          </div>
        )}
      </div>

      <ComposeDialog
        open={composeOpen}
        onOpenChange={setComposeOpen}
        accounts={accounts}
        defaultAccountId={defaultSenderId}
      />
      <ConnectAccountDialog
        open={connectOpen}
        onOpenChange={setConnectOpen}
        accounts={accounts}
      />
    </EmailLayout>
  );
}
