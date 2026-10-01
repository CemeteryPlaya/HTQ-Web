/**
 * Форма F-05 «Счёт на оплату» (ТЗ §10): основание (договор или «Без
 * договора»), контрагент, номер и дата счёта контрагента, сумма, валюта и
 * курс, НДС, тип приобретения, аванс, срок оплаты, комментарий, строки
 * позиций плана; решение ФД, отметки оплаты БУХ и закрывающие документы.
 *
 * - Режим и кнопки — из `allowed_actions`; поля правит автор в «Черновике»
 *   и «Возвращён на доработку».
 * - По договору контрагент, валюта, НДС и тип — из договора и не правятся
 *   (§10.3 п.2); виден остаток по договору. «Сделать „Без договора“» снимает
 *   договор со счёта (`PATCH basis: "no_contract"`).
 * - «Копировать номер» — номер счёта в буфер (назначение платежа, переписка).
 * - Без договора сумма выше 1000 МРП на дату счёта закрывает «Отправить ФД»
 *   (BR-040) и предлагает «Оформить договор по этим позициям»: черновик счёта
 *   удаляется — он держит количество позиций, — и из тех же позиций
 *   создаётся договор.
 * - «Оплатить» ФД спрашивает плановую дату оплаты (по умолчанию — срок
 *   оплаты), «Оплачено» БУХ — дату, сумму и номер платёжного поручения.
 * - Вкладка «Файлы» — папка владельца `bpp.invoice` в `apps.files`: файл
 *   счёта (обязателен для «Отправить ФД», `E-FIL-04`) и закрывающие — АВР,
 *   накладная, счёт-фактура. Закрывающие видят только автор, ФД и БУХ и
 *   вкладываются по запросу БУХ; «Документы предоставлены» без файла
 *   запрошенного типа — `E-INV-04` (`services/invoices/file_owner.py`).
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, Copy } from 'lucide-react';
import { toast } from 'sonner';

import { newIdempotencyKey } from '@/api/files';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { usePermissions } from '@/hooks/usePermissions';
import { errorStatus } from '@/lib/apiError';

import { agreementApi } from '../agreements/api';
import { CounterpartyPicker } from '../agreements/CounterpartyPicker';
import { lessThan, sumMoney } from '../budgets/cents';
import { BppDocumentShell, type BppDocumentAction } from '../core/BppDocumentShell';
import { useRegistryBackHref } from '../core/registryBack';
import { useCounterpartyConfirmation } from '../counterparties/useCounterpartyConfirmation';
import { formatDate, formatDateTime, formatMoney, parseMoneyInput } from '../format';
import { AlternativesBlock } from '../alternatives/AlternativesBlock';
import { shownQty } from '../plan/planSelection';
import { refdataApi, refdataKeys } from '../refdata/api';

import {
  INVOICE_HISTORY_TYPE, INVOICE_SUBJECT, INVOICES_BASE, invoiceApi, invoiceKey,
  type InvoiceCard,
} from './api';
import {
  INVOICE_HISTORY_FIELDS, COMMENT_MAX, formOf, localToday, overThreshold, patchOf, submitErrors,
  type InvoiceFormState,
} from './invoiceForm';
import { usePrompt, type PromptValues } from './PromptDialog';
import { MigratedNote } from '../migration/MigratedBadge';
import type { ComparisonOffer } from '../alternatives/api';
import { AlternativeLinksNote } from '../selection/AlternativeLinksNote';
import { documentUrl } from '../selection/links';

const COMMENT_MIN = 10;
const DOC_LABELS: Record<string, string> = {
  avr: 'АВР', waybill: 'Накладная', vat_invoice: 'Счёт-фактура',
};
const PAYMENT_STATUSES = ['partially_paid', 'paid'];

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

function PaymentsTab({ card, canUnmark, onUnmark }: {
  card: InvoiceCard; canUnmark: boolean; onUnmark: (markId: string) => void;
}) {
  const { t } = useTranslation();
  const currency = card.currency_code;
  const unmarkable = canUnmark && PAYMENT_STATUSES.includes(card.status)
    && !lessThan('0', card.paid_bank_amount);
  return (
    <div className="space-y-2">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('bpp.invoices.payDate', 'Дата оплаты')}</TableHead>
            <TableHead className="text-right">{t('bpp.invoices.payAmount', 'Сумма')}</TableHead>
            <TableHead>{t('bpp.invoices.ppNumber', '№ п/п')}</TableHead>
            <TableHead>{t('bpp.invoices.markedBy', 'Отметил')}</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {card.payments.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="text-center text-muted-foreground">
                {t('bpp.invoices.noPayments', 'Отметок оплаты нет')}
              </TableCell>
            </TableRow>
          )}
          {card.payments.map((mark) => (
            <TableRow key={mark.id} className={mark.cancelled_at ? 'text-muted-foreground line-through' : undefined}>
              <TableCell>{formatDate(mark.pay_date)}</TableCell>
              <TableCell className="text-right">{formatMoney(mark.amount, currency)}</TableCell>
              <TableCell>{mark.pp_number || '—'}</TableCell>
              <TableCell>{mark.marked_by_name ?? '—'}</TableCell>
              <TableCell className="text-right">
                {mark.cancelled_at ? (
                  <span className="no-underline" title={mark.cancel_comment}>
                    {t('bpp.invoices.markCancelled', 'отменена {{at}}', { at: formatDateTime(mark.cancelled_at) })}
                  </span>
                ) : unmarkable ? (
                  <Button type="button" variant="ghost" size="sm" onClick={() => onUnmark(mark.id)}>
                    {t('bpp.invoices.unmark', 'Отменить отметку')}
                  </Button>
                ) : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-sm">
        {t('bpp.invoices.paidTotal', 'Оплачено по отметкам')}: {formatMoney(card.paid_amount, currency)}
        {' · '}
        {t('bpp.invoices.unpaid', 'Не оплачено')}: {formatMoney(card.unpaid_amount, currency)}
        {' · '}
        {t('bpp.invoices.paidBank', 'Оплачено по банку')}: {formatMoney(card.paid_bank_amount, currency)}
      </p>
    </div>
  );
}

export function InvoiceFormPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const confirmation = useCounterpartyConfirmation();
  const prompt = usePrompt();

  const { data: card, isLoading, error } = useQuery({
    queryKey: invoiceKey(id),
    queryFn: () => invoiceApi.get(id),
    enabled: Boolean(id),
  });

  const [form, setForm] = useState<InvoiceFormState>(() => formOf(undefined));
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
  const noContract = card?.basis === 'no_contract';
  const thresholdDate = form.ext_date || localToday();

  const threshold = useQuery({
    queryKey: ['bpp', 'invoice-threshold', thresholdDate],
    queryFn: () => invoiceApi.threshold(thresholdDate),
    enabled: Boolean(card) && noContract,
    staleTime: 60 * 60 * 1000,
    retry: false,
  });
  const currencies = useQuery({
    queryKey: refdataKeys.list('currencies', { active: true }),
    queryFn: () => refdataApi.currencies.list({ active: true }),
    enabled: editable && noContract,
    staleTime: 5 * 60 * 1000,
  });

  const apply = useCallback((saved: InvoiceCard) => {
    queryClient.setQueryData(invoiceKey(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'history', INVOICE_HISTORY_TYPE, saved.id] });
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'invoices'] });
  }, [queryClient]);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !card) {
    return (
      <div className="space-y-2">
        <BackLink />
        <p className="text-sm text-muted-foreground">
          {errorStatus(error) === 404
            ? t('bpp.invoices.notFound', 'Счёт не найден или недоступен.')
            : t('bpp.invoices.loadFailed', 'Не удалось загрузить счёт.')}
        </p>
      </div>
    );
  }

  const today = localToday();
  const errors = submitErrors(form, card, today);
  const over = editable ? overThreshold(form, card, threshold.data ?? null) : card.over_threshold;
  const currency = editable ? form.currency_code : card.currency_code;
  const shown = (key: string) => (showErrors ? errors[key] : undefined);
  const setField = <K extends keyof InvoiceFormState>(key: K, value: InvoiceFormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const linesTotal = sumMoney(form.lines.map((line) => parseMoneyInput(line.amount)));

  const save = async (key: string): Promise<InvoiceCard> => {
    const saved = await invoiceApi.save(card.id, key, { ...patchOf(form, card), version: card.version });
    apply(saved);
    return saved;
  };

  const decide = (key: string, decision: 'pay' | 'not_payable' | 'return', comment = '',
    plannedPayDate: string | null = null) =>
    invoiceApi.decide(card.id, key, {
      decision, comment, ...(plannedPayDate ? { planned_pay_date: plannedPayDate } : {}),
    }).then(apply);

  const actions: Record<string, BppDocumentAction> = {
    save: { label: t('bpp.action.save', 'Сохранить'), variant: 'outline', run: save },
    submit: {
      label: t('bpp.invoices.submit', 'Отправить ФД'),
      run: async (key) => {
        setShowErrors(true);
        if (Object.keys(errors).length > 0) {
          throw new Error(t('bpp.invoices.fixErrors', 'Заполните обязательные поля счёта'));
        }
        const fresh = dirty ? await save(`${key}-save`) : card;
        const counterparty = fresh.counterparty!;
        const ok = await confirmation.confirm({
          id: counterparty.id, name: counterparty.name, short_name: counterparty.short_name,
          status: counterparty.status, is_verified: counterparty.is_verified,
        });
        if (!ok) return;
        apply(await invoiceApi.submit(fresh.id, key, fresh.version, !counterparty.is_verified));
      },
    },
    delete: {
      label: t('bpp.action.delete', 'Удалить'),
      variant: 'destructive',
      confirm: { title: t('bpp.invoices.deleteConfirm', 'Удалить черновик счёта? Позиции вернутся в план.') },
      run: async (key) => {
        await invoiceApi.remove(card.id, key, card.version);
        void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'invoices'] });
        navigate(INVOICES_BASE);
      },
    },
    cancel: {
      label: t('bpp.invoices.cancel', 'Отменить счёт'),
      variant: 'destructive',
      confirm: {
        title: t('bpp.invoices.cancelConfirm', 'Отменить счёт? Позиции освободятся, резерв бюджета снимется.'),
        commentMin: COMMENT_MIN,
      },
      run: async (key, comment) =>
        apply(await invoiceApi.cancel(card.id, key, card.version, comment ?? '')),
    },
    pay: {
      label: t('bpp.invoices.pay', 'Оплатить'),
      run: (key) => prompt.ask({
        title: t('bpp.invoices.payTitle', 'Оплатить счёт {{n}}', { n: card.number }),
        description: t('bpp.invoices.payHint', 'Счёт уйдёт бухгалтеру в очередь к оплате.'),
        submitLabel: t('bpp.invoices.pay', 'Оплатить'),
        fields: [{
          key: 'planned', kind: 'date',
          label: t('bpp.invoices.plannedPayDate', 'Плановая дата оплаты'),
          hint: t('bpp.invoices.plannedHint', 'Пусто — срок оплаты счёта'),
        }],
        initial: { planned: card.due_date && card.due_date >= today ? card.due_date : '' },
        validate: (values) => (values.planned && String(values.planned) < today
          ? t('bpp.invoices.plannedPast', 'Плановая дата оплаты — не раньше сегодняшней') : null),
        submit: (values) => decide(key, 'pay', '', String(values.planned) || null),
      }),
    },
    not_payable: {
      label: t('bpp.invoices.notPayable', 'Не оплачивать'),
      variant: 'destructive',
      confirm: { title: t('bpp.invoices.notPayableConfirm', 'Не оплачивать счёт?'), commentMin: COMMENT_MIN },
      run: (key, comment) => decide(key, 'not_payable', comment ?? ''),
    },
    return: {
      label: t('bpp.invoices.return', 'Вернуть на доработку'),
      variant: 'outline',
      confirm: { title: t('bpp.invoices.returnConfirm', 'Вернуть счёт автору на доработку?'), commentMin: COMMENT_MIN },
      run: (key, comment) => decide(key, 'return', comment ?? ''),
    },
    mark_paid: {
      label: t('bpp.invoices.markPaid', 'Оплачено'),
      run: (key) => prompt.ask({
        title: t('bpp.invoices.markPaidTitle', 'Отметка оплаты по счёту {{n}}', { n: card.number }),
        submitLabel: t('bpp.invoices.markPaid', 'Оплачено'),
        fields: [
          { key: 'pay_date', kind: 'date', label: t('bpp.invoices.payDate', 'Дата оплаты'), required: true },
          {
            key: 'amount', kind: 'money', required: true,
            label: t('bpp.invoices.payAmountIn', 'Сумма, {{c}}', { c: card.currency_code }),
            hint: t('bpp.invoices.unpaidHint', 'Не оплачено: {{sum}}', {
              sum: formatMoney(card.unpaid_amount, card.currency_code),
            }),
          },
          { key: 'pp_number', kind: 'text', label: t('bpp.invoices.ppNumber', '№ п/п'), maxLength: 50 },
          ...(card.currency_code !== 'KZT' ? [{
            key: 'rate', kind: 'text' as const, label: t('bpp.invoices.payRate', 'Курс на дату оплаты'),
          }] : []),
        ],
        initial: { pay_date: today, amount: formatMoney(card.unpaid_amount) },
        validate: (values) => {
          if (String(values.pay_date) > today) {
            return t('bpp.invoices.payDateFuture', 'Дата оплаты — не позже сегодняшней');
          }
          const amount = parseMoneyInput(String(values.amount));
          if (amount !== null && lessThan(card.unpaid_amount, amount)) {
            return t('bpp.invoices.overUnpaid', 'Сумма больше неоплаченного остатка ({{sum}})', {
              sum: formatMoney(card.unpaid_amount, card.currency_code),
            });
          }
          if (amount !== null && !lessThan('0', amount)) {
            return t('bpp.invoices.payPositive', 'Сумма оплаты — больше нуля');
          }
          return null;
        },
        submit: (values: PromptValues) => invoiceApi.pay(card.id, key, {
          pay_date: String(values.pay_date),
          amount: parseMoneyInput(String(values.amount)) ?? '0.00',
          pp_number: String(values.pp_number ?? '').trim(),
          rate: values.rate ? String(values.rate).replace(',', '.') : null,
        }).then(apply),
      }),
    },
    request_docs: {
      label: t('bpp.invoices.requestDocs', 'Запросить закрывающие'),
      variant: 'outline',
      run: (key) => prompt.ask({
        title: t('bpp.invoices.requestDocsTitle', 'Какие закрывающие документы нужны?'),
        submitLabel: t('bpp.invoices.requestDocs', 'Запросить закрывающие'),
        fields: [
          { key: 'avr', kind: 'check', label: DOC_LABELS.avr },
          { key: 'waybill', kind: 'check', label: DOC_LABELS.waybill },
          { key: 'vat_invoice', kind: 'check', label: DOC_LABELS.vat_invoice },
          { key: 'comment', kind: 'text', label: t('bpp.document.comment', 'Комментарий'), maxLength: COMMENT_MAX },
        ],
        initial: card.purchase_type === 'goods'
          ? { waybill: true, vat_invoice: card.with_vat }
          : { avr: true, vat_invoice: card.with_vat },
        validate: (values) => (values.avr || values.waybill || values.vat_invoice ? null
          : t('bpp.invoices.docsNone', 'Отметьте хотя бы один документ')),
        submit: (values) => invoiceApi.requestDocs(card.id, key, {
          avr: values.avr === true, waybill: values.waybill === true,
          vat_invoice: values.vat_invoice === true, comment: String(values.comment ?? '').trim(),
        }).then(apply),
      }),
    },
    submit_docs: {
      label: t('bpp.invoices.submitDocs', 'Документы предоставлены'),
      run: async (key) => apply(await invoiceApi.submitDocs(card.id, key)),
    },
    accept_docs: {
      label: t('bpp.invoices.acceptDocs', 'Принять документы'),
      confirm: { title: t('bpp.invoices.acceptDocsConfirm', 'Принять закрывающие документы и закрыть счёт?') },
      run: async (key) => apply(await invoiceApi.acceptDocs(card.id, key)),
    },
    return_docs: {
      label: t('bpp.invoices.returnDocs', 'Вернуть документы'),
      variant: 'outline',
      confirm: { title: t('bpp.invoices.returnDocsConfirm', 'Вернуть документы автору?'), commentMin: COMMENT_MIN },
      run: async (key, comment) => apply(await invoiceApi.returnDocs(card.id, key, comment ?? '')),
    },
  };

  const copyNumber = async () => {
    try {
      await navigator.clipboard.writeText(card.number);
      toast.success(t('bpp.invoices.numberCopied', 'Номер {{n}} скопирован', { n: card.number }));
    } catch {
      toast.error(t('bpp.invoices.copyFailed', 'Не удалось скопировать номер'));
    }
  };

  const dropAgreement = () => {
    const key = newIdempotencyKey();
    void prompt.ask({
      title: t('bpp.invoices.dropAgreementTitle', 'Сделать счёт «Без договора»?'),
      description: t('bpp.invoices.dropAgreementHint',
        'Договор снимется со счёта, контрагент, валюта и НДС станут редактируемыми. '
        + 'Позиции, которые держит договор, без договора не оплачиваются — строки, возможно, придётся поправить.'),
      submitLabel: t('bpp.invoices.dropAgreement', 'Без договора'),
      fields: [],
      submit: async () => apply(await invoiceApi.save(card.id, key, {
        ...patchOf(form, card), basis: 'no_contract', version: card.version,
      })),
    });
  };

  const unmark = (markId: string) => {
    const key = newIdempotencyKey();
    void prompt.ask({
      title: t('bpp.invoices.unmarkTitle', 'Отменить отметку оплаты?'),
      submitLabel: t('bpp.invoices.unmark', 'Отменить отметку'),
      destructive: true,
      fields: [{ key: 'comment', kind: 'comment', label: t('bpp.document.comment', 'Комментарий'), min: COMMENT_MIN }],
      submit: (values) => invoiceApi.unpay(card.id, markId, key, String(values.comment).trim()).then(apply),
    });
  };

  /** «Выбрать» альтернативу (B5.1, ТЗ §12.4 п.3): комментарий обязателен, счёт
   *  «Заменён альтернативой», дальше — новый документ (его черновик ждёт автора
   *  заявки). */
  const selectOffer = (offer: ComparisonOffer) => {
    const key = newIdempotencyKey();
    void prompt.ask({
      title: t('bpp.selection.selectTitle', 'Выбрать альтернативу {{number}}?', { number: offer.number }),
      description: t('bpp.selection.selectHint',
        'Счёт будет заменён альтернативой: его согласование аннулируется, позиции освободятся, '
        + 'на альтернативного контрагента создастся черновик — счёт или договор, если сумма выше 1000 МРП.'),
      submitLabel: t('bpp.selection.select', 'Выбрать'),
      fields: [{ key: 'comment', kind: 'comment', label: t('bpp.document.comment', 'Комментарий'), min: COMMENT_MIN }],
      submit: async (values) => {
        const done = await invoiceApi.selectAlternative(card.id, key, {
          offer_id: offer.id, comment: String(values.comment).trim(), version: card.version,
        });
        apply(done.invoice);
        void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry'] });
        toast.success(t('bpp.selection.done', 'Альтернатива выбрана: создан {{number}}',
          { number: done.result.number }));
        navigate(documentUrl(done.result.type, done.result.id));
      },
    });
  };

  const toAgreement = () => {
    const removeKey = newIdempotencyKey();
    const createKey = newIdempotencyKey();
    void prompt.ask({
      title: t('bpp.invoices.toAgreementTitle', 'Оформить договор по этим позициям?'),
      description: t('bpp.invoices.toAgreementHint',
        'Черновик счёта будет удалён, его позиции перейдут в новый договор.'),
      submitLabel: t('bpp.invoices.toAgreement', 'Оформить договор'),
      fields: [],
      submit: async () => {
        const itemIds = card.lines.map((line) => line.request_item_id);
        await invoiceApi.remove(card.id, removeKey, card.version).catch((reason: unknown) => {
          // Повтор после удачного удаления: черновика уже нет — идём дальше.
          if (errorStatus(reason) !== 404) throw reason;
        });
        const created = await agreementApi.createFromPlan(createKey, itemIds, card.initiator_role || null);
        void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry'] });
        navigate(`/bpp/agreements/${created.id}`);
      },
    });
  };

  const canUnmark = permissions.can('bpp.invoices.payment', 'edit')
    || permissions.can('bpp.invoices.decision', 'edit');
  const shellActions = over === true ? allowed.filter((action) => action !== 'submit') : allowed;
  const showPayments = card.payments.length > 0
    || ['to_pay', 'partially_paid', 'paid', 'awaiting_docs', 'docs_provided', 'closed'].includes(card.status);
  const requestedDocs = Object.entries(card.docs_required).filter(([, need]) => need)
    .map(([key]) => DOC_LABELS[key] ?? key);
  const agreement = card.agreement;

  return (
    <div className="space-y-4">
      <BackLink />
      <BppDocumentShell<InvoiceFormState>
        subjectType={INVOICE_SUBJECT}
        documentId={card.id}
        number={card.number}
        status={{ kind: 'invoice', code: card.status }}
        authorName={card.author_name}
        createdAt={card.created_at}
        allowedActions={shellActions}
        actions={actions}
        readOnly={!editable}
        historyType={INVOICE_HISTORY_TYPE}
        historyFields={INVOICE_HISTORY_FIELDS}
        extraTabs={showPayments ? [{
          key: 'payments', label: t('bpp.invoices.payments', 'Оплаты'),
          content: <PaymentsTab card={card} canUnmark={canUnmark} onUnmark={unmark} />,
        }] : []}
        draft={editable ? {
          value: form, dirty, onRestore: setForm, onSaveDraft: () => save(`draft-${Date.now()}`),
        } : undefined}
      >
        <div className="space-y-6">
          <MigratedNote migrated={card.is_migrated} />
          <AlternativeLinksNote links={card.alternative} />
          {card.status === 'returned' && card.rework_comment && (
            <div role="status" className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-medium">{t('bpp.invoices.returnedTitle', 'Счёт возвращён на доработку')}</div>
                <div>{card.rework_comment}</div>
              </div>
            </div>
          )}
          {card.status_comment && ['not_payable', 'cancelled'].includes(card.status) && (
            <p className="text-sm text-muted-foreground">{card.status_comment}</p>
          )}
          {(card.possible_split || card.counterparty?.status === 'blocked') && (
            <div className="flex flex-wrap gap-2">
              {card.possible_split && (
                <Badge variant="outline" className="border-amber-300 text-amber-800">
                  <AlertTriangle className="mr-1 h-3 w-3" />
                  {t('bpp.invoices.possibleSplit', 'Возможное дробление')}
                </Badge>
              )}
              {card.counterparty?.status === 'blocked' && (
                <Badge variant="destructive">{t('bpp.invoices.counterpartyBlocked', 'Контрагент заблокирован')}</Badge>
              )}
            </div>
          )}

          <div className="-mt-2 flex justify-end">
            <Button type="button" variant="ghost" size="sm" onClick={() => void copyNumber()}>
              <Copy className="mr-1.5 h-4 w-4" />
              {t('bpp.invoices.copyNumber', 'Копировать номер')}
            </Button>
          </div>

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label={t('bpp.invoices.basis', 'Основание')}>
              {agreement ? (
                <p className="text-sm">
                  {t('bpp.invoices.agreement', 'Договор')}{' '}
                  <Link className="text-primary underline" to={`/bpp/agreements/${agreement.id}`}>{agreement.number}</Link>
                  {agreement.ext_number && ` (№ ${agreement.ext_number}${agreement.ext_date ? ` от ${formatDate(agreement.ext_date)}` : ''})`}
                  {agreement.remaining !== null && (
                    <span className="block text-xs text-muted-foreground">
                      {t('bpp.invoices.agreementRemaining', 'Остаток по договору')}: {formatMoney(agreement.remaining, card.currency_code)}
                    </span>
                  )}
                  {agreement.is_open && (
                    <span className="block text-xs text-muted-foreground">{t('bpp.agreements.open', 'Открытый договор')}</span>
                  )}
                </p>
              ) : <p className="text-sm">{t('bpp.invoices.noAgreement', 'Без договора')}</p>}
              {agreement && editable && (
                <Button type="button" variant="link" size="sm" className="h-auto px-0" onClick={dropAgreement}>
                  {t('bpp.invoices.toNoAgreement', 'Сделать «Без договора»')}
                </Button>
              )}
            </Field>
            <Field label={t('bpp.invoices.project', 'Проект / статья')}>
              <p className="text-sm">{card.project.code} — {card.project.name} / {card.article.name}</p>
            </Field>
            <Field label={t('bpp.invoices.counterparty', 'Контрагент')} error={shown('counterparty')} htmlFor="inv-counterparty">
              <CounterpartyPicker
                id="inv-counterparty"
                value={form.counterparty}
                disabled={!editable || !noContract}
                onChange={(counterparty) => setForm({
                  ...form, counterparty, with_vat: counterparty.is_vat_payer, vat_manual: false,
                })}
              />
            </Field>
            <Field label={t('bpp.invoices.extNumberShort', 'Номер счёта контрагента')} error={shown('ext_number')} htmlFor="inv-ext-number">
              {editable ? (
                <Input id="inv-ext-number" value={form.ext_number} maxLength={50}
                  onChange={(event) => setField('ext_number', event.target.value)} />
              ) : <p className="text-sm">{card.ext_number || '—'}</p>}
            </Field>
            <Field label={t('bpp.invoices.extDate', 'Дата счёта')} error={shown('ext_date')} htmlFor="inv-ext-date">
              {editable ? (
                <DateInput id="inv-ext-date" value={form.ext_date} max={today}
                  onChange={(value) => setField('ext_date', value)} />
              ) : <p className="text-sm">{formatDate(card.ext_date)}</p>}
            </Field>
            <Field label={t('bpp.invoices.dueDate', 'Срок оплаты')} error={shown('due_date')} htmlFor="inv-due-date">
              {editable ? (
                <DateInput id="inv-due-date" value={form.due_date}
                  onChange={(value) => setField('due_date', value)} />
              ) : <p className="text-sm">{formatDate(card.due_date)}</p>}
            </Field>
            {card.planned_pay_date && (
              <Field label={t('bpp.invoices.plannedPayDate', 'Плановая дата оплаты')}>
                <p className="text-sm">{formatDate(card.planned_pay_date)}</p>
              </Field>
            )}
            <Field label={t('bpp.invoices.purchaseType', 'Тип приобретения')} error={shown('purchase_type')}>
              {editable && noContract ? (
                <RadioGroup value={form.purchase_type} className="flex gap-4"
                  onValueChange={(value) => setField('purchase_type', value as 'goods' | 'works')}>
                  <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="works" />Работы и услуги</label>
                  <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="goods" />ТМЦ</label>
                </RadioGroup>
              ) : (
                <p className="text-sm">
                  {card.purchase_type === 'goods' ? 'ТМЦ' : card.purchase_type === 'works' ? 'Работы и услуги' : '—'}
                </p>
              )}
            </Field>
            <label className="flex items-center gap-2 self-end text-sm">
              <Checkbox checked={form.is_advance} disabled={!editable}
                onCheckedChange={(checked) => setField('is_advance', checked === true)} />
              {t('bpp.invoices.advance', 'Аванс')}
            </label>
          </section>

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label={t('bpp.invoices.amount', 'Сумма счёта')} error={shown('amount')} htmlFor="inv-amount">
              {editable ? (
                <Input id="inv-amount" className="text-right" inputMode="decimal" value={form.amount}
                  onChange={(event) => setField('amount', event.target.value)}
                  onBlur={() => {
                    const parsed = parseMoneyInput(form.amount);
                    if (parsed !== null) setField('amount', formatMoney(parsed));
                  }} />
              ) : <p className="text-sm">{formatMoney(card.amount, card.currency_code)}</p>}
            </Field>
            <Field label={t('bpp.invoices.currency', 'Валюта')} htmlFor="inv-currency">
              {editable && noContract ? (
                <Select value={form.currency_code}
                  onValueChange={(value) => setForm({ ...form, currency_code: value, rate_manual: false, rate: '' })}>
                  <SelectTrigger id="inv-currency"><SelectValue /></SelectTrigger>
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
            {currency !== 'KZT' && (
              <Field label={t('bpp.invoices.rate', 'Курс к тенге')} htmlFor="inv-rate">
                {editable ? (
                  <div className="flex items-center gap-2">
                    <Input id="inv-rate" className="w-32 text-right" inputMode="decimal"
                      value={form.rate_manual ? form.rate : (card.currency_code === form.currency_code ? card.rate ?? '' : '')}
                      placeholder={t('bpp.invoices.rateNbrk', 'НБРК на дату счёта')}
                      onChange={(event) => setForm({ ...form, rate: event.target.value, rate_manual: true })} />
                    {form.rate_manual && (
                      <Button type="button" variant="link" size="sm" className="px-0"
                        onClick={() => setForm({ ...form, rate_manual: false, rate: '' })}>
                        {t('bpp.invoices.rateReset', 'курс НБРК')}
                      </Button>
                    )}
                  </div>
                ) : (
                  <p className="text-sm">
                    {card.rate ?? '—'}
                    {card.rate_source === 'manual' && (
                      <Badge variant="outline" className="ml-2 border-amber-300 text-amber-800">
                        {t('bpp.invoices.rateManual', 'курс введён вручную')}
                      </Badge>
                    )}
                  </p>
                )}
                {card.amount_kzt && (
                  <p className="text-xs text-muted-foreground">
                    {t('bpp.invoices.amountKzt', 'В тенге')}: {formatMoney(card.amount_kzt, 'KZT')}
                  </p>
                )}
              </Field>
            )}
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <Checkbox checked={form.with_vat} disabled={!editable || !noContract}
                  onCheckedChange={(checked) => setForm({ ...form, with_vat: checked === true })} />
                {t('bpp.invoices.withVat', 'С НДС')}
              </label>
              {form.with_vat && (editable && noContract ? (
                <div className="flex items-center gap-2">
                  <Input aria-label={t('bpp.invoices.vatRate', 'Ставка НДС, %')} className="w-32 text-right"
                    inputMode="decimal" value={form.vat_rate}
                    placeholder={t('bpp.invoices.vatAuto', 'по справочнику')}
                    onChange={(event) => setForm({ ...form, vat_rate: event.target.value, vat_manual: true })} />
                  <span className="text-sm">%</span>
                  {form.vat_manual && (
                    <Button type="button" variant="link" size="sm" className="px-0"
                      onClick={() => setForm({ ...form, vat_manual: false })}>
                      {t('bpp.agreements.vatReset', 'вернуть справочную')}
                    </Button>
                  )}
                </div>
              ) : (
                <p className="text-sm">
                  {card.vat_rate}%{card.vat_amount && ` · ${formatMoney(card.vat_amount, card.currency_code)}`}
                  {card.vat_source === 'manual' && (
                    <Badge variant="outline" className="ml-2 border-amber-300 text-amber-800">
                      {t('bpp.agreements.vatManual', 'ставка изменена вручную')}
                    </Badge>
                  )}
                </p>
              ))}
              {card.vat_warning && <p className="text-xs text-amber-700">{card.vat_warning}</p>}
            </div>
          </section>

          {noContract && over === true && threshold.data && (
            <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/50 p-3 text-sm text-destructive">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span className="flex-1">
                {t('bpp.invoices.overThreshold',
                  'Сумма счёта без договора выше 1000 МРП ({{limit}} на дату счёта) — нужен договор.',
                  { limit: formatMoney(threshold.data, 'KZT') })}
              </span>
              {allowed.includes('delete') && (
                <Button type="button" size="sm" variant="outline" onClick={toAgreement}>
                  {t('bpp.invoices.toAgreementLong', 'Оформить договор по этим позициям')}
                </Button>
              )}
            </div>
          )}

          <Field label={t('bpp.invoices.authorComment', 'Комментарий автора')} htmlFor="inv-comment">
            {editable ? (
              <Textarea id="inv-comment" rows={2} maxLength={COMMENT_MAX} value={form.author_comment}
                onChange={(event) => setField('author_comment', event.target.value)} />
            ) : <p className="text-sm">{card.author_comment || '—'}</p>}
          </Field>

          {(requestedDocs.length > 0 || card.docs_comment) && (
            <section className="space-y-1 rounded-lg border p-3 text-sm">
              <h3 className="font-semibold">{t('bpp.invoices.closingDocs', 'Закрывающие документы')}</h3>
              {requestedDocs.length > 0 && (
                <p>{t('bpp.invoices.docsRequested', 'Запрошены')}: {requestedDocs.join(', ')}
                  {card.docs_requested_at && ` · ${formatDateTime(card.docs_requested_at)}`}
                </p>
              )}
              {card.days_waiting_docs !== null && (
                <p className={card.days_waiting_docs > 5 ? 'text-destructive' : 'text-muted-foreground'}>
                  {t('bpp.invoices.daysWaiting', 'Ждём {{n}} дн.', { n: card.days_waiting_docs })}
                </p>
              )}
              {card.docs_comment && <p className="text-muted-foreground">{card.docs_comment}</p>}
              {allowed.includes('submit_docs') && (
                <p className="text-muted-foreground">
                  {t('bpp.invoices.docsHowTo',
                    'Вложите запрошенные документы на вкладке «Файлы» и нажмите «Документы предоставлены».')}
                </p>
              )}
            </section>
          )}

          <section className="space-y-2">
            <h3 className="text-lg font-semibold">{t('bpp.invoices.lines', 'Строки счёта')}</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('bpp.invoices.item', 'Позиция')}</TableHead>
                  <TableHead>{t('bpp.invoices.itemName', 'Наименование')}</TableHead>
                  {editable && <TableHead className="text-right">{t('bpp.invoices.available', 'Остаток')}</TableHead>}
                  <TableHead className="w-32 text-right">{t('bpp.invoices.qty', 'Кол-во')}</TableHead>
                  <TableHead className="text-right">{t('bpp.invoices.planAmount', 'План')}</TableHead>
                  <TableHead className="w-40 text-right">{t('bpp.invoices.lineAmount', 'Сумма в счёте')}</TableHead>
                  {editable && <TableHead className="w-10" />}
                </TableRow>
              </TableHeader>
              <TableBody>
                {card.lines.filter((line) => !editable || form.lines.some((f) => f.id === line.id)).map((line) => {
                  const row = form.lines.find((f) => f.id === line.id);
                  const patch = (change: Partial<NonNullable<typeof row>>) => setField('lines',
                    form.lines.map((f) => (f.id === line.id ? { ...f, ...change } : f)));
                  const problem = showErrors ? errors[`line:${line.id}`] : undefined;
                  return (
                    <TableRow key={line.id} data-testid="invoice-line">
                      <TableCell>
                        <Link className="text-primary hover:underline" to={`/bpp/requests/${line.request_id}`}>
                          {line.sys_number}
                        </Link>
                      </TableCell>
                      <TableCell>
                        {line.name}
                        {problem && <p className="text-xs text-destructive">{problem}</p>}
                      </TableCell>
                      {editable && <TableCell className="text-right">{shownQty(line.qty_available)}</TableCell>}
                      <TableCell className="text-right">
                        {editable && row ? (
                          <Input className="text-right" inputMode="decimal" value={row.qty}
                            aria-label={`${t('bpp.invoices.qty', 'Кол-во')} ${line.sys_number}`}
                            onChange={(event) => patch({ qty: event.target.value })} />
                        ) : shownQty(line.qty)}
                      </TableCell>
                      <TableCell className="text-right">{formatMoney(line.plan_amount)}</TableCell>
                      <TableCell className="text-right">
                        {editable && row ? (
                          <Input className="text-right" inputMode="decimal" value={row.amount}
                            aria-label={`${t('bpp.invoices.lineAmount', 'Сумма в счёте')} ${line.sys_number}`}
                            onChange={(event) => patch({ amount: event.target.value })} />
                        ) : formatMoney(line.amount)}
                      </TableCell>
                      {editable && (
                        <TableCell>
                          <Button type="button" variant="ghost" size="sm"
                            aria-label={`${t('bpp.invoices.removeLine', 'Убрать строку')} ${line.sys_number}`}
                            onClick={() => setField('lines', form.lines.filter((f) => f.id !== line.id))}>
                            ×
                          </Button>
                        </TableCell>
                      )}
                    </TableRow>
                  );
                })}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell colSpan={editable ? 5 : 4} className="text-right font-medium">
                    {t('bpp.invoices.linesTotal', 'Итого по строкам')}
                  </TableCell>
                  <TableCell className="text-right font-medium">
                    {formatMoney(editable ? linesTotal : sumMoney(card.lines.map((line) => line.amount)))}
                  </TableCell>
                  {editable && <TableCell />}
                </TableRow>
              </TableFooter>
            </Table>
            {showErrors && (errors.lines || errors.lines_total) && (
              <p className="text-sm text-destructive">{errors.lines ?? errors.lines_total}</p>
            )}
          </section>

          {card.basis === 'no_contract' && (
            <AlternativesBlock
              sourceType="invoice" sourceId={card.id}
              renderSelect={allowed.includes('select_alternative') ? (offer) => (
                <Button size="sm" onClick={() => selectOffer(offer)}>
                  {t('bpp.selection.select', 'Выбрать')}
                </Button>
              ) : undefined}
            />
          )}
        </div>
      </BppDocumentShell>
      {confirmation.dialog}
      {prompt.dialog}
    </div>
  );
}

function BackLink() {
  const { t } = useTranslation();
  const back = useRegistryBackHref(INVOICES_BASE);
  return (
    <Link to={back} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" />
      {t('bpp.invoices.back', 'К счетам')}
    </Link>
  );
}

export default InvoiceFormPage;
