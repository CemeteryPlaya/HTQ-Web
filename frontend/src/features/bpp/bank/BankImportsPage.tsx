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
 * Быстрого поиска у ручки нет, поэтому и поля поиска на экране нет
 * (`searchable={false}`): загрузки находят фильтрами по счёту, периоду и
 * статусу.
 *
 * «Загрузить выписку» — по узлу `bpp.bank` `edit` (ФД); БУХ смотрит.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';
import { Upload } from 'lucide-react';

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

export function BankImportsPage() {
  const { t } = useTranslation();
  const location = useLocation();
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

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">{t('bpp.bank.title', 'Оплаты факт')}</h2>
      <BppRegistry<BankImportRow>
        registryKey="bank-imports"
        endpoint={BANK_IMPORTS_ENDPOINT}
        columns={columns}
        filters={filters}
        exportName="bank-imports"
        searchable={false}
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
