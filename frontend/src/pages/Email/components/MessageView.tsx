import React from 'react';
import { useTranslation } from 'react-i18next';
import { format } from 'date-fns';
import { ru } from 'date-fns/locale';
import { ArrowLeft, Paperclip } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { EmailMessageDetail } from '@/pages/Email/types';

interface Props {
  message: EmailMessageDetail | null;
  loading: boolean;
  onBack?: () => void;
}

function fmtRecipients(rs: { email: string; name?: string | null }[]): string {
  return rs.map((r) => (r.name ? `${r.name} <${r.email}>` : r.email)).join(', ');
}

export const MessageView: React.FC<Props> = ({ message, loading, onBack }) => {
  const { t } = useTranslation();

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t('email.view.loading', 'Загрузка…')}
      </div>
    );
  }
  if (!message) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-8 text-center text-muted-foreground">
        <div className="text-sm">{t('email.view.empty', 'Выберите письмо для просмотра')}</div>
      </div>
    );
  }

  // Render HTML inside a sandboxed iframe — no JS, no parent navigation,
  // no plugin loading. Equivalent to (and stronger than) DOMPurify because
  // the iframe enforces isolation at the browser level.
  const htmlBody = message.body_html || null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b p-4">
        {onBack && (
          <Button variant="ghost" size="sm" onClick={onBack} className="lg:hidden">
            <ArrowLeft className="mr-1 h-4 w-4" /> {t('email.view.back', 'Назад')}
          </Button>
        )}
        <h2 className="text-lg font-semibold leading-tight">
          {message.subject || t('email.noSubject', '(без темы)')}
        </h2>
      </div>

      <div className="space-y-2 border-b p-4 text-sm">
        <div>
          <span className="text-muted-foreground">{t('email.view.from', 'От')}: </span>
          <span className="font-medium">
            {message.sender_name
              ? `${message.sender_name} <${message.sender_email}>`
              : message.sender_email}
          </span>
        </div>
        {message.to_recipients?.length > 0 && (
          <div>
            <span className="text-muted-foreground">{t('email.view.to', 'Кому')}: </span>
            <span>{fmtRecipients(message.to_recipients)}</span>
          </div>
        )}
        {message.cc_recipients?.length > 0 && (
          <div>
            <span className="text-muted-foreground">{t('email.view.cc', 'Копия')}: </span>
            <span>{fmtRecipients(message.cc_recipients)}</span>
          </div>
        )}
        <div className="text-xs text-muted-foreground">
          {format(new Date(message.date), 'd MMMM yyyy, HH:mm', { locale: ru })}
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {htmlBody ? (
          <iframe
            title="email-body"
            sandbox=""
            srcDoc={htmlBody}
            className="h-full w-full min-h-[400px] rounded border"
          />
        ) : (
          <pre className="whitespace-pre-wrap text-sm">{message.body_text || ''}</pre>
        )}
      </div>

      {message.attachments && message.attachments.length > 0 && (
        <div className="border-t p-4">
          <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
            {t('email.view.attachments', 'Вложения')}
          </div>
          <ul className="grid gap-2 sm:grid-cols-2">
            {message.attachments.map((a) => (
              <li
                key={a.id}
                className="flex items-center gap-2 rounded-lg border p-2 text-sm"
              >
                <Paperclip className="h-4 w-4 text-muted-foreground" />
                <span className="flex-1 truncate">{a.filename}</span>
                <span className="text-xs text-muted-foreground">
                  {Math.round(a.size / 1024)} KB
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default MessageView;
