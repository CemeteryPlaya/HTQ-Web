/**
 * Форма F-07 «Альтернативное предложение» (ТЗ §12.3).
 *
 * - Сверху — исходный документ только для чтения (номер, статус, контрагент,
 *   сумма, лимит альтернатив) со ссылкой на него.
 * - Автор правит черновик: контрагент (общий `CounterpartyPicker`), валюта,
 *   срок, условия оплаты, обоснование; таблица позиций — галочка «входит в
 *   АП» и цена за единицу. Сумма строки, отклонение %, сумма АП и экономия
 *   считаются на лету в тиынах (`money.ts`); удорожание — оранжевым «Дороже
 *   на …», обоснование тогда не короче 30 знаков (счётчик под полем).
 *   Экономию «на лету» считаем только в валюте исходного документа, иначе —
 *   цифры сервера после сохранения (нужен курс).
 * - Кнопки — из `allowed_actions`: «Сохранить черновик», «Подать»,
 *   «Отозвать», «Удалить черновик»; КП — вкладка «Файлы» общей панели
 *   подсистемы файлов (владелец `bpp.alternative_offer`).
 * - Отказы сервера `E-VAL-01` с `fields` показываются у своего поля.
 * - Знак отклонения: плюс — дороже исходного (как у сервера).
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft } from 'lucide-react';

import { Checkbox } from '@/components/ui/checkbox';
import { Button } from '@/components/ui/button';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { errorStatus } from '@/lib/apiError';

import { CounterpartyPicker } from '../agreements/CounterpartyPicker';
import { BppDocumentShell, type BppDocumentAction } from '../core/BppDocumentShell';
import { useRegistryBackHref } from '../core/registryBack';
import { StatusBadge } from '../core/StatusBadge';
import { errorFields } from '../counterparties/errors';
import { formatDate, formatMoney } from '../format';
import { INVOICES_BASE } from '../invoices/api';
import { localToday } from '../invoices/invoiceForm';
import { refdataApi, refdataKeys } from '../refdata/api';

import {
  ALTERNATIVES_BASE, OFFER_FILE_OWNER, OFFER_HISTORY_TYPE, PAYMENT_TERMS, alternativesApi,
  comparisonKey, offerKey, paymentTermsLabel, type OfferCard,
} from './api';
import {
  JUSTIFICATION_MORE_EXPENSIVE_MIN, deviationLabel, deviationText, formOf, isDearer, patchOf,
  savingFromServer, savingText, submitErrors, totalsOf, type OfferFormState,
} from './offerForm';
import { centsToDecimal } from './money';

const ORANGE = 'text-amber-700 dark:text-amber-400';

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

export function OfferFormPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const backHref = useRegistryBackHref(ALTERNATIVES_BASE);

  const { data: card, isLoading, error } = useQuery({
    queryKey: offerKey(id),
    queryFn: () => alternativesApi.get(id),
    enabled: Boolean(id),
  });
  const allowed = useMemo(() => card?.allowed_actions ?? [], [card?.allowed_actions]);
  const editable = allowed.includes('save');

  // Полный набор позиций исходного документа — чтобы снятую галочку можно
  // было вернуть: из карточки позиция после сохранения уходит.
  const comparison = useQuery({
    queryKey: card ? comparisonKey(card.source.type, card.source.id) : ['bpp', 'alternatives', 'comparison', 'none'],
    queryFn: () => alternativesApi.comparison(card!.source.type, card!.source.id),
    enabled: Boolean(card) && editable,
  });
  const currencies = useQuery({
    queryKey: refdataKeys.list('currencies', { active: true }),
    queryFn: () => refdataApi.currencies.list({ active: true }),
    enabled: editable,
    staleTime: 5 * 60 * 1000,
  });

  const positions = useMemo(() => (comparison.data?.positions ?? []).map((row) => ({
    source_line_id: row.source_line_id, item: row.item, name: row.name, uom: row.uom,
    qty: row.qty, source_price: row.source_price,
  })), [comparison.data]);
  const positionsReady = !editable || !comparison.isLoading;

  const [form, setForm] = useState<OfferFormState>(() => formOf(undefined));
  const [baseline, setBaseline] = useState('');
  const [showErrors, setShowErrors] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const stamp = card ? `${card.id}:${card.version}` : '';
  useEffect(() => {
    if (!card || !positionsReady) return;
    const next = formOf(card, positions);
    setForm(next);
    setBaseline(JSON.stringify(next));
    setShowErrors(false);
    setServerErrors({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp, positionsReady]);

  const dirty = editable && JSON.stringify(form) !== baseline;
  const apply = useCallback((saved: OfferCard) => {
    queryClient.setQueryData(offerKey(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'history', OFFER_HISTORY_TYPE, saved.id] });
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'alternatives'] });
    void queryClient.invalidateQueries({ queryKey: comparisonKey(saved.source.type, saved.source.id) });
  }, [queryClient]);

  if (isLoading || (card && !positionsReady)) return <Skeleton className="h-64 w-full" />;
  if (error || !card) {
    return (
      <div className="space-y-2">
        <BackLink href={backHref} />
        <p className="text-sm text-muted-foreground">
          {errorStatus(error) === 404
            ? t('bpp.alternatives.notFound', 'Альтернатива не найдена или недоступна.')
            : t('bpp.alternatives.loadFailed', 'Не удалось загрузить альтернативу.')}
        </p>
      </div>
    );
  }

  const source = card.source;
  const sourceCurrency = source.currency_code;
  const totals = totalsOf(form, sourceCurrency);
  const serverSaving = savingFromServer(card);
  // Что показывать экономией: в черновике в валюте исходного — «на лету»;
  // в другой валюте и после подачи — цифры сервера (в тенге).
  const liveMode = editable && totals.sameCurrency;
  const shownSaving = liveMode
    ? totals.saving
    : (editable && form.currency_code !== card.currency_code ? null : serverSaving);
  const savingCurrency = liveMode ? form.currency_code : 'KZT';
  const moreExpensive = shownSaving?.moreExpensive ?? false;
  const minJustification = moreExpensive ? JUSTIFICATION_MORE_EXPENSIVE_MIN : 10;

  const clientErrors = submitErrors(form, { moreExpensive, totals, today: localToday() }, t);
  const shown = (key: string): string | undefined =>
    serverErrors[key] ?? (showErrors ? clientErrors[key] : undefined);
  const setField = <K extends keyof OfferFormState>(key: K, value: OfferFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setServerErrors((current) => {
      const rest = { ...current };
      delete rest[key === 'counterparty' ? 'counterparty_id' : key];
      return rest;
    });
  };
  const patchLine = (lineId: string, change: Partial<OfferFormState['lines'][number]>) =>
    setForm((current) => ({
      ...current,
      lines: current.lines.map((row) => (row.source_line_id === lineId ? { ...row, ...change } : row)),
    }));

  /** Отказ сервера по полям — под полями, а не только тостом. */
  const withFieldErrors = async <T,>(run: () => Promise<T>): Promise<T> => {
    try {
      return await run();
    } catch (failure) {
      const fields = errorFields(failure);
      if (fields.length > 0) {
        setServerErrors(Object.fromEntries(fields.map((item) => [item.field, item.message])));
      }
      throw failure;
    }
  };

  const save = (key: string): Promise<OfferCard> => withFieldErrors(async () => {
    const saved = await alternativesApi.save(card.id, key, patchOf(form, card.version));
    apply(saved);
    return saved;
  });

  const actions: Record<string, BppDocumentAction> = {
    save: { label: t('bpp.alternatives.saveDraft', 'Сохранить черновик'), variant: 'outline', run: save },
    submit: {
      label: t('bpp.alternatives.submit', 'Подать'),
      run: async (key) => {
        setShowErrors(true);
        // Только то, что сервер проверит так же и чего не исправить в другом
        // месте: файл КП живёт во вкладке «Файлы» и проверяется сервером.
        if (Object.keys(clientErrors).length > 0) {
          throw new Error(t('bpp.alternatives.fixErrors', 'Заполните обязательные поля альтернативы'));
        }
        const fresh = dirty ? await save(`${key}-save`) : card;
        await withFieldErrors(async () => apply(await alternativesApi.submit(fresh.id, key, fresh.version)));
      },
    },
    withdraw: {
      label: t('bpp.alternatives.withdraw', 'Отозвать'),
      variant: 'outline',
      confirm: { title: t('bpp.alternatives.withdrawConfirm', 'Отозвать альтернативу? Место в лимитах освободится.') },
      run: async (key) => apply(await alternativesApi.withdraw(card.id, key, card.version)),
    },
    delete: {
      label: t('bpp.alternatives.deleteDraft', 'Удалить черновик'),
      variant: 'destructive',
      confirm: { title: t('bpp.alternatives.deleteConfirm', 'Удалить черновик альтернативы вместе с файлами?') },
      run: async (key) => {
        await alternativesApi.remove(card.id, key, card.version);
        void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'alternatives'] });
        void queryClient.invalidateQueries({ queryKey: comparisonKey(source.type, source.id) });
        navigate(ALTERNATIVES_BASE);
      },
    },
  };

  const justificationLength = form.justification.trim().length;
  const sourceHref = source.url || (source.type === 'invoice' ? `${INVOICES_BASE}/${source.id}` : `/bpp/agreements/${source.id}`);
  const kindLabel = source.type === 'invoice'
    ? t('bpp.alternatives.kindInvoice', 'Счёт')
    : t('bpp.alternatives.kindAgreement', 'Договор');
  const shownLines = editable ? form.lines : form.lines.filter((line) => line.included);

  return (
    <div className="space-y-4">
      <BackLink href={backHref} />
      <BppDocumentShell<OfferFormState>
        subjectType="bpp.alternative_offer"
        documentId={card.id}
        number={card.number}
        status={{ kind: 'alternative_offer', code: card.status }}
        authorName={card.author_name}
        allowedActions={allowed}
        actions={actions}
        readOnly={!editable}
        withApproval={false}
        fileOwnerType={OFFER_FILE_OWNER}
        historyType={OFFER_HISTORY_TYPE}
        draft={editable ? {
          value: form, dirty, onRestore: setForm, onSaveDraft: () => save(`draft-${Date.now()}`),
        } : undefined}
      >
        <div className="space-y-6">
          {card.closed_reason && (
            <div role="status" className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>{card.closed_reason}</div>
            </div>
          )}
          {card.decision_comment && (
            <p className="text-sm text-muted-foreground">{card.decision_comment}</p>
          )}

          <section aria-label={t('bpp.alternatives.sourceTitle', 'Исходный документ')}
            className="grid gap-4 rounded-lg border bg-muted/30 p-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label={kindLabel}>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Link className="text-primary hover:underline" to={sourceHref}>{source.number}</Link>
                {source.status && (
                  <StatusBadge kind={source.type === 'invoice' ? 'invoice' : 'contract'} status={source.status} />
                )}
              </div>
            </Field>
            <Field label={t('bpp.alternatives.sourceCounterparty', 'Контрагент документа')}>
              <p className="text-sm">{source.counterparty?.short_name || source.counterparty?.name || '—'}</p>
            </Field>
            <Field label={t('bpp.alternatives.sourceAmount', 'Сумма документа')}>
              <p className="text-sm">
                {source.amount ? formatMoney(source.amount, source.currency_code ?? undefined) : '—'}
              </p>
            </Field>
            <Field label={t('bpp.alternatives.projectArticle', 'Проект / статья')}>
              <p className="text-sm">
                {card.project ? `${card.project.code} — ${card.project.name}` : '—'}
                {card.article ? ` / ${card.article.name}` : ''}
              </p>
            </Field>
            <p className="text-xs text-muted-foreground sm:col-span-2 lg:col-span-4">
              {source.window_open
                ? t('bpp.alternatives.windowOpen', 'Окно подачи открыто, лимит альтернатив на документ — {{limit}}.', { limit: source.alt_limit ?? '—' })
                : t('bpp.alternatives.windowClosed', 'Окно подачи закрыто: по документу уже принято решение.')}
            </p>
          </section>

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label={t('bpp.alternatives.counterparty', 'Контрагент')} error={shown('counterparty_id')} htmlFor="alt-counterparty">
              <CounterpartyPicker
                id="alt-counterparty"
                value={form.counterparty}
                disabled={!editable}
                onChange={(counterparty) => setForm((current) => ({
                  ...current, counterparty, with_vat: counterparty.is_vat_payer,
                }))}
              />
            </Field>
            <Field label={t('bpp.alternatives.currency', 'Валюта')} error={shown('currency_code')} htmlFor="alt-currency">
              {editable ? (
                <Select value={form.currency_code} onValueChange={(value) => setField('currency_code', value)}>
                  <SelectTrigger id="alt-currency"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {!(currencies.data ?? []).some((row) => row.code === form.currency_code) && (
                      <SelectItem value={form.currency_code}>{form.currency_code}</SelectItem>
                    )}
                    {(currencies.data ?? []).map((row) => (
                      <SelectItem key={row.code} value={row.code}>{row.code} — {row.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : <p className="text-sm">{card.currency_code}</p>}
            </Field>
            <label className="flex items-center gap-2 self-end text-sm">
              <Checkbox checked={form.with_vat} disabled={!editable}
                onCheckedChange={(checked) => setField('with_vat', checked === true)} />
              {t('bpp.alternatives.withVat', 'Цены с НДС')}
              {card.vat_rate && form.with_vat && (
                <span className="text-muted-foreground">
                  {card.vat_rate}%{card.vat_amount ? ` · ${formatMoney(card.vat_amount, card.currency_code)}` : ''}
                </span>
              )}
            </label>
            <Field label={t('bpp.alternatives.deliveryDate', 'Срок поставки')} error={shown('delivery_date')} htmlFor="alt-delivery">
              {editable ? (
                <DateInput id="alt-delivery" value={form.delivery_date}
                  onChange={(value) => setField('delivery_date', value)} />
              ) : <p className="text-sm">{formatDate(card.delivery_date)}</p>}
            </Field>
            <Field label={t('bpp.alternatives.paymentTerms', 'Условия оплаты')} error={shown('payment_terms')} htmlFor="alt-terms">
              {editable ? (
                <Select value={form.payment_terms} onValueChange={(value) => setField('payment_terms', value)}>
                  <SelectTrigger id="alt-terms"><SelectValue placeholder={t('bpp.alternatives.choose', 'Выберите')} /></SelectTrigger>
                  <SelectContent>
                    {PAYMENT_TERMS.map((entry) => (
                      <SelectItem key={entry.value} value={entry.value}>
                        {t(`bpp.alternatives.terms.${entry.value}`, entry.label)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : <p className="text-sm">{paymentTermsLabel(card.payment_terms, t)}</p>}
            </Field>
            <Field label={t('bpp.alternatives.termsNote', 'Пояснение к условиям оплаты')} error={shown('payment_terms_note')} htmlFor="alt-note">
              {editable ? (
                <Input id="alt-note" value={form.payment_terms_note} maxLength={2000}
                  onChange={(event) => setField('payment_terms_note', event.target.value)} />
              ) : <p className="text-sm">{card.payment_terms_note || '—'}</p>}
            </Field>
          </section>

          <section className="space-y-2">
            <h3 className="text-lg font-semibold">{t('bpp.alternatives.lines', 'Позиции альтернативы')}</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  {editable && <TableHead className="w-10" />}
                  <TableHead>{t('bpp.alternatives.item', 'Позиция')}</TableHead>
                  <TableHead>{t('bpp.alternatives.itemName', 'Наименование')}</TableHead>
                  <TableHead className="text-right">{t('bpp.alternatives.qty', 'Кол-во')}</TableHead>
                  <TableHead className="text-right">{t('bpp.alternatives.sourcePrice', 'Цена исходная')}</TableHead>
                  <TableHead className="w-40 text-right">{t('bpp.alternatives.price', 'Цена АП за ед.')}</TableHead>
                  <TableHead className="text-right">{t('bpp.alternatives.lineAmount', 'Сумма')}</TableHead>
                  <TableHead className="text-right">{t('bpp.alternatives.deviation', 'Отклонение')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shownLines.map((line) => {
                  const amount = totals.lineAmount.get(line.source_line_id);
                  const deviation = totals.deviation.get(line.source_line_id);
                  const saved = card.lines.find((row) => row.source_line_id === line.source_line_id);
                  const dearer = editable ? deviation !== undefined && deviation > 0n : isDearer(saved?.deviation_pct ?? null);
                  return (
                    <TableRow key={line.source_line_id} data-testid="offer-line"
                      className={line.included ? undefined : 'opacity-50'}>
                      {editable && (
                        <TableCell>
                          <Checkbox checked={line.included}
                            aria-label={`${t('bpp.alternatives.included', 'Входит в АП')} ${line.item}`}
                            onCheckedChange={(checked) => patchLine(line.source_line_id, { included: checked === true })} />
                        </TableCell>
                      )}
                      <TableCell>{line.item}</TableCell>
                      <TableCell>{line.name}</TableCell>
                      <TableCell className="text-right">{line.qty} {line.uom ?? ''}</TableCell>
                      <TableCell className="text-right">{formatMoney(line.source_price)}</TableCell>
                      <TableCell className="text-right">
                        {editable ? (
                          <Input className="text-right" inputMode="decimal" value={line.price}
                            disabled={!line.included}
                            aria-label={`${t('bpp.alternatives.price', 'Цена АП за ед.')} ${line.item}`}
                            onChange={(event) => patchLine(line.source_line_id, { price: event.target.value })} />
                        ) : (saved?.price ? formatMoney(saved.price) : '—')}
                      </TableCell>
                      <TableCell className="text-right">
                        {editable
                          ? (line.included && amount !== undefined ? formatMoney(centsToDecimal(amount)) : '—')
                          : (saved?.amount ? formatMoney(saved.amount) : '—')}
                      </TableCell>
                      <TableCell className={`text-right ${dearer ? ORANGE : ''}`}>
                        {editable
                          ? (line.included && deviation !== undefined ? deviationLabel(deviation) : '—')
                          : deviationText(saved?.deviation_pct ?? null)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell colSpan={editable ? 6 : 5} className="text-right font-medium">
                    {t('bpp.alternatives.offerTotal', 'Сумма АП')}
                  </TableCell>
                  <TableCell className="text-right font-medium" data-testid="offer-total">
                    {editable
                      ? formatMoney(centsToDecimal(totals.offer), form.currency_code)
                      : (card.amount ? formatMoney(card.amount, card.currency_code) : '—')}
                  </TableCell>
                  <TableCell />
                </TableRow>
              </TableFooter>
            </Table>
            {shown('lines') && <p className="text-sm text-destructive">{shown('lines')}</p>}

            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
              {editable && (
                <span>
                  {t('bpp.alternatives.sourcePart', 'Исходная часть')}:{' '}
                  {formatMoney(centsToDecimal(totals.source), sourceCurrency ?? undefined)}
                </span>
              )}
              {shownSaving ? (
                <span data-testid="offer-saving" className={moreExpensive ? `font-medium ${ORANGE}` : 'font-medium'}>
                  {moreExpensive
                    ? savingText(shownSaving, savingCurrency, t('bpp.alternatives.dearer', 'Дороже на'))
                    : `${t('bpp.alternatives.saving', 'Экономия')}: ${savingText(shownSaving, savingCurrency, '')}`}
                </span>
              ) : (
                <span className="text-muted-foreground">
                  {editable && !totals.sameCurrency
                    ? t('bpp.alternatives.savingLater', 'Экономия в тенге — после сохранения, по курсу НБРК')
                    : t('bpp.alternatives.savingNeedPrices', 'Экономия считается, когда введены цены всех позиций')}
                </span>
              )}
            </div>
          </section>

          <section className="space-y-1.5">
            <Label htmlFor="alt-justification">{t('bpp.alternatives.justification', 'Обоснование')}</Label>
            {editable ? (
              <Textarea id="alt-justification" rows={4} maxLength={2000} value={form.justification}
                onChange={(event) => setField('justification', event.target.value)} />
            ) : <p className="whitespace-pre-wrap text-sm">{card.justification || '—'}</p>}
            {editable && (
              <p className={`text-xs ${justificationLength < minJustification ? (moreExpensive ? ORANGE : 'text-muted-foreground') : 'text-muted-foreground'}`}>
                {moreExpensive
                  ? t('bpp.alternatives.justificationDearer', 'Альтернатива дороже исходного — обоснование не короче {{min}} знаков: {{count}} из {{min}}', { min: minJustification, count: justificationLength })
                  : t('bpp.alternatives.justificationHint', 'Не короче {{min}} знаков: {{count}} из {{min}}', { min: minJustification, count: justificationLength })}
              </p>
            )}
            {shown('justification') && <p className="text-xs text-destructive">{shown('justification')}</p>}
          </section>

          <div>
            <p className="text-sm text-muted-foreground">
              {t('bpp.alternatives.filesHint', 'Коммерческое предложение прикладывается на вкладке «Файлы» (обязательно для подачи).')}
            </p>
            {shown('files') && <p className="text-xs text-destructive">{shown('files')}</p>}
          </div>
        </div>
      </BppDocumentShell>
    </div>
  );
}

function BackLink({ href }: { href: string }) {
  const { t } = useTranslation();
  return (
    <Button asChild variant="ghost" size="sm" className="-ml-2">
      <Link to={href}>
        <ArrowLeft className="mr-1.5 h-4 w-4" />
        {t('bpp.alternatives.back', 'К альтернативам')}
      </Link>
    </Button>
  );
}

export default OfferFormPage;
