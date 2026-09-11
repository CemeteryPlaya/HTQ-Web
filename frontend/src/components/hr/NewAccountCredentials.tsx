import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Copy, KeyRound, TriangleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { copyText } from '@/lib/clipboard';

/**
 * Доступы только что заведённой учётки — показываются ОДИН раз.
 *
 * Зачем экран вообще существует: HR-форма заводит учётку со случайным
 * паролем, который сервер нигде не хранит в открытом виде. Пока этот пароль
 * не показывали, заведённый сотрудник войти не мог — оставался только сброс
 * через `/admin/users`, о котором HR не знает.
 *
 * Панель, а не тост (как у почтовых ящиков в AdminMailboxes): тост можно
 * смахнуть мимоходом, и тогда единственный способ войти потерян. Здесь
 * человек закрывает окно сам, подтверждая, что забрал пароль.
 */

interface Props {
  credentials: { email: string; password: string };
  onDone: () => void;
}

const NewAccountCredentials = ({ credentials, onDone }: Props) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  const copy = async () => {
    const text = `${credentials.email}\n${credentials.password}`;
    // copyText не бросает, а возвращает false: буфер обмена бывает недоступен
    // (не защищённый контекст, отказ в правах). Сказать «Скопировано», когда
    // ничего не скопировано, здесь нельзя — пароль показывается один раз.
    if (await copyText(text)) {
      setCopied(true);
      setCopyFailed(false);
      setTimeout(() => setCopied(false), 2000);
    } else {
      setCopyFailed(true);
    }
  };

  return (
    <div className="grid gap-4">
      <div className="flex gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-sm">
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        <p>
          {t(
            'hr.pages.employees.newAccount.warning',
            'Передайте эти данные сотруднику. Пароль показывается один раз — потом его можно будет только сбросить.',
          )}
        </p>
      </div>

      <label className="grid gap-2 text-sm">
        {t('hr.pages.employees.newAccount.login', 'Логин')}
        {/* select-all — последний рубеж: если недоступен и буфер обмена, и
            запасной execCommand, пароль всё ещё забирается одним кликом. */}
        <Input value={credentials.email} readOnly className="select-all" />
      </label>

      <label className="grid gap-2 text-sm">
        <span className="flex items-center gap-2">
          <KeyRound className="h-4 w-4" />
          {t('hr.pages.employees.newAccount.password', 'Временный пароль')}
        </span>
        <Input value={credentials.password} readOnly className="select-all font-mono" />
      </label>

      <p className="text-xs text-muted-foreground">
        {t(
          'hr.pages.employees.newAccount.hint',
          'При первом входе сотруднику следует сменить пароль в своём профиле.',
        )}
      </p>

      {copyFailed && (
        <p className="text-xs text-destructive">
          {t(
            'hr.pages.employees.newAccount.copyFailed',
            'Не удалось скопировать — выделите пароль и скопируйте вручную.',
          )}
        </p>
      )}

      <div className="mt-2 flex justify-end gap-2">
        <Button type="button" variant="outline" className="gap-2" onClick={copy}>
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied
            ? t('hr.pages.employees.newAccount.copied', 'Скопировано')
            : t('hr.pages.employees.newAccount.copy', 'Скопировать')}
        </Button>
        <Button type="button" onClick={onDone}>
          {t('hr.pages.employees.newAccount.done', 'Я записал доступы')}
        </Button>
      </div>
    </div>
  );
};

export default NewAccountCredentials;
