import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useSendMessage } from '@/pages/Email/hooks/useSendMessage';
import type { EmailAccount } from '@/pages/Email/types';
import { replaceSignature } from '@/pages/Email/components/signature';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accounts: EmailAccount[];
  /** Default sender — usually the active account or the user's default. */
  defaultAccountId: number | null;
}

const LAST_SENDER_KEY = 'htq.email.compose.lastSenderId';


export const ComposeDialog: React.FC<Props> = ({
  open,
  onOpenChange,
  accounts,
  defaultAccountId,
}) => {
  const { t } = useTranslation();
  const send = useSendMessage();

  const writable = accounts.filter((a) => a.is_active);
  const initialSenderId = React.useMemo(() => {
    if (typeof window !== 'undefined') {
      const stored = window.localStorage.getItem(LAST_SENDER_KEY);
      const num = stored ? Number(stored) : NaN;
      if (!Number.isNaN(num) && writable.some((a) => a.id === num)) return num;
    }
    if (defaultAccountId && writable.some((a) => a.id === defaultAccountId)) {
      return defaultAccountId;
    }
    const def = writable.find((a) => a.is_default);
    return def?.id ?? writable[0]?.id ?? null;
  }, [defaultAccountId, writable]);

  const [senderId, setSenderId] = React.useState<number | null>(initialSenderId);
  const [to, setTo] = React.useState('');
  const [subject, setSubject] = React.useState('');
  const [body, setBody] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) {
      setError(null);
    } else {
      setSenderId(initialSenderId);
    }
  }, [open, initialSenderId]);

  // Подпись того адреса, с которого пишем. Держим предыдущую, чтобы при
  // смене отправителя заменить её, а не дописать вторую.
  const previousSignature = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    const next = writable.find((a) => a.id === senderId)?.signature ?? '';
    setBody((current) => replaceSignature(current, previousSignature.current, next));
    previousSignature.current = next;
    // writable пересобирается каждый рендер — завязываться на него нельзя,
    // иначе подпись переставлялась бы бесконечно.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, senderId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!senderId) {
      setError(t('email.compose.selectSender', 'Выберите аккаунт-отправитель'));
      return;
    }
    const recipients = to
      .split(/[,;\s]+/)
      .map((s) => s.trim())
      .filter((s) => s.includes('@'))
      .map((email) => ({ email }));
    if (recipients.length === 0) {
      setError(t('email.compose.recipientsRequired', 'Укажите хотя бы одного получателя'));
      return;
    }
    try {
      await send.mutateAsync({
        account_id: senderId,
        to_recipients: recipients,
        subject,
        body_text: body,
      });
      window.localStorage.setItem(LAST_SENDER_KEY, String(senderId));
      onOpenChange(false);
      setTo('');
      setSubject('');
      setBody('');
    } catch (e: any) {
      setError(
        e?.response?.data?.detail ||
          e?.message ||
          t('email.errors.send', 'Не удалось отправить'),
      );
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('email.compose.title', 'Новое письмо')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('email.compose.from', 'От кого')}
            </label>
            <Select
              value={senderId ? String(senderId) : ''}
              onValueChange={(v) => setSenderId(Number(v))}
            >
              <SelectTrigger>
                <SelectValue
                  placeholder={t('email.compose.selectSender', 'Выберите аккаунт')}
                />
              </SelectTrigger>
              <SelectContent>
                {writable.map((a) => (
                  <SelectItem key={a.id} value={String(a.id)}>
                    {a.address}
                    {a.is_default && (
                      <span className="ml-2 text-xs text-muted-foreground">
                        ({t('email.accounts.default', 'основной')})
                      </span>
                    )}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('email.compose.to', 'Кому')}
            </label>
            <Input
              type="text"
              placeholder="user@example.com, …"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('email.compose.subject', 'Тема')}
            </label>
            <Input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('email.compose.body', 'Сообщение')}
            </label>
            <Textarea
              rows={10}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              {t('email.compose.cancel', 'Отмена')}
            </Button>
            <Button type="submit" disabled={send.isPending}>
              {send.isPending
                ? t('email.compose.sending', 'Отправка…')
                : t('email.compose.send', 'Отправить')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default ComposeDialog;
