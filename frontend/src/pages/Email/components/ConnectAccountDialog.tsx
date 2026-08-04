import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Server, AlertTriangle, KeyRound } from 'lucide-react';

import api from '@/api/client';
import { Input } from '@/components/ui/input';

import { Button } from '@/components/ui/button';
import { useStartConnect } from '@/pages/Email/hooks/useSendMessage';
import { useDisconnectAccount } from '@/pages/Email/hooks/useEmailAccounts';
import { ConnectImapAccount } from '@/components/mail/ConnectImapAccount';
import type { EmailAccount } from '@/pages/Email/types';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accounts: EmailAccount[];
}

export const ConnectAccountDialog: React.FC<Props> = ({
  open,
  onOpenChange,
  accounts,
}) => {
  const { t } = useTranslation();
  const startConnect = useStartConnect();
  const disconnect = useDisconnectAccount();
  const [error, setError] = React.useState<string | null>(null);
  const [imapOpen, setImapOpen] = React.useState(false);
  // Починка сломанного IMAP-аккаунта: пароль сменили на сервере, и
  // синхронизация встала. Без этого её нельзя было восстановить из
  // интерфейса — только отключить аккаунт и подключить заново.
  const [fixingId, setFixingId] = React.useState<number | null>(null);
  const [newPassword, setNewPassword] = React.useState('');
  const [fixBusy, setFixBusy] = React.useState(false);

  const submitPassword = async (accountId: number) => {
    setFixBusy(true);
    setError(null);
    try {
      await api.post(`email/v1/accounts/${accountId}/imap-password/`, {
        password: newPassword,
      });
      setFixingId(null);
      setNewPassword('');
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(detail || t('email.accounts.passwordError', 'Пароль не принят сервером'));
    } finally {
      setFixBusy(false);
    }
  };

  const personal = accounts.filter((a) => a.type === 'personal');

  const handleConnect = async (provider: 'google' | 'microsoft') => {
    setError(null);
    try {
      const res = await startConnect.mutateAsync(provider);
      window.location.href = res.auth_url;
    } catch (e: any) {
      setError(
        e?.response?.data?.detail ||
          e?.message ||
          t('email.errors.connect', 'Не удалось начать подключение'),
      );
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t('email.accounts.manageTitle', 'Подключённые аккаунты')}
          </DialogTitle>
          <DialogDescription>
            {t(
              'email.accounts.manageDescription',
              'Корпоративный ящик создаёт администратор. Личные Gmail / Outlook подключаются здесь, а любую другую почту можно добавить по IMAP.',
            )}
          </DialogDescription>
        </DialogHeader>

        {personal.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              {t('email.accounts.personal', 'Личные')}
            </div>
            <ul className="divide-y rounded border">
              {personal.map((acc) => (
                <li
                  key={acc.id}
                  className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
                >
                  <div className="flex min-w-0 flex-col">
                    <span className="text-sm font-medium">{acc.address}</span>
                    <span className="text-xs text-muted-foreground capitalize">
                      {acc.provider}
                    </span>
                    {acc.last_sync_error && (
                      <span className="mt-0.5 flex items-start gap-1 text-xs text-destructive">
                        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                        <span className="break-words">{acc.last_sync_error}</span>
                      </span>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-1">
                    {acc.provider === 'imap' && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        title={t('email.accounts.updatePassword', 'Обновить пароль')}
                        onClick={() =>
                          setFixingId(fixingId === acc.id ? null : acc.id)
                        }
                      >
                        <KeyRound className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => disconnect.mutate(acc.id)}
                    >
                      {t('email.accounts.disconnect', 'Отключить')}
                    </Button>
                  </div>
                  {fixingId === acc.id && (
                    <div className="mt-2 flex w-full gap-2">
                      <Input
                        type="password"
                        autoFocus
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        placeholder={t(
                          'email.accounts.newPasswordPlaceholder',
                          'новый пароль ящика',
                        )}
                      />
                      <Button
                        type="button"
                        size="sm"
                        disabled={!newPassword || fixBusy}
                        onClick={() => submitPassword(acc.id)}
                      >
                        {fixBusy
                          ? t('email.accounts.checking', 'Проверяем…')
                          : t('email.accounts.save', 'Сохранить')}
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="space-y-2">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">
            {t('email.accounts.add', 'Добавить аккаунт')}
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleConnect('google')}
              disabled={startConnect.isPending}
            >
              🟢 Google
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleConnect('microsoft')}
              disabled={startConnect.isPending}
            >
              🟦 Outlook
            </Button>
          </div>
          {/* Всё, что не Google и не Outlook, — через IMAP: у такой почты
              нет OAuth, и без этой кнопки её нельзя было подключить вовсе. */}
          <Button
            type="button"
            variant="outline"
            className="w-full gap-2"
            onClick={() => setImapOpen(true)}
          >
            <Server className="h-4 w-4" />
            {t('email.accounts.addImap', 'Другая почта (IMAP)')}
          </Button>
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>
      </DialogContent>

      <ConnectImapAccount open={imapOpen} onClose={() => setImapOpen(false)} />
    </Dialog>
  );
};

export default ConnectAccountDialog;
