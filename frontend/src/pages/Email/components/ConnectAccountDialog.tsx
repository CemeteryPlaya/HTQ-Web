import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { useStartConnect } from '@/pages/Email/hooks/useSendMessage';
import { useDisconnectAccount } from '@/pages/Email/hooks/useEmailAccounts';
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
              'Корпоративный ящик создаёт администратор. Личные Gmail / Outlook можно подключить здесь.',
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
                  className="flex items-center justify-between gap-2 px-3 py-2"
                >
                  <div className="flex flex-col">
                    <span className="text-sm font-medium">{acc.address}</span>
                    <span className="text-xs text-muted-foreground capitalize">
                      {acc.provider}
                    </span>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => disconnect.mutate(acc.id)}
                  >
                    {t('email.accounts.disconnect', 'Отключить')}
                  </Button>
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
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ConnectAccountDialog;
