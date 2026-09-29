/**
 * Реестр L-01 «Бюджеты» (ТЗ §06, §19): проект, версия, статус, Σ лимит,
 * Σ задействовано, Σ доступно, дата утверждения; фильтры — статус и проект.
 * Строки, которые пользователь видит, и суммы по ним считает сервер: СН и
 * ПМ видят итоги только по статьям своей группы и своим проектам (BR-010).
 *
 * «Создать бюджет» — по узлу `bpp.budgets` `create` (ФД). Колонки «Оплачено
 * факт» пока нет: оплаты появятся со счетами (этап 3).
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { usePermissions } from '@/hooks/usePermissions';

import { BppRegistry } from '../core/BppRegistry';
import { moneyColumn, statusColumn } from '../core/registryColumns';
import type { RegistryColumn, RegistryFilter } from '../core/registryTypes';
import { STATUS_DICTIONARIES } from '../core/statusDictionaries';
import { formatDate } from '../format';
import { projectApi, projectKeys } from '../projects/api';

import { BUDGETS_BASE, BUDGETS_ENDPOINT, type BudgetRow } from './api';
import { lessThan } from './cents';

const DASH = <span className="text-muted-foreground">—</span>;

/** У черновика задействованного и доступного ещё нет — «—», а не нули. */
const notForDraft = (column: RegistryColumn<BudgetRow>): RegistryColumn<BudgetRow> => ({
  ...column,
  render: (row) => (row.status === 'draft' ? DASH : column.render?.(row)),
});

/** Отрицательный остаток (задействовано больше лимита) — красным. */
const negativeInRed = (column: RegistryColumn<BudgetRow>): RegistryColumn<BudgetRow> => ({
  ...column,
  render: (row) => (lessThan(row.available ?? '0', '0')
    ? <span className="text-destructive">{column.render?.(row)}</span>
    : column.render?.(row)),
});

export function BudgetsPage() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const canCreate = permissions.can('bpp.budgets', 'create');

  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    staleTime: 5 * 60 * 1000,
  });

  const columns = useMemo<RegistryColumn<BudgetRow>[]>(() => [
    { key: 'number', title: t('bpp.budgets.number', 'Номер'), required: true },
    {
      key: 'project',
      title: t('bpp.budgets.project', 'Проект'),
      render: (row) => (
        <div className="leading-tight">
          <div className="font-medium">{row.project.code ?? '—'}</div>
          {row.project.name && (
            <div className="text-xs text-muted-foreground">{row.project.name}</div>
          )}
        </div>
      ),
    },
    { key: 'version_no', title: t('bpp.budgets.version', 'Версия'), align: 'right' },
    statusColumn<BudgetRow>(t, 'budget'),
    moneyColumn<BudgetRow>('limit_amount', t('bpp.budgets.limit', 'Σ Лимит'),
      { currency: 'currency_code' }),
    notForDraft(moneyColumn<BudgetRow>('committed', t('bpp.budgets.committed', 'Σ Задействовано'),
      { currency: 'currency_code' })),
    notForDraft(negativeInRed(moneyColumn<BudgetRow>('available',
      t('bpp.budgets.available', 'Σ Доступно'), { currency: 'currency_code' }))),
    {
      key: 'approved_at',
      title: t('bpp.budgets.approvedAt', 'Утверждён'),
      render: (row) => (row.approved_at
        ? (
          <div className="leading-tight">
            <div>{formatDate(row.approved_at)}</div>
            {row.approved_by_name && (
              <div className="text-xs text-muted-foreground">{row.approved_by_name}</div>
            )}
          </div>
        )
        : <span className="text-muted-foreground">—</span>),
    },
  ], [t]);

  const filters = useMemo<RegistryFilter[]>(() => [
    {
      key: 'status',
      label: t('bpp.registry.status', 'Статус'),
      kind: 'select',
      options: Object.entries(STATUS_DICTIONARIES.budget).map(([value, entry]) => ({
        value,
        label: t(entry.labelKey, entry.label),
      })),
    },
    {
      key: 'project_id',
      label: t('bpp.budgets.project', 'Проект'),
      kind: 'select',
      options: (projects.data ?? []).map((project) => ({
        value: project.id,
        label: `${project.code} — ${project.name}`,
      })),
    },
  ], [projects.data, t]);

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">
        {t('bpp.budgets.title', 'Бюджеты')}
      </h2>
      <BppRegistry<BudgetRow>
        registryKey="budgets"
        endpoint={BUDGETS_ENDPOINT}
        columns={columns}
        filters={filters}
        exportName="budgets"
        rowHref={(row) => `${BUDGETS_BASE}/${row.id}`}
        rowLabel={(row) => row.number}
        toolbarExtra={canCreate ? (
          <Button asChild size="sm">
            <Link to={`${BUDGETS_BASE}/new`}>
              <Plus className="mr-1.5 h-4 w-4" />
              {t('bpp.budgets.create', 'Создать бюджет')}
            </Link>
          </Button>
        ) : null}
      />
    </div>
  );
}

export default BudgetsPage;
