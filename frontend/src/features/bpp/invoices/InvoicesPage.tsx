/**
 * Реестр L-06 «Счета на оплату» (ТЗ §10.5, §19): вкладки «Все», «На решение
 * ФД», «К оплате», «Ждут закрывающих», «Документы предоставлены»,
 * «Оплачено, банк не подтвердил», «Расхождения с банком»; итоговая строка —
 * Σ в KZT и Σ оплачено по банку по всей выборке (сервер).
 *
 * - Вкладка — параметр `tab` запроса реестра и адреса страницы
 *   (`/bpp/invoices?tab=awaiting_docs`): ссылки дашборда и ежедневной сводки
 *   открывают нужную вкладку, «К списку» с карточки счёта возвращает на неё
 *   же. Смена вкладки правит адрес с `replace` (как листание страниц реестра)
 *   и начинает выборку с первой страницы; неизвестная вкладка в адресе — «Все».
 *   Фильтры и колонки у вкладок общие (один ключ `localStorage`), отметки
 *   строк — свои: смена вкладки пересоздаёт таблицу.
 * - ФД на вкладке «На решение ФД» решает отмеченные разом: «Оплатить» — с
 *   плановой датой (пусто — срок оплаты каждого счёта), «Не оплачивать» — с
 *   причиной; итог — по каждому счёту (успешные и отклонённые с причиной).
 * - БУХ на вкладке «К оплате» выгружает очередь к оплате (xlsx с IBAN и
 *   назначением платежа).
 * - Кнопки «Создать» нет: счёт оформляется из Плана закупок или из
 *   действующего договора.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Download } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

import { newIdempotencyKey } from '@/api/files';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { usePermissions } from '@/hooks/usePermissions';
import { reportApiError } from '@/lib/apiError';

import { BppRegistry } from '../core/BppRegistry';
import { exportRegistry } from '../core/registryExport';
import { currentHoldersColumn, moneyColumn, statusColumn } from '../core/registryColumns';
import type {
  BulkOutcome, RegistryBulkAction, RegistryColumn, RegistryFilter,
} from '../core/registryTypes';
import { STATUS_DICTIONARIES } from '../core/statusDictionaries';
import { URL_PAGE } from '../core/useRegistryState';
import { formatDate } from '../format';
import { projectApi, projectKeys } from '../projects/api';

import {
  EXPORT_QUEUE_ENDPOINT, INVOICES_BASE, INVOICES_ENDPOINT, invoiceApi, type InvoiceRow,
} from './api';
import { localToday } from './invoiceForm';
import { usePrompt } from './PromptDialog';

const INVOICE_TABS = [
  { key: 'all', label: 'Все' },
  { key: 'fd', label: 'На решение ФД' },
  { key: 'to_pay', label: 'К оплате' },
  { key: 'awaiting_docs', label: 'Ждут закрывающих' },
  { key: 'docs_provided', label: 'Документы предоставлены' },
  { key: 'bank_unconfirmed', label: 'Оплачено, банк не подтвердил' },
  { key: 'bank_mismatch', label: 'Расхождения с банком' },
] as const;
type TabKey = (typeof INVOICE_TABS)[number]['key'];

/** Параметр адреса с вкладкой — тот же, что у ручки реестра. */
export const URL_TAB = 'tab';
const isTab = (value: string | null): value is TabKey =>
  INVOICE_TABS.some((entry) => entry.key === value);

const DOC_SHORT: Record<string, string> = { avr: 'АВР', waybill: 'накл.', vat_invoice: 'СФ' };
const COMMENT_MIN = 10;

export function InvoicesPage() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const prompt = usePrompt();
  const [urlParams, setUrlParams] = useSearchParams();
  const rawTab = urlParams.get(URL_TAB);
  const tab: TabKey = isTab(rawTab) ? rawTab : 'all';
  const setTab = useCallback((next: TabKey) => {
    setUrlParams((current) => {
      const params = new URLSearchParams(current);
      if (next === 'all') params.delete(URL_TAB); else params.set(URL_TAB, next);
      params.delete(URL_PAGE);   // другая выборка — с первой страницы
      return params;
    }, { replace: true });
  }, [setUrlParams]);
  // `?tab=all` и неизвестная вкладка — в канонический вид (без параметра):
  // такая ссылка не должна жить в адресе и уходить дальше при копировании.
  useEffect(() => {
    if (rawTab !== null && (!isTab(rawTab) || rawTab === 'all')) setTab('all');
  }, [rawTab, setTab]);
  const [exporting, setExporting] = useState(false);
  const canDecide = permissions.can('bpp.invoices.decision', 'edit');
  const canPay = permissions.can('bpp.invoices.payment', 'edit');

  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    staleTime: 5 * 60 * 1000,
  });

  const columns = useMemo<RegistryColumn<InvoiceRow>[]>(() => [
    {
      key: 'number',
      title: t('bpp.invoices.number', 'Номер'),
      required: true,
      render: (row) => (
        <span>
          {row.number}
          {row.possible_split && (
            <AlertTriangle className="ml-1 inline h-3.5 w-3.5 text-amber-600"
              aria-label={t('bpp.invoices.possibleSplit', 'Возможное дробление')} />
          )}
        </span>
      ),
    },
    {
      key: 'ext_number',
      title: t('bpp.invoices.extNumber', 'Счёт контрагента'),
      render: (row) => `${row.ext_number || '—'}${row.ext_date ? ` от ${formatDate(row.ext_date)}` : ''}`,
    },
    {
      key: 'counterparty_name',
      title: t('bpp.invoices.counterparty', 'Контрагент'),
      render: (row) => (
        <span>
          {row.counterparty_name ?? '—'}
          {row.counterparty_blocked && (
            <Badge variant="destructive" className="ml-2">{t('bpp.invoices.blocked', 'заблокирован')}</Badge>
          )}
        </span>
      ),
    },
    {
      key: 'basis',
      title: t('bpp.invoices.basis', 'Основание'),
      render: (row) => row.agreement_number ?? t('bpp.invoices.noAgreement', 'Без договора'),
    },
    { key: 'project_code', title: t('bpp.invoices.projectShort', 'Проект') },
    { key: 'article_name', title: t('bpp.invoices.article', 'Статья') },
    moneyColumn<InvoiceRow>('amount', t('bpp.invoices.amount', 'Сумма'),
      { currency: 'currency_code' }),
    moneyColumn<InvoiceRow>('amount_kzt', t('bpp.invoices.amountKzt', 'В тенге'),
      { totalKey: 'amount_kzt', totalCurrency: 'KZT' }),
    {
      key: 'due_date',
      title: t('bpp.invoices.dueDate', 'Срок оплаты'),
      render: (row) => (
        <span className={row.overdue ? 'text-destructive' : undefined}>
          {formatDate(row.planned_pay_date ?? row.due_date)}
        </span>
      ),
    },
    statusColumn<InvoiceRow>(t, 'invoice'),
    currentHoldersColumn<InvoiceRow>(t),
    {
      key: 'docs',
      title: t('bpp.invoices.closingDocs', 'Закрывающие'),
      render: (row) => {
        const docs = Object.entries(row.docs_required).filter(([, need]) => need)
          .map(([key]) => DOC_SHORT[key] ?? key);
        if (docs.length === 0) return <span className="text-muted-foreground">—</span>;
        return (
          <span className={row.days_waiting_docs !== null && row.days_waiting_docs > 5 ? 'text-destructive' : undefined}>
            {docs.join(', ')}
            {row.days_waiting_docs !== null && ` · ${row.days_waiting_docs} дн.`}
          </span>
        );
      },
    },
    moneyColumn<InvoiceRow>('paid_bank_amount', t('bpp.invoices.paidBank', 'Оплачено по банку'),
      { totalKey: 'paid_bank_amount' }),
  ], [t]);

  const filters = useMemo<RegistryFilter[]>(() => [
    {
      key: 'status',
      label: t('bpp.registry.status', 'Статус'),
      kind: 'select',
      options: Object.entries(STATUS_DICTIONARIES.invoice).map(([value, entry]) => ({
        value, label: t(entry.labelKey, entry.label),
      })),
    },
    {
      key: 'basis',
      label: t('bpp.invoices.basis', 'Основание'),
      kind: 'select',
      options: [
        { value: 'contract', label: t('bpp.invoices.byContract', 'По договору') },
        { value: 'no_contract', label: t('bpp.invoices.noAgreement', 'Без договора') },
      ],
    },
    {
      key: 'project_id',
      label: t('bpp.invoices.projectShort', 'Проект'),
      kind: 'select',
      options: (projects.data ?? []).map((project) => ({
        value: project.id, label: `${project.code} — ${project.name}`,
      })),
    },
    { key: 'date_from', label: t('bpp.invoices.dateFrom', 'Дата счёта с'), kind: 'date' },
    { key: 'date_to', label: t('bpp.invoices.dateTo', 'Дата счёта по'), kind: 'date' },
  ], [projects.data, t]);

  const batch = (ids: string[], decision: 'pay' | 'not_payable') => {
    const key = newIdempotencyKey();
    let outcome: BulkOutcome | null = null;
    const today = localToday();
    return prompt.ask(decision === 'pay' ? {
      title: t('bpp.invoices.batchPayTitle', 'Оплатить отмеченные счета ({{n}})', { n: ids.length }),
      submitLabel: t('bpp.invoices.pay', 'Оплатить'),
      fields: [{
        key: 'planned', kind: 'date',
        label: t('bpp.invoices.plannedPayDate', 'Плановая дата оплаты'),
        hint: t('bpp.invoices.plannedBatchHint', 'Пусто — срок оплаты каждого счёта'),
      }],
      validate: (values) => (values.planned && String(values.planned) < today
        ? t('bpp.invoices.plannedPast', 'Плановая дата оплаты — не раньше сегодняшней') : null),
      submit: async (values) => {
        outcome = await invoiceApi.batchDecision(key, {
          invoice_ids: ids, decision,
          ...(values.planned ? { planned_pay_date: String(values.planned) } : {}),
        });
      },
    } : {
      title: t('bpp.invoices.batchNotPayableTitle', 'Не оплачивать отмеченные счета ({{n}})', { n: ids.length }),
      submitLabel: t('bpp.invoices.notPayable', 'Не оплачивать'),
      destructive: true,
      fields: [{ key: 'comment', kind: 'comment', label: t('bpp.document.comment', 'Комментарий'), min: COMMENT_MIN }],
      submit: async (values) => {
        outcome = await invoiceApi.batchDecision(key, {
          invoice_ids: ids, decision, comment: String(values.comment).trim(),
        });
      },
    }).then((done) => (done ? outcome : null));
  };

  const bulkActions: RegistryBulkAction[] = tab === 'fd' && canDecide ? [
    { key: 'pay', label: t('bpp.invoices.batchPay', 'Оплатить отмеченные'), run: (ids) => batch(ids, 'pay') },
    {
      key: 'not_payable', label: t('bpp.invoices.batchNotPayable', 'Не оплачивать отмеченные'),
      run: (ids) => batch(ids, 'not_payable'),
    },
  ] : [];

  const exportQueue = async () => {
    setExporting(true);
    try {
      const result = await exportRegistry(EXPORT_QUEUE_ENDPOINT, {}, 'payment-queue');
      if (result.kind === 'queued') {
        toast.info(t('bpp.registry.exportQueued', 'Выгрузка готовится, ссылка придёт уведомлением'));
      }
    } catch (error) {
      reportApiError(error, t('bpp.invoices.queueExportFailed', 'Не удалось выгрузить очередь к оплате'));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">{t('bpp.invoices.title', 'Счета на оплату')}</h2>
      <Tabs value={tab} onValueChange={(value) => setTab(value as TabKey)}>
        <TabsList className="h-auto flex-wrap justify-start">
          {INVOICE_TABS.map((entry) => (
            <TabsTrigger key={entry.key} value={entry.key}>
              {t(`bpp.invoices.tab.${entry.key}`, entry.label)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <BppRegistry<InvoiceRow>
        key={tab}
        registryKey="invoices"
        endpoint={tab === 'all' ? INVOICES_ENDPOINT : `${INVOICES_ENDPOINT}?tab=${tab}`}
        columns={columns}
        filters={filters}
        bulkActions={bulkActions}
        exportName="invoices"
        searchParam="search"
        searchPlaceholder={t('bpp.invoices.search', 'Номер, номер счёта контрагента или БИН')}
        defaultHidden={['article_name', 'docs', 'current_holders']}
        rowHref={(row) => `${INVOICES_BASE}/${row.id}`}
        rowLabel={(row) => row.number}
        toolbarExtra={tab === 'to_pay' && canPay ? (
          <Button variant="outline" size="sm" onClick={exportQueue} disabled={exporting}>
            <Download className="mr-1.5 h-4 w-4" />
            {t('bpp.invoices.exportQueue', 'Экспорт очереди к оплате')}
          </Button>
        ) : undefined}
      />
      {prompt.dialog}
    </div>
  );
}

export default InvoicesPage;
