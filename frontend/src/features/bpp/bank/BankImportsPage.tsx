/**
 * Реестр L-07 «Загрузки выписок» (ТЗ §05 п.7, §11, §19; A4.1): номер, банк,
 * счёт, период, дата загрузки, кто загрузил, строк в файле, списаний,
 * дублей, ошибок, статус; «Сопоставлено» и «Не сопоставлено» (ТЗ §19) —
 * скрытыми по умолчанию колонками: выгрузка несёт их всегда, и экран может
 * показать то же, что в файле. Фильтры — счёт, период, статус; выборку и
 * страницы считает сервер (`GET bpp/v1/bank/imports`), экспорт в xlsx —
 * той же ручкой (`?format=xlsx`).
 *
 * Сортировки у ручки нет (порядок один — новые сверху), поэтому ни одна
 * колонка не сортируемая: заголовок-кнопка, которая ничего не меняет, хуже
 * простого заголовка. «Статус» из общего набора колонок сортируемый — здесь
 * это снято явно.
 *
 * Быстрый поиск — номер загрузки (`ВП-…`) или комментарий: ручка понимает
 * `q` (как реестр контрагентов), выгрузка идёт по той же выборке.
 *
 * «Загрузить выписку» — по узлу `bpp.bank` `edit` (ФД); БУХ смотрит.
 *
 * Отбор ссылкой (показатель «Несопоставленные списания» дашборда «Оплаты»):
 * `period_from`/`period_to` адреса страницы уходят в запрос реестра как есть
 * — загрузки, чей период выписки пересекается с периодом дашборда. В таком
 * режиме сохранённые фильтры панели не подмешиваются (свой ключ
 * `localStorage`, панели фильтров нет — они сузили бы выборку молча): над
 * таблицей плашка «Отбор по ссылке» с кнопкой «Показать все загрузки».
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { Upload } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { usePermissions } from '@/hooks/usePermissions';

import { BppRegistry } from '../core/BppRegistry';
import { registryOpenState } from '../core/registryBack';
import { statusColumn } from '../core/registryColumns';
import type { RegistryColumn, RegistryFilter } from '../core/registryTypes';
import { STATUS_DICTIONARIES } from '../core/statusDictionaries';
import { formatDate, formatDateTime } from '../format';
import { ACCOUNTS_KEY, bankSettingsApi } from '../settings/api';

import { BANK_BASE, BANK_IMPORTS_ENDPOINT, bankImportHref, type BankImportRow } from './api';

/** Параметры адреса, которые приходят ссылкой (дашборд «Оплаты») и уходят в
 * запрос реестра как есть — имена совпадают с параметрами `GET bank/imports`. */
const BANK_LINK_PARAMS = ['period_from', 'period_to'] as const;

/** Отбор ссылки из адреса страницы; пусто — отбора нет. */
function bankLinkParams(search: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  for (const key of BANK_LINK_PARAMS) {
    const value = search.get(key);
    if (value) out.set(key, value);
  }
  return out;
}

export function BankImportsPage() {
  const { t } = useTranslation();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const link = useMemo(() => bankLinkParams(searchParams), [searchParams]);
  const linkKey = link.toString();
  const fromLink = linkKey !== '';
  const permissions = usePermissions();
  const canUpload = permissions.can('bpp.bank', 'edit');

  const accounts = useQuery({
    queryKey: ACCOUNTS_KEY,
    queryFn: () => bankSettingsApi.accounts(),
    staleTime: 5 * 60 * 1000,
  });

  const columns = useMemo<RegistryColumn<BankImportRow>[]>(() => [
    { key: 'number', title: t('bpp.bank.number', 'Номер'), required: true },
    { key: 'bank_name', title: t('bpp.bank.bankName', 'Банк') },
    {
      key: 'account',
      title: t('bpp.bank.account', 'Счёт'),
      render: (row) => <span className="font-mono">{row.account.iban}</span>,
    },
    {
      key: 'period',
      title: t('bpp.bank.period', 'Период'),
      render: (row) => `${formatDate(row.period_from)} – ${formatDate(row.period_to)}`,
    },
    {
      key: 'created_at',
      title: t('bpp.bank.createdAt', 'Дата загрузки'),
      render: (row) => formatDateTime(row.created_at),
    },
    {
      key: 'author_name',
      title: t('bpp.bank.author', 'Кто загрузил'),
      render: (row) => row.author_name || '—',
    },
    { key: 'rows_total', title: t('bpp.bank.rowsTotal', 'Строк в файле'), align: 'right' },
    { key: 'debits', title: t('bpp.bank.debits', 'Списаний'), align: 'right' },
    { key: 'duplicates', title: t('bpp.bank.duplicates', 'Дублей'), align: 'right' },
    { key: 'errors_count', title: t('bpp.bank.errorsCount', 'Ошибок'), align: 'right' },
    { key: 'matched', title: t('bpp.bank.matched', 'Сопоставлено'), align: 'right' },
    { key: 'unmatched', title: t('bpp.bank.unmatched', 'Не сопоставлено'), align: 'right' },
    { ...statusColumn<BankImportRow>(t, 'bank_import'), sortable: false },
  ], [t]);

  const filters = useMemo<RegistryFilter[]>(() => [
    {
      key: 'account_id',
      label: t('bpp.bank.account', 'Счёт'),
      kind: 'select',
      options: (accounts.data ?? []).map((account) => ({
        value: account.id,
        label: `${account.bank_name ? `${account.bank_name} · ` : ''}${account.iban}`,
      })),
    },
    { key: 'period_from', label: t('bpp.bank.periodFrom', 'Период с'), kind: 'date' },
    { key: 'period_to', label: t('bpp.bank.periodTo', 'Период по'), kind: 'date' },
    {
      key: 'status',
      label: t('bpp.registry.status', 'Статус'),
      kind: 'select',
      options: Object.entries(STATUS_DICTIONARIES.bank_import).map(([value, def]) => ({
        value,
        label: t(def.labelKey, def.label),
      })),
    },
  ], [accounts.data, t]);

  /** Выйти из отбора ссылки: убрать его параметры (и номер страницы) из адреса. */
  const dropLink = () => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    for (const key of BANK_LINK_PARAMS) next.delete(key);
    next.delete('page');
    return next;
  }, { replace: true });
  const linkFrom = link.get('period_from');
  const linkTo = link.get('period_to');
  const linkPeriod = [
    linkFrom && t('bpp.bank.link.from', 'с {{date}}', { date: formatDate(linkFrom) }),
    linkTo && t('bpp.bank.link.to', 'по {{date}}', { date: formatDate(linkTo) }),
  ].filter(Boolean).join(' ');

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">{t('bpp.bank.title', 'Оплаты факт')}</h2>
      {fromLink && (
        <div role="note" className="flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-sm">
          <span className="font-medium">{t('bpp.bank.link.title', 'Отбор по ссылке')}</span>
          <Badge variant="secondary">
            {t('bpp.bank.link.period', 'Период выписки: {{period}}', { period: linkPeriod })}
          </Badge>
          <Button variant="ghost" size="sm" className="ml-auto" onClick={dropLink}>
            {t('bpp.bank.link.reset', 'Показать все загрузки')}
          </Button>
        </div>
      )}
      <BppRegistry<BankImportRow>
        key={linkKey}
        // Отбор ссылкой — свой ключ настроек: сохранённые фильтры панели
        // (счёт, статус, другой период) не должны молча сужать его выборку.
        registryKey={fromLink ? 'bank-imports-link' : 'bank-imports'}
        endpoint={fromLink ? `${BANK_IMPORTS_ENDPOINT}?${linkKey}` : BANK_IMPORTS_ENDPOINT}
        columns={columns}
        filters={fromLink ? [] : filters}
        exportName="bank-imports"
        searchParam="q"
        searchPlaceholder={t('bpp.bank.search', 'Номер или комментарий')}
        defaultHidden={['matched', 'unmatched']}
        rowHref={(row) => bankImportHref(row.id)}
        rowLabel={(row) => row.number}
        toolbarExtra={canUpload ? (
          <Button asChild size="sm">
            {/* Место в реестре — с переходом, как у строк: «Отмена» формы вернёт сюда же. */}
            <Link to={`${BANK_BASE}/new`} state={registryOpenState(location.search)}>
              <Upload className="mr-1.5 h-4 w-4" />
              {t('bpp.bank.upload', 'Загрузить выписку')}
            </Link>
          </Button>
        ) : null}
      />
    </div>
  );
}

export default BankImportsPage;
