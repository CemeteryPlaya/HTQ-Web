/**
 * Банковские счета контрагента (ТЗ §18): IBAN Казахстана (KZ + 18 знаков,
 * mod 97) и БИК (8 или 11 знаков) проверяются до запроса тем же правилом,
 * что на сервере (`validation.ts`), иначе — E-CTR-04 от сервера у поля.
 *
 * Править счета вправе держатель `bpp.counterparties` `edit` (ФД, БУХ) — об
 * этом говорит действие `add_account` карточки. Основной счёт один: сервер
 * снимает признак с прежнего сам. Удаления нет — счёт уходит в архив
 * (`is_active: false`) и остаётся в старых документах.
 */
import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Plus } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { reportApiError } from '@/lib/apiError';

import { useIdempotentAction } from '../core/useIdempotentAction';

import { counterpartyApi, type BankAccount, type BankAccountInput } from './api';
import { errorFields } from './errors';
import { checkBic, checkIban } from './validation';

interface Props {
  counterpartyId: string;
  accounts: BankAccount[];
  canEdit: boolean;
  /** Счета изменились — карточку надо перечитать. */
  onChanged: () => void;
}

const EMPTY: BankAccountInput = { iban: '', bic: '', bank_name: '', currency: 'KZT', is_primary: false };

type Errors = Partial<Record<keyof BankAccountInput, string>>;

function AccountRowActions({ account, onChanged }: { account: BankAccount; onChanged: () => void }) {
  const { t } = useTranslation();
  const makePrimary = useIdempotentAction((key) =>
    counterpartyApi.updateAccount(account.id, key, { is_primary: true }));
  const archive = useIdempotentAction((key) =>
    counterpartyApi.updateAccount(account.id, key, { is_active: false }));
  const busy = makePrimary.pending || archive.pending;

  const run = (action: { run: () => Promise<unknown> }) => {
    action.run().then(onChanged, (error: unknown) =>
      reportApiError(error, t('bpp.counterparties.accountFailed', 'Не удалось изменить счёт')));
  };

  if (!account.is_active) return null;
  return (
    <div className="flex justify-end gap-1">
      {!account.is_primary && (
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(makePrimary)}>
          {t('bpp.counterparties.makePrimary', 'Сделать основным')}
        </Button>
      )}
      <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(archive)}>
        {t('bpp.counterparties.accountArchive', 'В архив')}
      </Button>
    </div>
  );
}

export function BankAccountsPanel({ counterpartyId, accounts, canEdit, onChanged }: Props) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  const [values, setValues] = useState<BankAccountInput>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});

  const add = useIdempotentAction((key) => counterpartyApi.addAccount(counterpartyId, key, values));

  const set = <K extends keyof BankAccountInput>(key: K, value: BankAccountInput[K]) => {
    setValues((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: undefined }));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found: Errors = {};
    const iban = checkIban(values.iban);
    if (!iban.ok) found.iban = iban.message;
    const bic = checkBic(values.bic);
    if (!bic.ok) found.bic = bic.message;
    if (Object.keys(found).length > 0) {
      setErrors(found);
      return;
    }
    add.run().then(
      () => {
        setValues(EMPTY);
        setAdding(false);
        onChanged();
      },
      (error: unknown) => {
        const fields = errorFields(error);
        if (fields.length > 0) {
          setErrors(Object.fromEntries(fields.map((item) => [item.field, item.message])));
        } else {
          reportApiError(error, t('bpp.counterparties.accountFailed', 'Не удалось изменить счёт'));
        }
      },
    );
  };

  const input = (key: 'iban' | 'bic' | 'bank_name' | 'currency', label: string, mono = false) => (
    <div className="space-y-1.5">
      <Label htmlFor={`acc-${key}`}>{label}</Label>
      <Input
        id={`acc-${key}`}
        value={values[key]}
        onChange={(event) => set(key, event.target.value)}
        className={mono ? 'font-mono' : undefined}
        aria-invalid={errors[key] ? true : undefined}
        disabled={add.pending}
      />
      {errors[key] && <p className="text-xs text-destructive">{errors[key]}</p>}
    </div>
  );

  return (
    <div className="space-y-3">
      {accounts.length === 0 ? (
        <p className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
          {t('bpp.counterparties.noAccounts', 'Банковских счетов пока нет')}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>IBAN</TableHead>
                <TableHead>{t('bpp.counterparties.bic', 'БИК')}</TableHead>
                <TableHead>{t('bpp.counterparties.bank', 'Банк')}</TableHead>
                <TableHead>{t('bpp.counterparties.currency', 'Валюта')}</TableHead>
                <TableHead />
                {canEdit && <TableHead />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.map((account) => (
                <TableRow key={account.id} className={account.is_active ? undefined : 'opacity-60'}>
                  <TableCell className="font-mono">{account.iban}</TableCell>
                  <TableCell className="font-mono">{account.bic}</TableCell>
                  <TableCell>{account.bank_name || '—'}</TableCell>
                  <TableCell>{account.currency}</TableCell>
                  <TableCell>
                    {account.is_primary && <Badge>{t('bpp.counterparties.primary', 'Основной')}</Badge>}
                    {!account.is_active && (
                      <Badge variant="outline">{t('bpp.counterparties.accountArchived', 'Архив')}</Badge>
                    )}
                  </TableCell>
                  {canEdit && (
                    <TableCell>
                      <AccountRowActions account={account} onChanged={onChanged} />
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {canEdit && !adding && (
        <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
          <Plus className="mr-1.5 h-4 w-4" />
          {t('bpp.counterparties.addAccount', 'Добавить счёт')}
        </Button>
      )}

      {canEdit && adding && (
        <form onSubmit={submit} noValidate className="space-y-3 rounded-lg border p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            {input('iban', 'IBAN', true)}
            {input('bic', t('bpp.counterparties.bic', 'БИК'), true)}
            {input('bank_name', t('bpp.counterparties.bank', 'Банк'))}
            {input('currency', t('bpp.counterparties.currency', 'Валюта'))}
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={values.is_primary}
              onCheckedChange={(checked) => set('is_primary', checked === true)}
              disabled={add.pending}
            />
            {t('bpp.counterparties.primaryAccount', 'Основной счёт')}
          </label>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={add.pending}
              onClick={() => { setAdding(false); setValues(EMPTY); setErrors({}); }}
            >
              {t('bpp.document.cancel', 'Отмена')}
            </Button>
            <Button type="submit" size="sm" disabled={add.pending}>
              {add.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              {t('bpp.counterparties.addAccountSubmit', 'Добавить')}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

export default BankAccountsPanel;
