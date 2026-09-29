/**
 * Вкладка «Счета организации» экрана «Настройки» (ТЗ §11.2, §18, A3.1):
 * IBAN, банк, БИК, валюта и шаблон, по которому разбирается выписка счёта
 * («счёт определяет шаблон разбора», ТЗ §11.2).
 *
 * IBAN (KZ + 18 знаков, mod 97) и БИК проверяются до запроса тем же
 * правилом, что у счетов контрагентов и на сервере (`E-CTR-04`). IBAN
 * уникален вместе с архивными: второй раз его не завести (422 `E-BNK-01`) —
 * счёт возвращают из архива. Удаления нет, только архив.
 *
 * «Изменить» — та же форма, `PATCH` только изменённых полей с `version`.
 * Так счёт переводят на другой шаблон — без этого шаблон, по которому
 * разбирается действующий счёт, не архивировать (409 `E-STATE-01`). IBAN
 * счёта, по которому уже загружены выписки, сервер менять не даст.
 */
import { useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Loader2, Plus } from 'lucide-react';

import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { errorCode, errorDetail, reportApiError } from '@/lib/apiError';

import { errorFields } from '../counterparties/errors';
import { checkBic, checkIban } from '../counterparties/validation';
import { useIdempotentAction } from '../core/useIdempotentAction';

import {
  ACCOUNTS_KEY, bankSettingsApi, settingsTabHref, TEMPLATES_KEY,
  type AccountInput, type OrgAccount,
} from './api';
import { FORMAT_LABELS } from './templateFields';

const EMPTY: AccountInput = { iban: '', bic: '', bank_name: '', currency: 'KZT', template_id: '' };

type Errors = Partial<Record<keyof AccountInput | 'form', string>>;

/** Форма закрыта, новый счёт или правка существующего. */
type Mode = { kind: 'closed' } | { kind: 'new' } | { kind: 'edit'; account: OrgAccount };

const fromAccount = (account: OrgAccount): AccountInput => ({
  iban: account.iban,
  bic: account.bic,
  bank_name: account.bank_name,
  currency: account.currency,
  template_id: account.template.id,
});

/** Отказ сервера по полям; у дубля IBAN (E-BNK-01) — полный текст: в нём
 * сказано, где уже заведённый счёт и что делать (вернуть из архива). */
function serverErrors(error: unknown): Errors | null {
  const fields = errorFields(error);
  if (fields.length === 0) return null;
  if (errorCode(error) === 'E-BNK-01') return { iban: errorDetail(error) ?? fields[0].message };
  return Object.fromEntries(fields.map((item) => [
    item.field in EMPTY ? item.field : 'form', item.message,
  ]));
}

function ArchiveToggle({ account, onChanged }: { account: OrgAccount; onChanged: () => void }) {
  const { t } = useTranslation();
  const toggle = useIdempotentAction((key) => bankSettingsApi.updateAccount(account.id, key, {
    version: account.version, is_active: !account.is_active,
  }));
  const run = () => {
    toggle.run().then(onChanged, (error: unknown) =>
      reportApiError(error, t('bpp.bankSettings.accountToggleFailed', 'Не удалось изменить счёт')));
  };
  return (
    <Button size="sm" variant="ghost" disabled={toggle.pending} onClick={run}>
      {account.is_active
        ? t('bpp.bankSettings.archive', 'В архив')
        : t('bpp.bankSettings.restore', 'Вернуть из архива')}
    </Button>
  );
}

interface Props {
  canEdit: boolean;
}

export function AccountsTab({ canEdit }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const accounts = useQuery({ queryKey: ACCOUNTS_KEY, queryFn: () => bankSettingsApi.accounts() });
  const templatesQuery = useQuery({
    queryKey: [...TEMPLATES_KEY, 'active'],
    queryFn: () => bankSettingsApi.templates(true),
    enabled: canEdit,
  });
  const [mode, setMode] = useState<Mode>({ kind: 'closed' });
  const [values, setValues] = useState<AccountInput>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});

  const save = useIdempotentAction((key) => {
    const body: AccountInput = {
      ...values, iban: checkIban(values.iban).value ?? values.iban,
      bic: checkBic(values.bic).value ?? values.bic,
    };
    if (mode.kind !== 'edit') return bankSettingsApi.createAccount(key, body);
    const before = fromAccount(mode.account);
    const changed = Object.fromEntries(
      (Object.keys(body) as (keyof AccountInput)[])
        .filter((field) => body[field] !== before[field])
        .map((field) => [field, body[field]]),
    ) as Partial<AccountInput>;
    return bankSettingsApi.updateAccount(mode.account.id, key, {
      ...changed, version: mode.account.version,
    });
  });

  const open = (next: Mode) => {
    setMode(next);
    setValues(next.kind === 'edit' ? fromAccount(next.account) : EMPTY);
    setErrors({});
  };
  const close = () => open({ kind: 'closed' });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'bank'] });
  };

  const set = <K extends keyof AccountInput>(key: K, value: AccountInput[K]) => {
    setValues((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: undefined, form: undefined }));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found: Errors = {};
    const iban = checkIban(values.iban);
    if (!iban.ok) found.iban = iban.message;
    const bic = checkBic(values.bic);
    if (!bic.ok) found.bic = bic.message;
    if (!values.template_id) {
      found.template_id = t('bpp.bankSettings.templateRequired', 'Выберите шаблон выписки');
    }
    if (Object.keys(found).length > 0) {
      setErrors(found);
      return;
    }
    save.run().then(
      () => {
        close();
        refresh();
      },
      (error: unknown) => {
        const found = serverErrors(error);
        if (found) {
          setErrors(found);
        } else {
          reportApiError(error, mode.kind === 'edit'
            ? t('bpp.bankSettings.accountUpdateFailed', 'Не удалось сохранить счёт')
            : t('bpp.bankSettings.accountFailed', 'Не удалось завести счёт'));
        }
      },
    );
  };

  const input = (key: 'iban' | 'bic' | 'bank_name' | 'currency', label: string, mono = false) => (
    <div className="space-y-1.5">
      <Label htmlFor={`org-acc-${key}`}>{label}</Label>
      <Input
        id={`org-acc-${key}`}
        value={values[key]}
        onChange={(event) => set(key, event.target.value)}
        className={mono ? 'font-mono' : undefined}
        aria-invalid={errors[key] ? true : undefined}
        disabled={save.pending}
      />
      {errors[key] && <p className="text-xs text-destructive">{errors[key]}</p>}
    </div>
  );

  const active = templatesQuery.data ?? [];
  // Шаблон счёта мог уйти в архив — в правке он всё равно виден выбранным.
  const current = mode.kind === 'edit' ? mode.account.template : null;
  const templates = current && !active.some((item) => item.id === current.id)
    ? [...active, { id: current.id, name: current.name }]
    : active;
  const rows = accounts.data ?? [];
  const formOpen = mode.kind !== 'closed';
  const formTitle = mode.kind === 'edit'
    ? t('bpp.bankSettings.editAccount', 'Счёт {{iban}}', { iban: mode.account.iban })
    : t('bpp.bankSettings.newAccount', 'Новый счёт организации');

  return (
    <div className="space-y-3">
      {accounts.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : accounts.isError ? (
        <p className="rounded-lg border p-6 text-center text-sm text-destructive">
          {t('bpp.bankSettings.loadError', 'Не удалось загрузить справочник. Обновите страницу.')}
        </p>
      ) : rows.length === 0 ? (
        <p className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
          {canEdit
            ? t('bpp.bankSettings.noAccounts', 'Счетов организации пока нет — заведите счёт, чтобы загружать его выписки.')
            : t('bpp.bankSettings.noAccountsReadOnly', 'Счетов организации пока нет. Их заводит администратор модуля.')}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>IBAN</TableHead>
                <TableHead>{t('bpp.bankSettings.bank', 'Банк')}</TableHead>
                <TableHead>{t('bpp.bankSettings.bic', 'БИК')}</TableHead>
                <TableHead>{t('bpp.bankSettings.currency', 'Валюта')}</TableHead>
                <TableHead>{t('bpp.bankSettings.template', 'Шаблон выписки')}</TableHead>
                <TableHead />
                {canEdit && <TableHead />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((account) => (
                <TableRow key={account.id} className={account.is_active ? undefined : 'opacity-60'}>
                  <TableCell className="font-mono">{account.iban}</TableCell>
                  <TableCell>{account.bank_name || '—'}</TableCell>
                  <TableCell className="font-mono">{account.bic}</TableCell>
                  <TableCell>{account.currency}</TableCell>
                  <TableCell>
                    {account.template.name}
                    <span className="ml-1 text-xs text-muted-foreground">
                      ({t(FORMAT_LABELS[account.template.format][0], FORMAT_LABELS[account.template.format][1])})
                    </span>
                  </TableCell>
                  <TableCell>
                    {!account.is_active && (
                      <Badge variant="outline">{t('bpp.bankSettings.archived', 'Архив')}</Badge>
                    )}
                  </TableCell>
                  {canEdit && (
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={formOpen}
                          onClick={() => open({ kind: 'edit', account })}
                        >
                          {t('bpp.bankSettings.edit', 'Изменить')}
                        </Button>
                        <ArchiveToggle account={account} onChanged={refresh} />
                      </div>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {canEdit && !formOpen && (
        <Button size="sm" variant="outline" onClick={() => open({ kind: 'new' })}>
          <Plus className="mr-1.5 h-4 w-4" />
          {t('bpp.bankSettings.addAccount', 'Добавить счёт')}
        </Button>
      )}

      {canEdit && formOpen && (
        <form
          onSubmit={submit}
          noValidate
          className="space-y-3 rounded-lg border p-3"
          aria-label={formTitle}
        >
          {mode.kind === 'edit' && <p className="text-sm font-medium">{formTitle}</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            {input('iban', 'IBAN', true)}
            {input('bic', t('bpp.bankSettings.bic', 'БИК'), true)}
            {input('bank_name', t('bpp.bankSettings.bank', 'Банк'))}
            {input('currency', t('bpp.bankSettings.currency', 'Валюта'))}
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="org-acc-template">{t('bpp.bankSettings.template', 'Шаблон выписки')}</Label>
              <Select
                value={values.template_id}
                onValueChange={(value) => set('template_id', value)}
                disabled={save.pending || templates.length === 0}
              >
                <SelectTrigger
                  id="org-acc-template"
                  aria-invalid={errors.template_id ? true : undefined}
                >
                  <SelectValue placeholder={t('bpp.bankSettings.templatePlaceholder', 'Выберите шаблон')} />
                </SelectTrigger>
                <SelectContent>
                  {templates.map((template) => (
                    <SelectItem key={template.id} value={template.id}>{template.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <PrerequisiteNotice
                variant="inline"
                items={[{
                  when: templatesQuery.isSuccess && templates.length === 0,
                  text: t('bpp.bankSettings.noActiveTemplates', 'Действующих шаблонов выписок нет —'),
                  to: settingsTabHref('templates'),
                  linkText: t('bpp.bankSettings.createTemplateLink', 'создайте шаблон'),
                }]}
              />
              {errors.template_id && <p className="text-xs text-destructive">{errors.template_id}</p>}
            </div>
          </div>
          {errors.form && <p role="alert" className="text-sm text-destructive">{errors.form}</p>}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={save.pending}
              onClick={close}
            >
              {t('bpp.document.cancel', 'Отмена')}
            </Button>
            <Button type="submit" size="sm" disabled={save.pending}>
              {save.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              {mode.kind === 'edit'
                ? t('bpp.bankSettings.save', 'Сохранить')
                : t('bpp.bankSettings.addAccountSubmit', 'Добавить')}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

export default AccountsTab;
