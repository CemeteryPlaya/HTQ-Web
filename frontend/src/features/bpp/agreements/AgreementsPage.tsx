/**
 * Реестр L-05 «Договоры» (ТЗ §09, §19): номер, номер и дата по документу,
 * контрагент, проект, статья, сумма, остаток по договору (CALC-009),
 * статус, «Сейчас у», срок действия. Выборку режет сервер: СН и ПМ — свои,
 * своих проектов и групп статей и ждущие их решения; директора и БУХ — все.
 *
 * Кнопки «Создать» нет: договор оформляется из Плана закупок (мастер F-03).
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';

import { BppRegistry } from '../core/BppRegistry';
import { currentHoldersColumn, moneyColumn, statusColumn } from '../core/registryColumns';
import type { RegistryColumn, RegistryFilter } from '../core/registryTypes';
import { STATUS_DICTIONARIES } from '../core/statusDictionaries';
import { formatDate } from '../format';
import { projectApi, projectKeys } from '../projects/api';

import { AGREEMENTS_BASE, AGREEMENTS_ENDPOINT, type AgreementRow } from './api';

export function AgreementsPage() {
  const { t } = useTranslation();
  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    staleTime: 5 * 60 * 1000,
  });

  const columns = useMemo<RegistryColumn<AgreementRow>[]>(() => [
    {
      key: 'number',
      title: t('bpp.agreements.number', 'Номер'),
      required: true,
      render: (row) => (
        <span>
          {row.number}
          {row.is_supplement && (
            <Badge variant="outline" className="ml-2">{t('bpp.agreements.supplementShort', 'ДС')}</Badge>
          )}
        </span>
      ),
    },
    {
      key: 'ext_number',
      title: t('bpp.agreements.extNumber', 'Номер и дата'),
      render: (row) => `${row.ext_number || '—'}${row.ext_date ? ` от ${formatDate(row.ext_date)}` : ''}`,
    },
    { key: 'counterparty_name', title: t('bpp.agreements.counterparty', 'Контрагент') },
    { key: 'project_code', title: t('bpp.agreements.project', 'Проект') },
    { key: 'article_name', title: t('bpp.agreements.article', 'Статья') },
    // У открытого договора суммы нет (`amount: null`) — колонка покажет «—».
    moneyColumn<AgreementRow>('amount', t('bpp.agreements.amount', 'Сумма'),
      { currency: 'currency_code' }),
    moneyColumn<AgreementRow>('remaining', t('bpp.agreements.remaining', 'Остаток по договору'),
      { currency: 'currency_code' }),
    statusColumn<AgreementRow>(t, 'contract'),
    currentHoldersColumn<AgreementRow>(t),
    {
      key: 'valid_to',
      title: t('bpp.agreements.validTo', 'Срок действия по'),
      render: (row) => formatDate(row.valid_to),
    },
  ], [t]);

  const filters = useMemo<RegistryFilter[]>(() => [
    {
      key: 'status',
      label: t('bpp.registry.status', 'Статус'),
      kind: 'select',
      options: Object.entries(STATUS_DICTIONARIES.contract).map(([value, entry]) => ({
        value, label: t(entry.labelKey, entry.label),
      })),
    },
    {
      key: 'project_id',
      label: t('bpp.agreements.project', 'Проект'),
      kind: 'select',
      options: (projects.data ?? []).map((project) => ({
        value: project.id, label: `${project.code} — ${project.name}`,
      })),
    },
    {
      key: 'awaiting_me',
      label: t('bpp.requests.awaitingMe', 'Ждёт моего решения'),
      kind: 'select',
      options: [{ value: '1', label: t('bpp.common.yes', 'Да') }],
    },
    { key: 'date_from', label: t('bpp.agreements.dateFrom', 'Дата договора с'), kind: 'date' },
    { key: 'date_to', label: t('bpp.agreements.dateTo', 'Дата договора по'), kind: 'date' },
  ], [projects.data, t]);

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">{t('bpp.agreements.title', 'Договоры')}</h2>
      <BppRegistry<AgreementRow>
        registryKey="agreements"
        endpoint={AGREEMENTS_ENDPOINT}
        columns={columns}
        filters={filters}
        exportName="agreements"
        searchParam="search"
        searchPlaceholder={t('bpp.agreements.search', 'Номер, номер по документу или наименование')}
        defaultHidden={['valid_to']}
        rowHref={(row) => `${AGREEMENTS_BASE}/${row.id}`}
        rowLabel={(row) => row.number}
      />
    </div>
  );
}

export default AgreementsPage;
