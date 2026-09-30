/**
 * Реестр L-06 «Счета на оплату» (ТЗ §10.5, §19): вкладки «Все», «На решение
 * ФД», «К оплате», «Ждут закрывающих», «Документы предоставлены»,
 * «Оплачено, банк не подтвердил», «Расхождения с банком»; итоговая строка —
 * Σ в KZT и Σ оплачено по банку по всей выборке (сервер).
 *
 * - Вкладка — параметр `tab` адреса реестра; фильтры и колонки у вкладок
 *   общие (один ключ `localStorage`), отметки строк — свои: смена вкладки
 *   пересоздаёт таблицу.
 * - ФД на вкладке «На решение ФД» решает отмеченные разом: «Оплатить» — с
 *   плановой датой (пусто — срок оплаты каждого счёта), «Не оплачивать» — с
 *   причиной; итог — по каждому счёту (успешные и отклонённые с причиной).
 * - БУХ на вкладке «К оплате» выгружает очередь к оплате (xlsx с IBAN и
 *   назначением платежа).
 * - Кнопки «Создать» нет: счёт оформляется из Плана закупок или из
 *   действующего договора.
 * - Отбор ссылкой (показатель дашборда «Оплаты», D-S4-8): параметры адреса
 *   `tab`, `status`, `recon_status`, `project_id`, `article_id`,
 *   `counterparty_id`, `author_id`, `bank_date_from`/`bank_date_to`,
 *   `bank_wait_days` уходят в запрос реестра как есть, и `total` реестра
 *   совпадает с числом на карточке. Поэтому в таком режиме сохранённые
 *   фильтры панели не подмешиваются (свой ключ `localStorage`, панели
 *   фильтров нет — они сузили бы выборку молча): над таблицей плашка
 *   «Отбор с дашборда» с кнопкой «Показать весь реестр». Смена вкладки
 *   тоже выходит из отбора ссылки — это уже другая выборка. Вкладка в режиме
 *   ссылки — из адреса, вне его — выбор человека: переход из меню «Счета»
 *   (адрес без отбора) не оставляет вкладку, которую выбрала ссылка.
 *   «Экспорт очереди к оплате» отбора ссылки не знает — в этом режиме кнопка
 *   так и подписана: «вся очередь».
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { AlertTriangle, Download } from 'lucide-react';
import { toast } from 'sonner';

import { newIdempotencyKey } from '@/api/files';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { usePermissions } from '@/hooks/usePermissions';
import { reportApiError } from '@/lib/apiError';

import { moneyColumn } from '../budgets/money';
import { BppRegistry } from '../core/BppRegistry';
import { exportRegistry } from '../core/registryExport';
import { currentHoldersColumn, statusColumn } from '../core/registryColumns';
import type {
  BulkOutcome, RegistryBulkAction, RegistryColumn, RegistryFilter,
} from '../core/registryTypes';
import { STATUS_DICTIONARIES } from '../core/statusDictionaries';
import { formatDate } from '../format';
import { projectApi, projectKeys, type Project } from '../projects/api';

import {
  EXPORT_QUEUE_ENDPOINT, INVOICE_LINK_PARAMS, INVOICES_BASE, invoiceApi, invoiceLinkParams,
  invoicesEndpoint, type InvoiceRow,
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
const isTabKey = (value: string | null): value is TabKey =>
  INVOICE_TABS.some((entry) => entry.key === value);

/** Статус сверки с банком (`ReconStatus`, CALC-010). */
const RECON_LABELS: Record<string, string> = {
  no_data: 'Нет данных банка',
  partial: 'Оплачен частично',
  full: 'Оплачен полностью',
  overpaid: 'Переплата',
};

type Translate = ReturnType<typeof useTranslation>['t'];

/** Что отобрано ссылкой — человеческими словами для плашки над реестром.
 * Ключи-UUID не расшифровываются (кроме проекта — его список уже есть):
 * достаточно видеть, что фильтр задан. */
function describeLink(link: URLSearchParams, t: Translate, projects: Project[] | undefined): string[] {
  const out: string[] = [];
  const statuses = link.getAll('status');
  if (statuses.length) {
    const labels = statuses.map((code) => {
      const entry = (STATUS_DICTIONARIES.invoice as Record<string, { labelKey: string; label: string }>)[code];
      return entry ? t(entry.labelKey, entry.label) : code;
    });
    out.push(t('bpp.invoices.link.status', 'Статус: {{list}}', { list: labels.join(', ') }));
  }
  const recon = link.getAll('recon_status');
  if (recon.length) {
    const labels = recon.map((code) => t(`bpp.invoices.recon.${code}`, RECON_LABELS[code] ?? code));
    out.push(t('bpp.invoices.link.recon', 'Сверка с банком: {{list}}', { list: labels.join(', ') }));
  }
  const projectId = link.get('project_id');
  if (projectId) {
    const project = projects?.find((row) => row.id === projectId);
    out.push(project
      ? t('bpp.invoices.link.project', 'Проект: {{name}}', { name: `${project.code} — ${project.name}` })
      : t('bpp.invoices.link.projectSet', 'Проект задан'));
  }
  if (link.get('article_id')) out.push(t('bpp.invoices.link.article', 'Статья задана'));
  if (link.get('counterparty_id')) out.push(t('bpp.invoices.link.counterparty', 'Контрагент задан'));
  if (link.get('author_id')) out.push(t('bpp.invoices.link.author', 'Автор счёта задан'));
  const from = link.get('bank_date_from');
  const to = link.get('bank_date_to');
  if (from || to) {
    out.push(t('bpp.invoices.link.bankPeriod', 'Платёж по банку: {{period}}', {
      period: [
        from && t('bpp.invoices.link.from', 'с {{date}}', { date: formatDate(from) }),
        to && t('bpp.invoices.link.to', 'по {{date}}', { date: formatDate(to) }),
      ].filter(Boolean).join(' '),
    }));
  }
  const waitDays = link.get('bank_wait_days');
  if (waitDays) {
    out.push(t('bpp.invoices.link.bankWait', 'Банк не подтвердил дольше {{n}} раб. дн.', { n: waitDays }));
  }
  return out;
}

const DOC_SHORT: Record<string, string> = { avr: 'АВР', waybill: 'накл.', vat_invoice: 'СФ' };
const COMMENT_MIN = 10;

export function InvoicesPage() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const prompt = usePrompt();
  const [searchParams, setSearchParams] = useSearchParams();
  const link = useMemo(() => invoiceLinkParams(searchParams), [searchParams]);
  const linkKey = link.toString();
  const fromLink = linkKey !== '';
  const urlTab = link.get('tab');
  // Вкладка ссылки — из адреса (новая ссылка при открытом реестре — новая
  // вкладка); вне ссылки — выбор человека. Уход из отбора ссылки переходом из
  // меню возвращает её («Все», если реестр открыли ссылкой), а не вкладку ссылки.
  const [ownTab, setOwnTab] = useState<TabKey>('all');
  const tab: TabKey = fromLink ? (isTabKey(urlTab) ? urlTab : 'all') : ownTab;
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
      (row) => row.amount, { currency: (row) => row.currency_code }),
    moneyColumn<InvoiceRow>('amount_kzt', t('bpp.invoices.amountKzt', 'В тенге'),
      (row) => row.amount_kzt, { total: 'amount_kzt' }),
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
      (row) => row.paid_bank_amount, { total: 'paid_bank_amount' }),
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

  /** Выйти из отбора ссылки: убрать его параметры (и номер страницы) из адреса. */
  const dropLink = () => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    for (const key of INVOICE_LINK_PARAMS) next.delete(key);
    next.delete('page');
    return next;
  }, { replace: true });
  const changeTab = (value: TabKey) => {
    setOwnTab(value);
    if (fromLink) dropLink();
  };
  const showWholeRegistry = () => {
    setOwnTab('all');
    dropLink();
  };
  const linkLabels = fromLink ? describeLink(link, t, projects.data) : [];

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
      <Tabs value={tab} onValueChange={(value) => changeTab(value as TabKey)}>
        <TabsList className="h-auto flex-wrap justify-start">
          {INVOICE_TABS.map((entry) => (
            <TabsTrigger key={entry.key} value={entry.key}>
              {t(`bpp.invoices.tab.${entry.key}`, entry.label)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {fromLink && (
        <div role="note" className="flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-sm">
          <span className="font-medium">{t('bpp.invoices.link.title', 'Отбор с дашборда оплат')}</span>
          {linkLabels.map((label) => (
            <Badge key={label} variant="secondary">{label}</Badge>
          ))}
          <Button variant="ghost" size="sm" className="ml-auto" onClick={showWholeRegistry}>
            {t('bpp.invoices.link.reset', 'Показать весь реестр')}
          </Button>
        </div>
      )}
      <BppRegistry<InvoiceRow>
        key={`${tab}|${linkKey}`}
        // Отбор ссылкой — свой ключ настроек: сохранённые фильтры панели не
        // должны сужать выборку, число которой обещала карточка дашборда.
        registryKey={fromLink ? 'invoices-link' : 'invoices'}
        endpoint={invoicesEndpoint(tab, link)}
        columns={columns}
        filters={fromLink ? [] : filters}
        bulkActions={bulkActions}
        exportName="invoices"
        searchParam="search"
        searchPlaceholder={t('bpp.invoices.search', 'Номер, номер счёта контрагента или БИН')}
        defaultHidden={['article_name', 'docs', 'current_holders']}
        rowHref={(row) => `${INVOICES_BASE}/${row.id}`}
        rowLabel={(row) => row.number}
        toolbarExtra={tab === 'to_pay' && canPay ? (
          // Ручка очереди отбора ссылки не знает: в режиме ссылки выгружается
          // вся очередь, и подпись это говорит, а не обещает отбор дашборда.
          <Button variant="outline" size="sm" onClick={exportQueue} disabled={exporting}
            title={fromLink
              ? t('bpp.invoices.exportQueueAllHint', 'Выгружается вся очередь к оплате, без отбора дашборда')
              : undefined}>
            <Download className="mr-1.5 h-4 w-4" />
            {fromLink
              ? t('bpp.invoices.exportQueueAll', 'Экспорт всей очереди к оплате')
              : t('bpp.invoices.exportQueue', 'Экспорт очереди к оплате')}
          </Button>
        ) : undefined}
      />
      {prompt.dialog}
    </div>
  );
}

export default InvoicesPage;
