/**
 * Реестр L-02 «Заявки на закупку» (ТЗ §07, §19): номер, дата, автор, роль,
 * проект, статья, сумма, статус, «Сейчас у», дата потребности; фильтры —
 * статус, проект, период, «Ждёт моего решения». СН и ПМ видят свои заявки и
 * те, что ждут их решения, директора — все: выборку режет сервер.
 *
 * «Создать заявку» — по узлу `bpp.requests` `create` (СН, ПМ).
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { usePermissions } from '@/hooks/usePermissions';

import { moneyColumn } from '../budgets/money';
import { BppRegistry } from '../core/BppRegistry';
import { currentHoldersColumn, statusColumn } from '../core/registryColumns';
import type { RegistryColumn, RegistryFilter } from '../core/registryTypes';
import { STATUS_DICTIONARIES } from '../core/statusDictionaries';
import { formatDate } from '../format';
import { projectApi, projectKeys } from '../projects/api';

import { REQUESTS_BASE, REQUESTS_ENDPOINT, type RequestRow } from './api';
import { ROLE_LABELS } from './requestForm';

export function RequestsPage() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const canCreate = permissions.can('bpp.requests', 'create');

  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    staleTime: 5 * 60 * 1000,
  });

  const columns = useMemo<RegistryColumn<RequestRow>[]>(() => [
    { key: 'number', title: t('bpp.requests.number', 'Номер'), required: true },
    {
      key: 'created_at',
      title: t('bpp.requests.createdAt', 'Дата'),
      render: (row) => formatDate(row.created_at),
    },
    { key: 'author_name', title: t('bpp.requests.author', 'Автор') },
    {
      key: 'initiator_role',
      title: t('bpp.requests.role', 'Роль'),
      render: (row) => ROLE_LABELS[row.initiator_role] ?? '—',
    },
    { key: 'project_code', title: t('bpp.requests.project', 'Проект') },
    { key: 'article_name', title: t('bpp.requests.article', 'Статья') },
    moneyColumn<RequestRow>('total_amount', t('bpp.requests.amount', 'Сумма'),
      (row) => row.total_amount, { currency: (row) => row.currency_code, total: 'total_amount' }),
    statusColumn<RequestRow>(t, 'request'),
    currentHoldersColumn<RequestRow>(t),
    {
      key: 'need_date',
      title: t('bpp.requests.needDate', 'Дата потребности'),
      render: (row) => formatDate(row.need_date),
    },
  ], [t]);

  const filters = useMemo<RegistryFilter[]>(() => [
    {
      key: 'status',
      label: t('bpp.registry.status', 'Статус'),
      kind: 'select',
      options: Object.entries(STATUS_DICTIONARIES.request).map(([value, entry]) => ({
        value, label: t(entry.labelKey, entry.label),
      })),
    },
    {
      key: 'project_id',
      label: t('bpp.requests.project', 'Проект'),
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
    { key: 'created_from', label: t('bpp.requests.createdFrom', 'Создана с'), kind: 'date' },
    { key: 'created_to', label: t('bpp.requests.createdTo', 'Создана по'), kind: 'date' },
  ], [projects.data, t]);

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">
        {t('bpp.requests.title', 'Заявки на закупку')}
      </h2>
      <BppRegistry<RequestRow>
        registryKey="requests"
        endpoint={REQUESTS_ENDPOINT}
        columns={columns}
        filters={filters}
        exportName="requests"
        searchParam="search"
        searchPlaceholder={t('bpp.requests.search', 'Поиск по номеру заявки')}
        defaultHidden={['need_date']}
        rowHref={(row) => `${REQUESTS_BASE}/${row.id}`}
        rowLabel={(row) => row.number}
        toolbarExtra={canCreate ? (
          <Button asChild size="sm">
            <Link to={`${REQUESTS_BASE}/new`}>
              <Plus className="mr-1.5 h-4 w-4" />
              {t('bpp.requests.create', 'Создать заявку')}
            </Link>
          </Button>
        ) : null}
      />
    </div>
  );
}

export default RequestsPage;
