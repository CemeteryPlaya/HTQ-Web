/**
 * Форма F-04 «Договор» (ТЗ §09): контрагент, реквизиты по документу, тип,
 * «Открытый договор», сумма и НДС, срок действия, позиции плана; вкладки
 * «Согласование», «Исполнение», «История изменений».
 *
 * - Режим и кнопки — из `allowed_actions`; поля правит автор в «Черновике» и
 *   «На доработке».
 * - Непроверенного контрагента автор подтверждает в окне при отправке (D-20).
 * - Превышение над планом позиций — предупреждение с остатком статьи; больше
 *   остатка — «Отправить» закрыта (ТЗ §9.3 п.5, BR-034).
 * - Ставка НДС — из справочника страны на дату; её можно поправить (D-14),
 *   ручная ставка подсвечена для ФД.
 * - Вкладка «Файлы» — папка владельца `bpp.agreement` в `apps.files`: скан
 *   договора (обязателен для отправки — без него сервер отвечает `E-FIL-04`,
 *   ТЗ §21) и приложения до 30. Менять их может автор в «Черновике» и «На
 *   доработке»; правила — у владельца (`services/agreements/file_owner.py`).
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { errorStatus } from '@/lib/apiError';

import { lessThan } from '../budgets/cents';
import { BppDocumentShell, type BppDocumentAction } from '../core/BppDocumentShell';
import { StatusBadge } from '../core/StatusBadge';
import { useCounterpartyConfirmation } from '../counterparties/useCounterpartyConfirmation';
import { formatDate, formatMoney, parseMoneyInput } from '../format';
import { INVOICES_BASE, invoiceApi } from '../invoices/api';
import { shownQty } from '../plan/planSelection';

import {
  AGREEMENT_HISTORY_TYPE, AGREEMENT_SUBJECT, AGREEMENTS_BASE, agreementApi, agreementKey,
  type AgreementCard, type AgreementType,
} from './api';
import { formOf, overPlan, patchOf, submitErrors, type AgreementFormState } from './agreementForm';
import { CounterpartyPicker } from './CounterpartyPicker';

const COMMENT_MIN = 10;

function Field({ label, error, children, htmlFor }: {
  label: string; error?: string; children: ReactNode; htmlFor?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

function ExecutionTab({ id }: { id: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: [...agreementKey(id), 'execution'],
    queryFn: () => agreementApi.execution(id),
  });
  if (isLoading || !data) return <Skeleton className="h-24 w-full" />;
  return (
    <div className="space-y-2">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('bpp.invoices.number', 'Счёт')}</TableHead>
            <TableHead>{t('bpp.invoices.extNumber', 'Счёт контрагента')}</TableHead>
            <TableHead className="text-right">{t('bpp.invoices.amount', 'Сумма')}</TableHead>
            <TableHead>{t('bpp.registry.status', 'Статус')}</TableHead>
            <TableHead className="text-right">{t('bpp.invoices.paidBank', 'Оплачено факт')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.invoices.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="text-center text-muted-foreground">
                {t('bpp.agreements.noInvoices', 'Счетов по договору пока нет')}
              </TableCell>
            </TableRow>
          )}
          {data.invoices.map((row) => (
            <TableRow key={row.id}>
              <TableCell>
                <Link className="text-primary hover:underline" to={`${INVOICES_BASE}/${row.id}`}>{row.number}</Link>
              </TableCell>
              <TableCell>{row.ext_number} {row.ext_date ? `от ${formatDate(row.ext_date)}` : ''}</TableCell>
              <TableCell className="text-right">{formatMoney(row.amount, row.currency_code)}</TableCell>
              <TableCell><StatusBadge kind="invoice" status={row.status} /></TableCell>
              <TableCell className="text-right">{formatMoney(row.paid_bank_amount)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {data.remaining !== null && (
        <p className="text-sm font-medium">
          {t('bpp.agreements.remaining', 'Остаток по договору')}: {formatMoney(data.remaining)}
        </p>
      )}
    </div>
  );
}

export function AgreementFormPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const confirmation = useCounterpartyConfirmation();

  const { data: card, isLoading, error } = useQuery({
    queryKey: agreementKey(id),
    queryFn: () => agreementApi.get(id),
    enabled: Boolean(id),
  });

  const [form, setForm] = useState<AgreementFormState>(() => formOf(undefined));
  const [baseline, setBaseline] = useState('');
  const [showErrors, setShowErrors] = useState(false);
  const stamp = card ? `${card.id}:${card.version}` : '';
  useEffect(() => {
    const next = formOf(card);
    setForm(next);
    setBaseline(JSON.stringify(next));
    setShowErrors(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp]);

  const allowed = useMemo(() => card?.allowed_actions ?? [], [card?.allowed_actions]);
  const editable = allowed.includes('save');
  const dirty = editable && JSON.stringify(form) !== baseline;

  const apply = useCallback((saved: AgreementCard) => {
    queryClient.setQueryData(agreementKey(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'history', AGREEMENT_HISTORY_TYPE, saved.id] });
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'agreements'] });
  }, [queryClient]);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !card) {
    return (
      <div className="space-y-2">
        <BackLink />
        <p className="text-sm text-muted-foreground">
          {errorStatus(error) === 404
            ? t('bpp.agreements.notFound', 'Договор не найден или недоступен.')
            : t('bpp.agreements.loadFailed', 'Не удалось загрузить договор.')}
        </p>
      </div>
    );
  }

  const errors = submitErrors(form, card);
  const over = overPlan(form, card);
  const available = card.budget?.available ?? null;
  const overBudget = editable && available !== null && lessThan(available, over);
  const currency = card.currency_code;
  const shown = (key: string) => (showErrors ? errors[key] : undefined);
  const setField = <K extends keyof AgreementFormState>(key: K, value: AgreementFormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const save = async (key: string): Promise<AgreementCard> => {
    const saved = await agreementApi.save(card.id, key, { ...patchOf(form, card), version: card.version });
    apply(saved);
    return saved;
  };

  const actions: Record<string, BppDocumentAction> = {
    save: { label: t('bpp.action.save', 'Сохранить'), variant: 'outline', run: save },
    submit: {
      label: t('bpp.requests.submit', 'Отправить на согласование'),
      run: async (key) => {
        setShowErrors(true);
        if (Object.keys(errors).length > 0) {
          throw new Error(t('bpp.agreements.fixErrors', 'Заполните обязательные поля договора'));
        }
        const fresh = dirty ? await save(`${key}-save`) : card;
        const counterparty = fresh.counterparty!;
        const ok = await confirmation.confirm({
          id: counterparty.id, name: counterparty.name, short_name: counterparty.short_name,
          status: counterparty.status, is_verified: counterparty.is_verified,
        });
        if (!ok) return;
        apply(await agreementApi.submit(fresh.id, key, fresh.version, !counterparty.is_verified));
      },
    },
    withdraw: {
      label: t('bpp.requests.withdraw', 'Отозвать'),
      variant: 'outline',
      confirm: { title: t('bpp.agreements.withdrawConfirm', 'Отозвать договор с согласования?') },
      run: async (key) => apply(await agreementApi.withdraw(card.id, key, card.version)),
    },
    fulfil: {
      label: t('bpp.agreements.fulfil', 'Отметить «Исполнен»'),
      variant: 'outline',
      confirm: { title: t('bpp.agreements.fulfilConfirm', 'Отметить договор исполненным? Новые счета по нему будут запрещены.') },
      run: async (key) => apply(await agreementApi.fulfil(card.id, key, card.version)),
    },
    terminate: {
      label: t('bpp.agreements.terminate', 'Расторгнуть'),
      variant: 'destructive',
      confirm: {
        title: t('bpp.agreements.terminateConfirm', 'Расторгнуть договор? Неоплаченные счета останутся, новые — запрещены.'),
        commentMin: COMMENT_MIN,
      },
      run: async (key, comment) =>
        apply(await agreementApi.terminate(card.id, key, card.version, comment ?? '')),
    },
    supplement: {
      label: t('bpp.agreements.supplement', 'Допсоглашение'),
      variant: 'outline',
      run: async (key) => {
        const created = await agreementApi.supplement(card.id, key);
        apply(created);
        navigate(`${AGREEMENTS_BASE}/${created.id}`);
      },
    },
    create_invoice: {
      label: t('bpp.agreements.createInvoice', 'Создать счёт'),
      run: async (key) => {
        const created = await invoiceApi.createFromAgreement(key, card.id);
        void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'invoices'] });
        navigate(`${INVOICES_BASE}/${created.id}`);
      },
    },
    delete: {
      label: t('bpp.action.delete', 'Удалить'),
      variant: 'destructive',
      confirm: { title: t('bpp.agreements.deleteConfirm', 'Удалить черновик договора? Позиции вернутся в план.') },
      run: async (key) => {
        await agreementApi.remove(card.id, key, card.version);
        void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'agreements'] });
        navigate(AGREEMENTS_BASE);
      },
    },
  };

  const shellActions = overBudget ? allowed.filter((action) => action !== 'submit') : allowed;
  const showExecution = ['active', 'fulfilled', 'terminated'].includes(card.status);

  return (
    <div className="space-y-4">
      <BackLink />
      <BppDocumentShell<AgreementFormState>
        subjectType={AGREEMENT_SUBJECT}
        documentId={card.id}
        number={card.number}
        status={{ kind: 'contract', code: card.status }}
        authorName={card.author_name}
        createdAt={card.created_at}
        allowedActions={shellActions}
        actions={actions}
        readOnly={!editable}
        historyType={AGREEMENT_HISTORY_TYPE}
        extraTabs={showExecution ? [{
          key: 'execution', label: t('bpp.requests.execution', 'Исполнение'),
          content: <ExecutionTab id={card.id} />,
        }] : []}
        draft={editable ? {
          value: form, dirty, onRestore: setForm, onSaveDraft: () => save(`draft-${Date.now()}`),
        } : undefined}
      >
        <div className="space-y-6">
          {card.status === 'rework' && card.rework_comment && (
            <div role="status" className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-medium">{t('bpp.agreements.reworkTitle', 'Договор возвращён на доработку')}</div>
                <div>{card.rework_comment}</div>
              </div>
            </div>
          )}
          {card.parent && (
            <p className="text-sm">
              {t('bpp.agreements.supplementTo', 'Дополнительное соглашение к договору')}{' '}
              <Link className="text-primary underline" to={`${AGREEMENTS_BASE}/${card.parent.id}`}>
                {card.parent.number}
              </Link>
              {' — '}
              {t('bpp.agreements.supplementHint', 'сумма — прирост к договору; 0 — без изменения суммы')}
            </p>
          )}
          {card.status_comment && ['terminated'].includes(card.status) && (
            <p className="text-sm text-muted-foreground">{card.status_comment}</p>
          )}

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label={t('bpp.agreements.project', 'Проект / статья')}>
              <p className="text-sm">{card.project.code} — {card.project.name} / {card.article.name}</p>
            </Field>
            <Field label={t('bpp.agreements.counterparty', 'Контрагент')} error={shown('counterparty')} htmlFor="agr-counterparty">
              <CounterpartyPicker
                id="agr-counterparty"
                value={form.counterparty}
                disabled={!editable || card.parent !== null}
                onChange={(counterparty) => setForm({
                  ...form, counterparty, with_vat: counterparty.is_vat_payer, vat_manual: false,
                })}
              />
            </Field>
            <Field label={t('bpp.agreements.name', 'Наименование договора')} error={shown('name')} htmlFor="agr-name">
              {editable ? (
                <Input id="agr-name" value={form.name} maxLength={500}
                  onChange={(event) => setField('name', event.target.value)} />
              ) : <p className="text-sm">{card.name}</p>}
            </Field>
            <Field label={t('bpp.agreements.extNumber', 'Номер договора')} error={shown('ext_number')} htmlFor="agr-ext-number">
              {editable ? (
                <Input id="agr-ext-number" value={form.ext_number} maxLength={50}
                  onChange={(event) => setField('ext_number', event.target.value)} />
              ) : <p className="text-sm">{card.ext_number || '—'}</p>}
            </Field>
            <Field label={t('bpp.agreements.extDate', 'Дата договора')} error={shown('ext_date')} htmlFor="agr-ext-date">
              {editable ? (
                <DateInput id="agr-ext-date" value={form.ext_date}
                  onChange={(value) => setField('ext_date', value)} />
              ) : <p className="text-sm">{formatDate(card.ext_date)}</p>}
            </Field>
            <Field label={t('bpp.agreements.validTo', 'Срок действия по')} error={shown('valid_to')} htmlFor="agr-valid-to">
              {editable ? (
                <DateInput id="agr-valid-to" value={form.valid_to}
                  onChange={(value) => setField('valid_to', value)} />
              ) : <p className="text-sm">{formatDate(card.valid_to)}</p>}
            </Field>
            <Field label={t('bpp.agreements.type', 'Тип договора')} error={shown('agreement_type')}>
              {editable ? (
                <RadioGroup value={form.agreement_type} className="flex gap-4"
                  onValueChange={(value) => setField('agreement_type', value as AgreementType)}>
                  <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="works" />Работы и услуги</label>
                  <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="goods" />ТМЦ</label>
                </RadioGroup>
              ) : <p className="text-sm">{card.agreement_type === 'goods' ? 'ТМЦ' : 'Работы и услуги'}</p>}
            </Field>
          </section>

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={form.is_open} disabled={!editable || card.parent !== null}
                onCheckedChange={(checked) => setForm({ ...form, is_open: checked === true, amount: '' })} />
              {t('bpp.agreements.open', 'Открытый договор')}
            </label>
            {!form.is_open && (
              <Field label={card.parent
                ? t('bpp.agreements.delta', 'Прирост суммы')
                : t('bpp.agreements.amount', 'Сумма договора')} error={shown('amount')} htmlFor="agr-amount">
                {editable ? (
                  <Input id="agr-amount" className="text-right" inputMode="decimal" value={form.amount}
                    onChange={(event) => setField('amount', event.target.value)}
                    onBlur={() => {
                      const parsed = parseMoneyInput(form.amount);
                      if (parsed !== null) setField('amount', formatMoney(parsed));
                    }} />
                ) : <p className="text-sm">{formatMoney(card.amount ?? '0', currency)}</p>}
              </Field>
            )}
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={form.with_vat} disabled={!editable}
                onCheckedChange={(checked) => setForm({ ...form, with_vat: checked === true })} />
              {t('bpp.agreements.withVat', 'С НДС')}
            </label>
            {form.with_vat && (
              <Field label={t('bpp.agreements.vatRate', 'Ставка НДС, %')} htmlFor="agr-vat">
                {editable ? (
                  <div className="flex items-center gap-2">
                    <Input id="agr-vat" className="w-24 text-right" inputMode="decimal" value={form.vat_rate}
                      onChange={(event) => setForm({ ...form, vat_rate: event.target.value, vat_manual: true })} />
                    {form.vat_manual && (
                      <Button type="button" variant="link" size="sm" className="px-0"
                        onClick={() => setForm({ ...form, vat_manual: false })}>
                        {t('bpp.agreements.vatReset', 'вернуть справочную')}
                      </Button>
                    )}
                  </div>
                ) : (
                  <p className="text-sm">
                    {card.vat_rate}%
                    {card.vat_amount && ` · ${formatMoney(card.vat_amount, currency)}`}
                    {card.vat_source === 'manual' && (
                      <Badge variant="outline" className="ml-2 border-amber-300 text-amber-800">
                        {t('bpp.agreements.vatManual', 'ставка изменена вручную')}
                      </Badge>
                    )}
                  </p>
                )}
                {card.vat_warning && <p className="text-xs text-amber-700">{card.vat_warning}</p>}
              </Field>
            )}
          </section>

          {editable && lessThan('0', over) && available !== null && (
            <p role={overBudget ? 'alert' : 'status'} className={overBudget ? 'text-sm text-destructive' : 'text-sm text-amber-700'}>
              {t('bpp.agreements.overPlanText',
                'Сумма договора превышает план позиций на {{over}}; доступный остаток статьи — {{available}}.',
                { over: formatMoney(over, currency), available: formatMoney(available, currency) })}
              {overBudget && ` ${t('bpp.agreements.overBudget', 'Остатка недостаточно — отправка недоступна.')}`}
            </p>
          )}

          {(form.items.length > 0 || card.items.length > 0) && (
            <section className="space-y-2">
              <h3 className="text-lg font-semibold">{t('bpp.agreements.items', 'Позиции договора')}</h3>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('bpp.agreements.item', 'Позиция')}</TableHead>
                    <TableHead>{t('bpp.agreements.itemName', 'Наименование')}</TableHead>
                    <TableHead className="text-right">{t('bpp.agreements.available', 'Остаток')}</TableHead>
                    <TableHead className="w-32 text-right">{t('bpp.agreements.qty', 'Кол-во')}</TableHead>
                    <TableHead className="text-right">{t('bpp.agreements.planAmount', 'План')}</TableHead>
                    {!form.is_open && <TableHead className="w-40 text-right">{t('bpp.agreements.itemAmount', 'Сумма по договору')}</TableHead>}
                    {editable && <TableHead className="w-10" />}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {card.items.filter((item) => form.items.some((f) => f.id === item.id)).map((item) => {
                    const row = form.items.find((f) => f.id === item.id)!;
                    const patch = (change: Partial<typeof row>) => setField('items',
                      form.items.map((f) => (f.id === item.id ? { ...f, ...change } : f)));
                    const error = showErrors ? errors[`item:${item.id}`] : undefined;
                    return (
                      <TableRow key={item.id} data-testid="agreement-item">
                        <TableCell>{item.sys_number}</TableCell>
                        <TableCell>
                          {item.name}
                          {error && <p className="text-xs text-destructive">{error}</p>}
                        </TableCell>
                        <TableCell className="text-right">{shownQty(item.qty_available)} {item.uom ?? ''}</TableCell>
                        <TableCell className="text-right">
                          {editable ? (
                            <Input className="text-right" inputMode="decimal" value={row.qty}
                              aria-label={`${t('bpp.agreements.qty', 'Кол-во')} ${item.sys_number}`}
                              onChange={(event) => patch({ qty: event.target.value })} />
                          ) : shownQty(item.qty)}
                        </TableCell>
                        <TableCell className="text-right">{formatMoney(item.plan_amount)}</TableCell>
                        {!form.is_open && (
                          <TableCell className="text-right">
                            {editable ? (
                              <Input className="text-right" inputMode="decimal" value={row.amount}
                                aria-label={`${t('bpp.agreements.itemAmount', 'Сумма по договору')} ${item.sys_number}`}
                                onChange={(event) => patch({ amount: event.target.value })} />
                            ) : formatMoney(item.amount ?? '0')}
                          </TableCell>
                        )}
                        {editable && (
                          <TableCell>
                            <Button type="button" variant="ghost" size="sm"
                              onClick={() => setField('items', form.items.filter((f) => f.id !== item.id))}>
                              ×
                            </Button>
                          </TableCell>
                        )}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              {showErrors && (errors.items || errors.items_total) && (
                <p className="text-sm text-destructive">{errors.items ?? errors.items_total}</p>
              )}
            </section>
          )}

          {card.supplements.length > 0 && (
            <section className="space-y-1">
              <h3 className="text-lg font-semibold">{t('bpp.agreements.supplements', 'Дополнительные соглашения')}</h3>
              <ul className="space-y-1 text-sm">
                {card.supplements.map((sup) => (
                  <li key={sup.id} className="flex items-center gap-2">
                    <Link className="text-primary hover:underline" to={`${AGREEMENTS_BASE}/${sup.id}`}>{sup.number}</Link>
                    <StatusBadge kind="contract" status={sup.status} />
                    {sup.amount !== null && <span>+{formatMoney(sup.amount, currency)}</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </BppDocumentShell>
      {confirmation.dialog}
    </div>
  );
}

function BackLink() {
  const { t } = useTranslation();
  return (
    <Link to={AGREEMENTS_BASE} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" />
      {t('bpp.agreements.back', 'К договорам')}
    </Link>
  );
}

export default AgreementFormPage;
