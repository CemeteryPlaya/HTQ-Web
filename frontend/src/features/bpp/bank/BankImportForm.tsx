/**
 * Форма загрузки выписки (ТЗ §11.2, A4.1): счёт организации, формат (его
 * задаёт шаблон счёта — выбрать другой нельзя), период, файл до 20 МБ,
 * комментарий.
 *
 * - счетов нет — плашка со ссылкой в «Настройки» (заводит АДМ);
 * - период: у выписки 1С сервер берёт его из файла, поля необязательны; у
 *   Excel и CSV — обязательны, «по» не раньше «с» и не позже сегодня;
 * - «Загрузить» идёт с `Idempotency-Key`: повтор после обрыва сети не
 *   заводит вторую загрузку. Разбор идёт в фоне — после ответа открывается
 *   экран загрузки, он опрашивает ход разбора. Предупреждения о пересечении
 *   периода с прошлыми загрузками приезжают туда же состоянием перехода;
 * - загружает держатель `bpp.bank` `edit` (ФД): без права экран не рисует
 *   форму, которую сервер всё равно отвергнет (403), — как «Новый контрагент»;
 * - «Отмена» возвращает на то место реестра, откуда открыли форму
 *   (`useRegistryBackHref`: кнопка «Загрузить выписку» реестра передаёт его
 *   состоянием перехода так же, как строки).
 */
import { useMemo, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, Loader2, Upload } from 'lucide-react';

import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { usePermissions } from '@/hooks/usePermissions';
import { errorCode, errorDetail, reportApiError } from '@/lib/apiError';
import { DATES_OUT_OF_ORDER, datesOutOfOrder, todayIso } from '@/lib/validation';

import { errorFields } from '../counterparties/errors';
import { useRegistryBackHref } from '../core/registryBack';
import { useIdempotentAction } from '../core/useIdempotentAction';
import { bankSettingsApi, settingsTabHref, ACCOUNTS_KEY } from '../settings/api';
import { FORMAT_ACCEPT, FORMAT_LABELS } from '../settings/templateFields';

import { BANK_BASE, bankImportApi, bankImportHref, MAX_FILE_MB } from './api';

type Field = 'account_id' | 'file' | 'period_from' | 'period_to' | 'comment' | 'form';
type Errors = Partial<Record<Field, string>>;

const FIELDS: Field[] = ['account_id', 'file', 'period_from', 'period_to', 'comment'];

/**
 * Отказ сервера — по полям формы. `fields` у E-IMP-02 называют не поля
 * формы, а недостающие колонки ШАБЛОНА (`date`, `purpose`, …) с текстом
 * заголовка в `message`, — поэтому полный текст отказа (`detail`) ставится
 * у поля файла: это файл не подошёл шаблону. Прочие поля не из формы —
 * текстом `detail` под формой. `null` — полей нет, показывает тост.
 */
function serverErrors(error: unknown): Errors | null {
  const fields = errorFields(error);
  if (fields.length === 0) return null;
  const detail = errorDetail(error);
  if (errorCode(error) === 'E-IMP-02') {
    return { file: detail ?? fields.map((item) => item.message).join(', ') };
  }
  const found: Errors = {};
  for (const item of fields) {
    if (FIELDS.includes(item.field as Field)) {
      found[item.field as Field] = item.message;
    } else {
      found.form = detail ?? item.message;
    }
  }
  return found;
}

export function BankImportForm() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const permissions = usePermissions();
  const canUpload = permissions.can('bpp.bank', 'edit');
  const canConfigure = permissions.can('bpp.settings', 'edit');
  const backHref = useRegistryBackHref(BANK_BASE);

  const accountsQuery = useQuery({
    queryKey: [...ACCOUNTS_KEY, 'active'],
    queryFn: () => bankSettingsApi.accounts(true),
    enabled: canUpload,
  });
  const accounts = useMemo(() => accountsQuery.data ?? [], [accountsQuery.data]);

  const [accountId, setAccountId] = useState('');
  const [periodFrom, setPeriodFrom] = useState('');
  const [periodTo, setPeriodTo] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [comment, setComment] = useState('');
  const [errors, setErrors] = useState<Errors>({});

  const account = accounts.find((item) => item.id === accountId) ?? null;
  const format = account?.template.format ?? null;
  const periodFromFile = format === 'onec';

  const upload = useIdempotentAction((key) => bankImportApi.create(key, {
    account_id: accountId, file: file as File, period_from: periodFrom, period_to: periodTo, comment,
  }));

  const clear = (field: Field) => setErrors((current) => ({ ...current, [field]: undefined, form: undefined }));

  const validate = (): Errors => {
    const found: Errors = {};
    if (!accountId) found.account_id = t('bpp.bank.accountRequired', 'Выберите банковский счёт организации');
    if (!file) {
      found.file = t('bpp.bank.fileRequired', 'Выберите файл выписки');
    } else if (file.size > MAX_FILE_MB * 1024 * 1024) {
      found.file = t('bpp.bank.fileTooBig', 'Файл {{name}} не загружен: допустимы TXT, XLSX, CSV до {{mb}} МБ', {
        name: file.name, mb: MAX_FILE_MB,
      });
    }
    if (!periodFromFile) {
      if (!periodFrom) found.period_from = t('bpp.bank.periodRequired', 'Укажите период выписки');
      if (!periodTo) found.period_to = t('bpp.bank.periodRequired', 'Укажите период выписки');
    }
    if (datesOutOfOrder(periodFrom, periodTo)) {
      found.period_to = DATES_OUT_OF_ORDER;
    } else if (periodTo && periodTo > todayIso()) {
      found.period_to = t('bpp.bank.periodFuture', 'Период выписки не может заканчиваться позже сегодняшнего дня');
    }
    return found;
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found = validate();
    if (Object.keys(found).length > 0) {
      setErrors(found);
      return;
    }
    upload.run().then(
      (created) => {
        navigate(bankImportHref(created.id), { state: { warnings: created.warnings ?? [] } });
      },
      (error: unknown) => {
        const found = serverErrors(error);
        if (found) {
          setErrors(found);
        } else {
          reportApiError(error, t('bpp.bank.uploadFailed', 'Не удалось загрузить выписку'));
        }
      },
    );
  };

  const busy = upload.pending;

  if (!canUpload) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        <Link to={backHref} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          {t('bpp.bank.backToList', 'К списку загрузок')}
        </Link>
        <p className="rounded-2xl border bg-card p-8 text-center text-sm text-muted-foreground">
          {t('bpp.bank.noUpload', 'У вашей роли нет права загружать выписки.')}
        </p>
      </div>
    );
  }

  return (
    <Card className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle className="text-lg">{t('bpp.bank.uploadTitle', 'Загрузка выписки')}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} noValidate className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="imp-account">{t('bpp.bank.accountLabel', 'Банк / счёт организации')}</Label>
            <Select
              value={accountId}
              onValueChange={(value) => { setAccountId(value); clear('account_id'); }}
              disabled={busy || accounts.length === 0}
            >
              <SelectTrigger id="imp-account" aria-invalid={errors.account_id ? true : undefined}>
                <SelectValue placeholder={t('bpp.bank.accountPlaceholder', 'Выберите счёт')} />
              </SelectTrigger>
              <SelectContent>
                {accounts.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.bank_name ? `${item.bank_name} · ` : ''}{item.iban} ({item.currency})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <PrerequisiteNotice
              variant="inline"
              items={[{
                when: accountsQuery.isSuccess && accounts.length === 0,
                text: canConfigure
                  ? t('bpp.bank.noAccounts', 'Действующих счетов организации нет —')
                  : t('bpp.bank.noAccountsAsk', 'Действующих счетов организации нет — их заводит администратор модуля в настройках'),
                to: canConfigure ? settingsTabHref('accounts') : undefined,
                linkText: canConfigure ? t('bpp.bank.addAccountLink', 'заведите счёт в настройках') : undefined,
              }]}
            />
            {accountsQuery.isError && (
              <p role="alert" className="text-xs text-destructive">
                {t('bpp.bank.accountsLoadError', 'Не удалось загрузить счета организации. Обновите страницу.')}
              </p>
            )}
            {errors.account_id && <p className="text-xs text-destructive">{errors.account_id}</p>}
          </div>

          <div className="space-y-1.5">
            <Label>{t('bpp.bank.format', 'Формат файла')}</Label>
            <p className="text-sm" data-testid="import-format">
              {format
                ? t(FORMAT_LABELS[format][0], FORMAT_LABELS[format][1])
                : <span className="text-muted-foreground">{t('bpp.bank.formatHint', 'Определяется шаблоном выбранного счёта')}</span>}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="imp-from">{t('bpp.bank.periodFrom', 'Период с')}</Label>
              <DateInput
                id="imp-from"
                value={periodFrom}
                onChange={(value) => { setPeriodFrom(value); clear('period_from'); clear('period_to'); }}
                disabled={busy}
              />
              {errors.period_from && <p className="text-xs text-destructive">{errors.period_from}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="imp-to">{t('bpp.bank.periodTo', 'Период по')}</Label>
              <DateInput
                id="imp-to"
                value={periodTo}
                onChange={(value) => { setPeriodTo(value); clear('period_to'); }}
                disabled={busy}
              />
              {errors.period_to && <p className="text-xs text-destructive">{errors.period_to}</p>}
            </div>
            {periodFromFile && (
              <p className="text-xs text-muted-foreground sm:col-span-2">
                {t('bpp.bank.periodFromFile', 'У выписки 1С период берётся из файла — поля можно не заполнять.')}
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="imp-file">{t('bpp.bank.file', 'Файл выписки')}</Label>
            <Input
              id="imp-file"
              type="file"
              accept={format ? FORMAT_ACCEPT[format] : '.txt,.xlsx,.csv'}
              onChange={(event) => { setFile(event.target.files?.[0] ?? null); clear('file'); }}
              disabled={busy}
              aria-invalid={errors.file ? true : undefined}
            />
            <p className="text-xs text-muted-foreground">
              {t('bpp.bank.fileHint', 'До {{mb}} МБ и до 10 000 строк. Загружаются только списания со счёта организации.', { mb: MAX_FILE_MB })}
            </p>
            {errors.file && <p className="text-xs text-destructive">{errors.file}</p>}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="imp-comment">{t('bpp.bank.comment', 'Комментарий')}</Label>
            <Textarea
              id="imp-comment"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              disabled={busy}
              rows={3}
            />
            {errors.comment && <p className="text-xs text-destructive">{errors.comment}</p>}
          </div>

          {errors.form && <p role="alert" className="text-sm text-destructive">{errors.form}</p>}

          <div className="flex justify-end gap-2">
            <Button asChild variant="outline">
              <Link to={backHref}>{t('bpp.document.cancel', 'Отмена')}</Link>
            </Button>
            <Button type="submit" disabled={busy}>
              {busy
                ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                : <Upload className="mr-1.5 h-4 w-4" />}
              {t('bpp.bank.uploadSubmit', 'Загрузить')}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export default BankImportForm;
